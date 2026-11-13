"""Trusted access: opt-in YAML edits and restarts with backups and a check_config gate."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

from homeassistant.components import persistent_notification
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError, Unauthorized
import pytest

from custom_components.grok_bot.const import DOMAIN

from .conftest import posted, setup_entry

TRUSTED = {
    "mode": "advanced",
    "trusted": True,
    "trusted_confirm": True,
    "allow_yaml_edit": True,
    "allow_restart": True,
    "trusted_window": True,
    "trusted_window_minutes": 30,
}
SWITCH = "switch.grok_bot_trusted_access"


def _notes(hass) -> dict:
    return persistent_notification._async_get_or_create_notifications(hass)


async def _on(hass):
    await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    await hass.async_block_till_done()


async def _svc(hass, name, data=None):
    return await hass.services.async_call(
        DOMAIN, name, data or {}, blocking=True, return_response=True
    )


@pytest.fixture
def config_dir(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "configuration.yaml").write_text("homeassistant:\n  name: Test\n")
    (tmp_path / "secrets.yaml").write_text("x: y\n")
    (tmp_path / "packages").mkdir()
    (tmp_path / "packages" / "heat.yaml").write_text("input_boolean: {}\n")
    (tmp_path / "packages" / "notes.txt").write_text("no")
    (tmp_path / ".storage").mkdir()
    (tmp_path / ".storage" / "core.config").write_text("{}")
    (tmp_path / "custom_components").mkdir()
    (tmp_path / "custom_components" / "a.yaml").write_text("a: 1\n")
    return tmp_path


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


async def test_trusted_off_by_default(hass, webhook_mock, config_dir):
    entry = await setup_entry(hass)
    hub = entry.runtime_data.hub
    assert hub.trusted.enabled is False
    with pytest.raises(ServiceValidationError):
        hub.trusted.turn_on()
    with pytest.raises(ServiceValidationError):
        await _svc(hass, "prepare_change", {"path": "configuration.yaml"})
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
    assert access["allow_yaml_edit"] is True
    assert access["allow_restart"] is False
    assert access["backup_service"] == "grok_bot.prepare_change"
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
    entry = await setup_entry(hass, **{**TRUSTED, "trusted_window": False})
    hub = entry.runtime_data.hub
    await _on(hass)
    assert hub.trusted.until == "forever"
    assert hub.trusted.to_store()["trusted_until"] == "forever"
    await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    assert hub.trusted.active is False


# ------------------------------------------------------------ backups
@pytest.mark.parametrize(
    "path",
    [
        "secrets.yaml",
        ".storage/core.config",
        "custom_components/a.yaml",
        "../outside.yaml",
        "/etc/passwd",
        "packages/notes.txt",
        "ui-lovelace.yaml",
        ".grok_bot_backups/x.bak",
    ],
)
async def test_prepare_change_denies(hass, webhook_mock, config_dir, path):
    await setup_entry(hass, **TRUSTED)
    await _on(hass)
    with pytest.raises(ServiceValidationError):
        await _svc(hass, "prepare_change", {"path": path})


async def test_backup_and_restore(hass, webhook_mock, config_dir):
    entry = await setup_entry(hass, **TRUSTED)
    await _on(hass)
    before = len(_notes(hass))
    res = await _svc(hass, "prepare_change", {"path": "configuration.yaml"})
    backup = res["backup_path"]
    assert "/.grok_bot_backups/configuration.yaml." in backup
    assert (config_dir / ".grok_bot_backups").is_dir()
    res2 = await _svc(hass, "prepare_change", {"path": str(config_dir / "packages" / "heat.yaml")})
    assert res2["path"] == "packages/heat.yaml"
    assert "packages__heat.yaml." in res2["backup_path"]

    (config_dir / "configuration.yaml").write_text("broken: [\n")
    res = await _svc(hass, "restore_backup", {"backup_path": backup})
    assert res["path"] == "configuration.yaml"
    assert (config_dir / "configuration.yaml").read_text().startswith("homeassistant:")
    with pytest.raises(ServiceValidationError):
        await _svc(hass, "restore_backup", {"backup_path": str(config_dir / "secrets.yaml")})

    assert len(_notes(hass)) >= before + 3  # one notification per trusted action
    kinds = [a["type"] for a in entry.runtime_data.hub.access.audit]
    assert "trusted_prepare_change" in kinds and "trusted_restore_backup" in kinds
    assert hass.states.get("sensor.grok_bot_last_grok_bot_action").state


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
    assert "grok_bot.prepare_change" in prompt and "grok_bot.safe_restart" in prompt
    assert "sign-in" in prompt and "password never reaches you" in prompt
    assert "Profile > Security" in prompt
