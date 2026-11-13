"""Opt-in forwarding, filters, rate limits and problem watchers."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.grok_bot.hub import SendBudget, in_quiet_hours

from .conftest import posted, setup_entry


async def test_nothing_forwarded_by_default(hass, webhook_mock):
    hass.states.async_set("sensor.temp", "20")
    await setup_entry(hass)
    hass.states.async_set("sensor.temp", "25")
    hass.bus.async_fire("zha_event", {"x": 1})
    logging.getLogger("homeassistant.components.zha").error("boom")
    await hass.async_block_till_done()
    assert posted(webhook_mock) == []


async def test_state_forwarding_with_cooldown(hass, webhook_mock):
    hass.states.async_set("binary_sensor.door", "off")
    await setup_entry(hass, forward_entities=["binary_sensor.door"], min_interval=300)
    dropped = async_capture_events(hass, "grok_bot_dropped")
    hass.states.async_set("binary_sensor.door", "on")
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.door", "off")  # inside the cooldown
    await hass.async_block_till_done()
    hass.states.async_set("binary_sensor.door", "off", {"x": 1})  # attribute noise
    await hass.async_block_till_done()
    payloads = posted(webhook_mock)
    assert len(payloads) == 1
    assert payloads[0]["type"] == "state_changed"
    assert payloads[0]["data"]["to_state"] == "on"
    assert payloads[0]["source"] == "binary_sensor.door"
    assert dropped[0].data["reason"] == "dropped_cooldown"


async def test_to_states_filter_and_template(hass, webhook_mock):
    hass.states.async_set("alarm_control_panel.home", "disarmed")
    await setup_entry(
        hass,
        forward_entities=["alarm_control_panel.home"],
        min_interval=0,
        filters={"alarm_control_panel.home": {"to_states": ["triggered"]}},
        template_state="ALARM {{ to_state.state }} on {{ entity_id }}",
        state_action="fix",
    )
    hass.states.async_set("alarm_control_panel.home", "armed_away")
    await hass.async_block_till_done()
    hass.states.async_set("alarm_control_panel.home", "triggered")
    await hass.async_block_till_done()
    payloads = posted(webhook_mock)
    assert len(payloads) == 1
    assert payloads[0]["message"] == "ALARM triggered on alarm_control_panel.home"
    assert payloads[0]["allow_fix"] is True


async def test_threshold_crossing_and_attribute(hass, webhook_mock):
    hass.states.async_set("sensor.temp", "20")
    hass.states.async_set("climate.room", "heat", {"current_temperature": 19})
    await setup_entry(
        hass,
        forward_entities=["sensor.temp", "climate.room"],
        min_interval=0,
        filters={
            "sensor.temp": {"above": 30},
            "climate.room": {"attribute": "current_temperature", "below": 15},
        },
    )
    for value in ("25", "31", "35", "29", "32"):
        hass.states.async_set("sensor.temp", value)
        await hass.async_block_till_done()
    hass.states.async_set("climate.room", "heat", {"current_temperature": 14})
    await hass.async_block_till_done()
    sent = [(p["source"], p["data"]["to_state"]) for p in posted(webhook_mock)]
    # 31 crosses, 35 stays above, 29 leaves, 32 crosses again; climate crosses below 15
    assert sent == [("sensor.temp", "31"), ("sensor.temp", "32"), ("climate.room", "heat")]


async def test_ignore_unavailable(hass, webhook_mock):
    hass.states.async_set("sensor.temp", "20")
    await setup_entry(hass, forward_entities=["sensor.temp"], min_interval=0)
    hass.states.async_set("sensor.temp", "unavailable")
    await hass.async_block_till_done()
    assert posted(webhook_mock) == []


async def test_event_forwarding(hass, webhook_mock):
    await setup_entry(hass, forward_events=["zha_event", "state_changed"], min_interval=300)
    hass.bus.async_fire("zha_event", {"command": "on"})
    hass.bus.async_fire("zha_event", {"command": "off"})  # cooldown
    hass.bus.async_fire("other_event", {})
    await hass.async_block_till_done()
    payloads = posted(webhook_mock)
    assert len(payloads) == 1  # state_changed is never forwarded
    assert payloads[0]["data"]["event_data"] == {"command": "on"}


async def test_automatic_sends_respect_budget(hass, webhook_mock):
    hass.states.async_set("sensor.temp", "0")
    await setup_entry(hass, forward_entities=["sensor.temp"], min_interval=0, max_per_hour=3)
    for i in range(1, 8):
        hass.states.async_set("sensor.temp", str(i))
        await hass.async_block_till_done()
    assert len(posted(webhook_mock)) == 3
    assert hass.states.get("sensor.grok_bot_sends_last_hour").state == "3"
    assert hass.states.get("sensor.grok_bot_last_status").state == "dropped_budget"


async def test_quiet_hours_drop_automatic_only(hass, webhook_mock):
    hass.states.async_set("sensor.temp", "0")
    await setup_entry(
        hass,
        forward_entities=["sensor.temp"],
        min_interval=0,
        quiet_hours=True,
        quiet_start="00:00:00",
        quiet_end="23:59:59",
    )
    with patch("custom_components.grok_bot.hub.in_quiet_hours", return_value=True):
        hass.states.async_set("sensor.temp", "5")
        await hass.async_block_till_done()
        assert posted(webhook_mock) == []
        resp = await hass.services.async_call(
            "grok_bot", "ask", {"message": "manual"}, blocking=True, return_response=True
        )
        assert resp["status"] == "sent"


def test_quiet_hours_window():
    night = datetime(2026, 11, 13, 23, 30)
    noon = datetime(2026, 11, 13, 12, 0)
    early = datetime(2026, 11, 13, 6, 0)
    assert in_quiet_hours(night, "23:00:00", "07:00:00")
    assert in_quiet_hours(early, "23:00:00", "07:00:00")
    assert not in_quiet_hours(noon, "23:00:00", "07:00:00")
    assert in_quiet_hours(noon, "09:00", "17:00")
    assert not in_quiet_hours(noon, "bad", "17:00")


def test_budget_windows():
    budget = SendBudget()
    for ts in (0, 10, 3700):
        budget.record(ts)
    assert budget.count(3600, now=3700) == 1
    assert budget.count(86400, now=3700) == 3
    assert not budget.allowed(5, 3, now=3700)
    assert budget.allowed(5, 4, now=3700)
    assert budget.count(86400, now=86400 + 20) == 1  # old sends roll off


async def test_unavailable_watcher(hass, webhook_mock, freezer: FrozenDateTimeFactory):
    hass.states.async_set("light.porch", "on")
    await setup_entry(
        hass,
        watch_unavailable=["light.porch"],
        unavailable_minutes=10,
        unavailable_action="diagnose",
    )
    hass.states.async_set("light.porch", "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    hass.states.async_set("light.porch", "on")  # recovered in time
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert posted(webhook_mock) == []
    hass.states.async_set("light.porch", "unavailable")
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    payloads = posted(webhook_mock)
    assert len(payloads) == 1
    assert payloads[0]["type"] == "entity_unavailable"
    assert payloads[0]["action_mode"] == "diagnose"
    assert payloads[0]["data"]["entity_id"] == "light.porch"


async def test_repair_watcher(hass, webhook_mock):
    await setup_entry(hass, watch_repairs=True, repairs_action="fix")
    ir.async_create_issue(
        hass,
        "zha",
        "radio_lost",
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="radio_lost",
    )
    await hass.async_block_till_done()
    payloads = posted(webhook_mock)
    assert payloads[0]["type"] == "repair_issue"
    assert payloads[0]["data"]["issue_id"] == "radio_lost"
    assert payloads[0]["allow_fix"] is True


async def test_log_watcher_dedupe_and_filters(hass, webhook_mock):
    await setup_entry(
        hass,
        watch_logs=True,
        log_level="error",
        log_logger_mode="deny",
        log_loggers=["homeassistant.components.noisy"],
        log_dedupe=3600,
        log_action="diagnose",
    )
    zha = logging.getLogger("homeassistant.components.zha")
    zha.error("Radio %s lost", "ezsp")
    zha.error("Radio %s lost", "ezsp")  # duplicate inside the window
    zha.warning("only a warning")  # below the level
    logging.getLogger("homeassistant.components.noisy.sub").error("denied")
    logging.getLogger("custom_components.grok_bot").error("own logs never loop")
    await hass.async_block_till_done()
    await hass.async_block_till_done()
    payloads = posted(webhook_mock)
    assert len(payloads) == 1
    assert payloads[0]["type"] == "log_error"
    assert "Radio ezsp lost" in payloads[0]["message"]
    assert payloads[0]["data"]["logger"] == "homeassistant.components.zha"
    assert payloads[0]["action_mode"] == "diagnose"


async def test_log_allowlist(hass, webhook_mock):
    await setup_entry(
        hass,
        watch_logs=True,
        log_level="warning",
        log_logger_mode="allow",
        log_loggers=["custom_components.helios_tilt"],
        log_dedupe=0,
    )
    logging.getLogger("custom_components.helios_tilt.cover").warning("stuck")
    logging.getLogger("homeassistant.components.zha").error("not allowed")
    await hass.async_block_till_done()
    await hass.async_block_till_done()
    assert [p["data"]["logger"] for p in posted(webhook_mock)] == [
        "custom_components.helios_tilt.cover"
    ]


async def test_automation_and_setup_watchers(hass, webhook_mock):
    await setup_entry(hass, watch_automations=True, automations_action="fix", watch_setup=True)
    logging.getLogger("homeassistant.components.automation.morning").error(
        "Error while executing automation"
    )
    logging.getLogger("homeassistant.setup").error("Setup failed for foo")
    logging.getLogger("homeassistant.components.zha").error("ignored, logs off")
    await hass.async_block_till_done()
    await hass.async_block_till_done()
    kinds = [(p["type"], p["allow_fix"]) for p in posted(webhook_mock)]
    assert kinds == [("automation_error", True), ("setup_error", False)]


async def test_setup_failure_watcher(hass, webhook_mock):
    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    await setup_entry(hass, watch_setup=True, setup_action="diagnose")
    other = MockConfigEntry(domain="demo_broken", title="Broken")
    other.add_to_hass(hass)
    other.mock_state(hass, ConfigEntryState.SETUP_ERROR, "Cannot connect")
    await hass.async_block_till_done()
    payloads = posted(webhook_mock)
    assert payloads[0]["type"] == "setup_failed"
    assert payloads[0]["data"]["domain"] == "demo_broken"
    assert payloads[0]["data"]["reason"] == "Cannot connect"
