"""Trusted access: opt-in restarts with a check_config gate."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, PropertyMock, patch

from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError, Unauthorized
import pytest

from custom_components.grok_bot.const import DOMAIN

from .conftest import posted, setup_entry

TRUSTED = {
    "mode": "advanced",
    "trusted": True,
    "trusted_confirm": True,
    "allow_restart": True,
    "trusted_duration": "30m",
}
SWITCH = "switch.grok_bot_trusted_access"


async def _on(hass):
    await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    await hass.async_block_till_done()


async def _svc(hass, name, data=None):
    return await hass.services.async_call(
        DOMAIN, name, data or {}, blocking=True, return_response=True
    )


# ------------------------------------------------------------------ options
async def test_options_require_confirmation(hass, webhook_mock):
    entry = await setup_entry(hass, mode="advanced")
    assert hass.states.get(SWITCH) is None  # no switch unless enabled
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "access"}
    )
    base = {"access_method": "mcp", "access_level": "reply", "reply_timeout": 10}
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {**base, "trusted": True, "trusted_confirm": False}
    )
    assert flow["errors"] == {"trusted_confirm": "trusted_confirm_required"}
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {**base, "trusted": True, "trusted_confirm": True}
    )
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "finish"}
    )
    await hass.async_block_till_done()
    assert entry.options["trusted"] is True
    assert hass.states.get(SWITCH).state == "off"  # enabled, but the window is closed


async def test_trusted_off_by_default(hass, webhook_mock):
    entry = await setup_entry(hass)
    hub = entry.runtime_data.hub
    assert hub.trusted.enabled is False
    with pytest.raises(ServiceValidationError):
        hub.trusted.turn_on()
    with pytest.raises(ServiceValidationError):
        await _svc(hass, "safe_restart")
    await hass.services.async_call(
        DOMAIN, "ask", {"message": "fix", "action_mode": "fix"}, blocking=True
    )
    assert "trusted" not in posted(webhook_mock)[-1]["access"]


# ------------------------------------------------------------ payload flags
async def test_payload_flags_only_for_fix(hass, webhook_mock):
    entry = await setup_entry(hass, **{**TRUSTED, "allow_restart": False})
    await _on(hass)
    state = hass.states.get(SWITCH)
    assert state.state == "on" and state.attributes["until"]
    await hass.services.async_call(
        DOMAIN, "ask", {"message": "report", "action_mode": "report"}, blocking=True
    )
    assert "trusted" not in posted(webhook_mock)[-1]["access"]
    await hass.services.async_call(
        DOMAIN, "ask", {"message": "fix it", "action_mode": "fix"}, blocking=True
    )
    access = posted(webhook_mock)[-1]["access"]
    assert access["trusted"] is True
    assert access["allow_restart"] is False
    assert access["restart_service"] == "grok_bot.safe_restart"
    assert "edit_service" not in access
    with pytest.raises(ServiceValidationError):
        await _svc(hass, "safe_restart")
    audit = entry.runtime_data.hub.access.audit
    assert any(a["type"] == "trusted_on" for a in audit)


async def test_window_auto_reverts(hass, webhook_mock):
    entry = await setup_entry(hass, **TRUSTED)
    hub = entry.runtime_data.hub
    await _on(hass)
    assert hub.trusted.active
    hub.trusted.until = time.time() - 1
    hub.trusted.async_tick()
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).state == "off"
    assert hub.trusted.until is None
    assert any("window expired" in a["summary"] for a in hub.access.audit)
    # a timed window never survives a restart
    hub.trusted.until = time.time() + 999
    assert hub.trusted.to_store()["trusted_until"] is None


async def test_no_window_stays_on_and_persists(hass, webhook_mock):
    entry = await setup_entry(hass, **{**TRUSTED, "trusted_duration": "always"})
    hub = entry.runtime_data.hub
    await _on(hass)
    assert hub.trusted.until == "forever"
    assert hub.trusted.to_store()["trusted_until"] == "forever"
    await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    assert hub.trusted.active is False


# ------------------------------------------------------------ restart
async def test_safe_restart_checks_config_first(hass, webhook_mock):
    await setup_entry(hass, **TRUSTED)
    await _on(hass)
    restart = AsyncMock()
    with (
        patch(
            "custom_components.grok_bot.trusted.async_check_config",
            AsyncMock(return_value=["Invalid config for 'light'"]),
        ),
        patch("custom_components.grok_bot.trusted.async_restart", restart),
    ):
        res = await _svc(hass, "safe_restart")
    assert res == {"valid": False, "restarting": False, "errors": ["Invalid config for 'light'"]}
    restart.assert_not_called()
    with (
        patch("custom_components.grok_bot.trusted.async_check_config", AsyncMock(return_value=[])),
        patch("custom_components.grok_bot.trusted.async_restart", restart),
    ):
        res = await _svc(hass, "safe_restart")
    assert res["restarting"] is True
    restart.assert_awaited_once()


async def test_trusted_services_are_admin_only(hass, webhook_mock, hass_read_only_user):
    await setup_entry(hass, **TRUSTED)
    await _on(hass)
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            "safe_restart",
            {},
            blocking=True,
            return_response=True,
            context=Context(user_id=hass_read_only_user.id),
        )


async def test_setup_prompt_mentions_trusted_and_sign_in(hass, webhook_mock):
    entry = await setup_entry(hass)
    prompt = entry.runtime_data.hub.setup_prompt()
    assert "grok_bot.safe_restart" in prompt
    assert "prepare_change" not in prompt and "edit_yaml" not in prompt
    assert "sign-in" in prompt and "password never reaches you" in prompt
    assert "Profile > Security" in prompt


# ------------------------------------------------------------ durations
@pytest.mark.parametrize(("duration", "minutes"), [("30m", 30), ("2h", 120), ("24h", 1440)])
async def test_duration_choices(hass, webhook_mock, duration, minutes):
    entry = await setup_entry(hass, **{**TRUSTED, "trusted_duration": duration})
    hub = entry.runtime_data.hub
    await _on(hass)
    assert abs(float(hub.trusted.until) - (time.time() + minutes * 60)) < 5


async def test_always_on_raises_repair_issue(hass, webhook_mock):
    from homeassistant.helpers import issue_registry as ir

    entry = await setup_entry(hass, **{**TRUSTED, "trusted_duration": "always"})
    hub = entry.runtime_data.hub
    issue_id = f"trusted_always_on_{entry.entry_id}"
    reg = ir.async_get(hass)
    assert reg.async_get_issue(DOMAIN, issue_id) is None
    await _on(hass)
    assert reg.async_get_issue(DOMAIN, issue_id) is not None
    # switching the duration away from "always" closes the open-ended window
    with patch.object(
        type(hub),
        "options",
        new_callable=PropertyMock,
        return_value={**hub.options, "trusted_duration": "30m"},
    ):
        assert not hub.trusted.active
        hub.trusted.async_tick()
        await hass.async_block_till_done()
    assert hub.trusted.until is None
    assert reg.async_get_issue(DOMAIN, issue_id) is None
