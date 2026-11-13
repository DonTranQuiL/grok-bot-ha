"""MCP detection (HA-MCP preferred), connect prompt, reply timeout and access webhook."""

from __future__ import annotations

import time

from homeassistant import config_entries
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.grok_bot.const import DOMAIN
from custom_components.grok_bot.hub import options_of

from .conftest import AUTH, URL, make_entry, posted, setup_entry

USER_INPUT = {
    "name": "Grok Bot",
    "webhook_url": URL,
    "auth_header": AUTH,
    "send_test": False,
}


_MOCKED: list[MockConfigEntry] = []


@pytest.fixture(autouse=True)
def _reset_mock_mcp_entries(hass):
    """Mark mocked MCP entries not loaded so teardown doesn't import the real ones."""
    yield
    while _MOCKED:
        _MOCKED.pop().mock_state(hass, ConfigEntryState.NOT_LOADED)


def add_ha_mcp(hass, loaded: bool = True) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain="ha_mcp_tools",
        title="HA-MCP Server",
        data={"entry_type": "server", "webhook_id": "mcp_secret_id"},
        state=ConfigEntryState.LOADED if loaded else ConfigEntryState.NOT_LOADED,
    )
    entry.add_to_hass(hass)
    _MOCKED.append(entry)
    return entry


def add_core_mcp(hass) -> MockConfigEntry:
    entry = MockConfigEntry(domain="mcp_server", state=ConfigEntryState.LOADED)
    entry.add_to_hass(hass)
    _MOCKED.append(entry)
    return entry


async def _flow_to_access(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"preset": "ask_only"})


def _issue(hass, key, entry):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{key}_{entry.entry_id}")


# ----------------------------------------------------------------- onboarding
async def test_flow_with_ha_mcp_shows_connect_prompt(hass, webhook_mock):
    await hass.config.async_update(external_url="https://ha.example.test", location_name="Lab")
    add_ha_mcp(hass)
    add_core_mcp(hass)  # HA-MCP wins when both exist
    result = await _flow_to_access(hass)
    assert result["step_id"] == "access"
    assert result["description_placeholders"]["mcp_status"] == "ha_mcp (ready)"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"access_method": "mcp", "access_level": "reply"}
    )
    assert result["step_id"] == "connect"
    prompt = result["description_placeholders"]["prompt"]
    assert '"Lab"' in prompt
    assert URL in prompt
    assert "https://ha.example.test/api/webhook/" in prompt
    assert "grok_bot.reply" in prompt and "Connected" in prompt
    assert "allow_fix" in prompt and "Never restart" in prompt
    assert "super-secret-token" not in prompt and "mcp_secret_id" not in prompt
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_flow_with_core_mcp_only_has_no_connect_step(hass, webhook_mock):
    add_core_mcp(hass)
    result = await _flow_to_access(hass)
    assert result["step_id"] == "access"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"access_method": "mcp", "access_level": "reply"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_options_redetect_after_installing_ha_mcp(hass, webhook_mock):
    entry = await setup_entry(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert "connect" not in flow["menu_options"]
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "access"}
    )
    assert flow["step_id"] == "install_mcp"
    await hass.config_entries.options.async_configure(
        flow["flow_id"], {"access_method": "mcp", "reply_timeout": 10}
    )

    add_ha_mcp(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert "connect" in flow["menu_options"]
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "access"}
    )
    assert flow["step_id"] == "access"
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"access_method": "mcp", "access_level": "reply", "reply_timeout": 5}
    )
    assert flow["step_id"] == "connect"
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    assert flow["type"] is FlowResultType.MENU
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "finish"}
    )
    assert entry.options["reply_timeout"] == 5


async def test_reconfigure_shows_connect_with_ha_mcp(hass, webhook_mock):
    entry = await setup_entry(hass)
    add_ha_mcp(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"webhook_url": URL, "auth_header": AUTH, "send_test": False}
    )
    assert result["step_id"] == "reconfigure_connect"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["reason"] == "reconfigure_successful"


