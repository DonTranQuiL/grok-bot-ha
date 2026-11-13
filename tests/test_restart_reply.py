"""0.1.4: a safe_restart never swallows the reply of the conversation that asked for it."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.grok_bot.const import (
    DOMAIN,
    RESTART_AFTER_REPLY,
    RESTART_REPLY_GRACE,
)

from .conftest import setup_entry
from .test_trusted import TRUSTED, _on, _svc

PENDING = "sensor.grok_bot_awaiting_reply"
STATUS = "sensor.grok_bot_last_status"


@pytest.fixture
def restart():
    mock = AsyncMock()
    with (
        patch("custom_components.grok_bot.trusted.async_check_config", AsyncMock(return_value=[])),
        patch("custom_components.grok_bot.trusted.async_restart", mock),
    ):
        yield mock


async def _ask(hass, hub) -> str:
    await hass.services.async_call(
        DOMAIN, "ask", {"message": "fix it", "action_mode": "fix"}, blocking=True
    )
    return next(reversed(hub.pending))


async def _later(hass, seconds: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def _reply(hass, cid: str, message: str = "Fixed, restarting") -> None:
    await hass.services.async_call(
        DOMAIN, "reply", {"message": message, "conversation_id": cid}, blocking=True
    )
    await hass.async_block_till_done()


async def test_restart_waits_for_the_reply(hass, webhook_mock, restart):
    entry = await setup_entry(hass, **TRUSTED)
    hub = entry.runtime_data.hub
    await _on(hass)
    cid = await _ask(hass, hub)

    res = await _svc(hass, "safe_restart", {"conversation_id": cid})
    assert res["restarting"] is True and res["waiting_for_reply"] == [cid]
    assert res["delay"] == RESTART_REPLY_GRACE
    restart.assert_not_called()
    assert hub.last_status == "restarting"
    await hass.async_block_till_done()
    assert hass.states.get(PENDING).attributes["restart_scheduled"] is True
    assert hass.states.get(STATUS).state == "restarting"

    await _reply(hass, cid)
    restart.assert_not_called()  # short pause so the reply is saved first
    await _later(hass, RESTART_AFTER_REPLY + 1)
    restart.assert_awaited_once()
    assert hub.history[-1]["message"] == "Fixed, restarting"
    assert hub.pending == {}


async def test_restart_goes_ahead_without_a_reply(hass, webhook_mock, restart):
    entry = await setup_entry(hass, **TRUSTED)
    hub = entry.runtime_data.hub
    await _on(hass)
    cid = await _ask(hass, hub)
    await _svc(hass, "safe_restart")  # no conversation_id: waits for any awaiting reply
    await _later(hass, RESTART_REPLY_GRACE - 5)
    restart.assert_not_called()
    await _later(hass, RESTART_REPLY_GRACE + 1)
    restart.assert_awaited_once()
    assert hub.pending[cid]["restarting"] is True
    assert hub.restart_marker["conversations"] == [cid]


async def test_restart_immediately_when_nothing_awaits(hass, webhook_mock, restart):
    await setup_entry(hass, **TRUSTED)
    await _on(hass)
    res = await _svc(hass, "safe_restart", {"conversation_id": "answered-already"})
    assert res == {"valid": True, "restarting": True, "errors": [], "delay": 0}
    restart.assert_awaited_once()


async def test_other_reply_does_not_trigger_restart(hass, webhook_mock, restart):
    entry = await setup_entry(hass, **TRUSTED)
    hub = entry.runtime_data.hub
    await _on(hass)
    first = await _ask(hass, hub)
    second = await _ask(hass, hub)
    await _svc(hass, "safe_restart", {"conversation_id": second})
    await _reply(hass, first, "other answer")
    await _later(hass, RESTART_AFTER_REPLY + 1)
    restart.assert_not_called()
    await _reply(hass, second)
    await _later(hass, RESTART_AFTER_REPLY + 1)
    restart.assert_awaited_once()


async def test_awaiting_reply_survives_the_restart(hass, webhook_mock, restart, hass_storage):
    assert await async_setup_component(hass, "persistent_notification", {})
    entry = await setup_entry(hass, **TRUSTED, reply_timeout=10)
    hub = entry.runtime_data.hub
    await _on(hass)
    await hass.services.async_call(
        DOMAIN,
        "ask",
        {"message": "fix it", "action_mode": "fix", "reply_to": "persistent_notification.create"},
        blocking=True,
    )
    cid = next(iter(hub.pending))
    await _svc(hass, "safe_restart", {"conversation_id": cid})
    await _later(hass, RESTART_REPLY_GRACE + 1)  # the reply did not make it in time
    restart.assert_awaited_once()
    stored = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]
    assert cid in stored["pending"] and stored["restart"]["conversation_id"] == cid

    # "Restart": unload and set the entry up again from the Store.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    hub = entry.runtime_data.hub
    assert hub.pending[cid]["restarted"] is True
    assert hub.pending[cid]["reply_to"] == "persistent_notification.create"
    assert hub.restart_marker is None
    assert hub.history[-1]["type"] == "system"
    assert hub.history[-1]["message"] == "Restart done, Home Assistant is back."
    assert hass.states.get(STATUS).state == "restarted_waiting"
    assert hass.states.get(PENDING).attributes["restarted_waiting"] is True
    assert hub.access.audit[-1]["type"] == "trusted_restart_done"

    await _reply(hass, cid, "Duplicate http: removed, all good")
    assert hub.pending == {}
    assert hub.last_reply["conversation_id"] == cid
    assert hub.history[-1]["message"] == "Duplicate http: removed, all good"
    assert hass.states.get(STATUS).state == "idle"
    assert hass.states.get(PENDING).attributes["restarted_waiting"] is False
    restart.assert_awaited_once()  # a late reply never restarts again

    # A second reload does not write another "Restart done" entry.
    entries = len(hub.history)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(entry.runtime_data.hub.history) == entries


async def test_reload_before_the_restart_cancels_it(hass, webhook_mock, restart):
    entry = await setup_entry(hass, **TRUSTED)
    hub = entry.runtime_data.hub
    await _on(hass)
    cid = await _ask(hass, hub)
    await _svc(hass, "safe_restart", {"conversation_id": cid})
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await _later(hass, RESTART_REPLY_GRACE + 1)
    restart.assert_not_called()
    hub = entry.runtime_data.hub
    assert hub.restart_marker is None
    assert not any(e["type"] == "system" for e in hub.history)
    assert cid in hub.pending and "restarting" not in hub.pending[cid]


async def test_prompt_tells_to_pass_conversation_id(hass, webhook_mock):
    entry = await setup_entry(hass)
    prompt = entry.runtime_data.hub.setup_prompt()
    assert "conversation_id to grok_bot.safe_restart" in prompt