# ------------------------------------------------------------ payload + issues
async def test_access_block_and_issues(hass, webhook_mock):
    entry = await setup_entry(hass)
    hub = entry.runtime_data.hub
    await hass.services.async_call(DOMAIN, "ask", {"message": "hi"}, blocking=True)
    access = posted(webhook_mock)[-1]["access"]
    assert access["method"] == "none"
    assert access["configured_method"] == "mcp"
    assert access["mcp_ready"] is False
    assert access["ha_instance"]["config_entry_id"] == entry.entry_id
    assert _issue(hass, "mcp_server_missing", entry) is not None
    assert _issue(hass, "not_connected", entry) is None  # only with HA-MCP
    assert hass.states.get("sensor.grok_bot_access_method").state == "none"

    mcp = add_ha_mcp(hass, loaded=False)
    mcp.mock_state(hass, ConfigEntryState.LOADED)  # fires the config entry signal
    await hass.async_block_till_done()
    assert _issue(hass, "mcp_server_missing", entry) is None
    assert _issue(hass, "not_connected", entry) is not None
    await hass.services.async_call(DOMAIN, "ask", {"message": "again"}, blocking=True)
    access = posted(webhook_mock)[-1]["access"]
    assert access["method"] == "mcp"
    assert access["mcp_provider"] == "ha_mcp"
    assert "/api/webhook/" in access["connector_url_hint"]
    assert "mcp_secret_id" not in str(access)
    hub.notify()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.grok_bot_access_method").state == "ha_mcp"

    await hass.services.async_call(DOMAIN, "reply", {"message": "Connected"}, blocking=True)
    await hass.async_block_till_done()
    assert hub.connected is True
    assert _issue(hass, "not_connected", entry) is None
    assert hub._data_to_save()["connected"] is True


async def test_core_mcp_access_block(hass, webhook_mock):
    await hass.config.async_update(external_url="https://ha.example.test")
    add_core_mcp(hass)
    await setup_entry(hass)
    await hass.services.async_call(DOMAIN, "ask", {"message": "hi"}, blocking=True)
    access = posted(webhook_mock)[-1]["access"]
    assert access["mcp_provider"] == "mcp_server"
    assert access["connector_url_hint"] == "https://ha.example.test/api/mcp"


# -------------------------------------------------------------- awaiting reply
async def test_reply_timeout_marks_answered_elsewhere(hass, webhook_mock):
    entry = await setup_entry(hass)
    hub = entry.runtime_data.hub
    await hass.services.async_call(DOMAIN, "ask", {"message": "q"}, blocking=True)
    assert len(hub.pending) == 1
    assert hub.async_expire_pending(now=time.time() + 60) == 0
    assert hub.async_expire_pending(now=time.time() + 601) == 1
    await hass.async_block_till_done()
    assert hub.pending == {}
    assert hass.states.get("sensor.grok_bot_awaiting_reply").state == "0"
    assert hass.states.get("sensor.grok_bot_last_status").state == "answered_elsewhere"


async def test_reply_timeout_zero_never_expires(hass, webhook_mock):
    entry = await setup_entry(hass, reply_timeout=0)
    hub = entry.runtime_data.hub
    await hass.services.async_call(DOMAIN, "ask", {"message": "q"}, blocking=True)
    assert hub.async_expire_pending(now=time.time() + 10**6) == 0
    assert len(hub.pending) == 1


async def test_reply_clears_pending_immediately(hass, webhook_mock):
    entry = await setup_entry(hass)
    hub = entry.runtime_data.hub
    await hass.services.async_call(DOMAIN, "ask", {"message": "q"}, blocking=True)
    cid = next(iter(hub.pending))
    await hass.services.async_call(
        DOMAIN, "reply", {"message": "done", "conversation_id": cid}, blocking=True
    )
    assert hub.pending == {}


async def test_mark_handled_and_setup_prompt_buttons(hass, webhook_mock):
    entry = await setup_entry(hass)
    hub = entry.runtime_data.hub
    await hass.services.async_call(DOMAIN, "ask", {"message": "q"}, blocking=True)
    await hass.services.async_call(DOMAIN, "ask", {"message": "q2"}, blocking=True)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.grok_bot_mark_replies_handled"}, blocking=True
    )
    assert hub.pending == {}
    assert hub.last_status == "answered_elsewhere"

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.grok_bot_show_grok_bot_setup_prompt"},
        blocking=True,
    )
    await hass.async_block_till_done()
    notes = persistent_notification._async_get_or_create_notifications(hass)
    note = notes.get(f"grok_bot_setup_prompt_{entry.entry_id}")
    assert note is not None
    assert "grok_bot.reply" in note["message"]


async def test_prompt_dutch(hass, webhook_mock):
    await hass.config.async_update(language="nl")
    entry = await setup_entry(hass)
    prompt = entry.runtime_data.hub.setup_prompt()
    assert prompt.startswith("Hoi Grok Bot")
    assert "Herstart nooit Home Assistant Core" in prompt


# -------------------------------------------------------------- access webhook
def test_legacy_inbound_option_migrates_to_webhook():
    entry = make_entry()
    entry = MockConfigEntry(
        domain=DOMAIN, data=entry.data, options={"enable_inbound_webhook": True}
    )
    assert options_of(entry)["access_method"] == "webhook"
    entry2 = MockConfigEntry(
        domain=DOMAIN,
        data=entry.data,
        options={"enable_inbound_webhook": True, "access_method": "mcp"},
    )
    assert options_of(entry2)["access_method"] == "mcp"


async def _post(client, token, body):
    return await client.post(
        "/api/webhook/inbound-test-id", json=body, headers={"X-Grok-Bot-Token": token}
    )


async def test_access_webhook_levels(hass, webhook_mock, hass_client_no_auth):
    await hass.config.async_update(external_url="https://ha.example.test")
    hass.states.async_set("light.desk", "off")
    entry = await setup_entry(hass, access_method="webhook", access_level="read")
    hub = entry.runtime_data.hub
    token = hub.access.token
    await hass.services.async_call(DOMAIN, "ask", {"message": "q"}, blocking=True)
    payload = posted(webhook_mock)[-1]
    assert payload["access"]["method"] == "webhook"
    cb = payload["callback"]
    assert cb["url"].startswith("https://ha.example.test/api/webhook/")
    cid = cb["conversation_id"]
    client = await hass_client_no_auth()

    resp = await _post(client, token, {"conversation_id": cid, "actions": [{"type": "get_states"}]})
    data = await resp.json()
    assert data["results"][0]["ok"] is True
    assert any(s["entity_id"] == "light.desk" for s in data["results"][0]["result"])

    resp = await _post(
        client,
        token,
        {
            "conversation_id": cid,
            "actions": [
                {
                    "type": "call_service",
                    "domain": "light",
                    "service": "turn_on",
                    "target": {"entity_id": "light.desk"},
                }
            ],
        },
    )
    data = await resp.json()
    assert data["results"][0]["error"] == "denied"  # read level can't control

    resp = await _post(
        client, token, {"conversation_id": "unknown", "actions": [{"type": "get_states"}]}
    )
    assert (await resp.json())["results"][0]["error"] == "denied"  # no open session

    hub.access.rotate_token()
    resp = await _post(client, token, {"conversation_id": cid, "actions": [{"type": "get_states"}]})
    assert resp.status == 401
    assert hass.states.get("sensor.grok_bot_last_grok_bot_action").state


async def test_access_webhook_blocks_restart(hass, webhook_mock, hass_client_no_auth):
    await hass.config.async_update(external_url="https://ha.example.test")
    entry = await setup_entry(
        hass, access_method="webhook", access_level="fix", access_require_pending=False
    )
    token = entry.runtime_data.hub.access.token
    client = await hass_client_no_auth()
    resp = await _post(
        client,
        token,
        {"actions": [{"type": "call_service", "domain": "homeassistant", "service": "restart"}]},
    )
    data = await resp.json()
    assert data["results"][0]["ok"] is False


async def test_mcp_method_does_not_register_access_webhook(hass, webhook_mock, hass_client_no_auth):
    entry = await setup_entry(hass)  # default: mcp
    assert entry.runtime_data.hub.access.enabled is False
    client = await hass_client_no_auth()
    await _post(client, "x", {"message": "hi"})
    assert hass.states.get("sensor.grok_bot_last_reply").state == "unknown"
