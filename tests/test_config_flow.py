"""Config, reauth, reconfigure and options flow tests."""

from __future__ import annotations

import aiohttp
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.grok_bot.const import (
    CONF_AUTH_HEADER,
    CONF_FILTERS,
    CONF_FORWARD_ENTITIES,
    CONF_FORWARD_EVENTS,
    CONF_MAX_PER_DAY,
    CONF_MAX_PER_HOUR,
    CONF_MODE,
    CONF_PRESET,
    CONF_TEMPLATE_STATE,
    CONF_WATCH_LOGS,
    CONF_WATCH_REPAIRS,
    CONF_WEBHOOK_URL,
    DOMAIN,
)

from .conftest import AUTH, URL, make_entry, posted, setup_entry

USER_INPUT = {
    "name": "Grok Bot",
    CONF_WEBHOOK_URL: URL,
    CONF_AUTH_HEADER: "Authorization: Bearer super-secret-token",
    "send_test": True,
}


async def _start(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_user_flow_creates_entry_with_preset(hass, webhook_mock):
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["step_id"] == "preset"
    pings = posted(webhook_mock)
    assert pings[0]["type"] == "ping"
    # the pasted "Authorization:" prefix is stripped before sending
    assert webhook_mock.mock_calls[0][3]["Authorization"] == AUTH
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PRESET: "errors_repairs_diagnose"}
    )
    # no MCP server installed: "Install HA-MCP first", continue reply-only
    assert result["step_id"] == "install_mcp"
    assert "ha_mcp_install_url" in result["description_placeholders"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"access_method": "mcp"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["access_level"] == "reply"
    assert result["data"][CONF_AUTH_HEADER] == AUTH
    assert result["data"]["inbound_webhook_id"]
    opts = result["options"]
    assert opts[CONF_WATCH_LOGS] is True
    assert opts[CONF_WATCH_REPAIRS] is True
    assert opts["log_action"] == "diagnose"
    assert opts[CONF_FORWARD_ENTITIES] == []
    assert opts["enable_notify"] is False
    assert opts["enable_conversation"] is False


async def test_ask_only_preset_is_quiet(hass, webhook_mock):
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, "send_test": False}
    )
    assert posted(webhook_mock) == []  # no ping when the test is skipped
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PRESET: "ask_only"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"access_method": "mcp"}
    )
    opts = result["options"]
    assert not any(
        opts[k] for k in ("watch_logs", "watch_repairs", "watch_setup", "watch_automations")
    )


@pytest.mark.parametrize(
    ("mock_kwargs", "user_input", "error"),
    [
        ({"status": 200}, {CONF_WEBHOOK_URL: "http://insecure.example/x"}, "invalid_url"),
        ({"status": 401}, {}, "invalid_auth"),
        ({"status": 500}, {}, "cannot_connect"),
        ({"exc": aiohttp.ClientConnectionError()}, {}, "cannot_connect"),
        ({"status": 200}, {CONF_AUTH_HEADER: "  "}, "invalid_auth"),
    ],
)
async def test_user_flow_errors(hass, aioclient_mock, mock_kwargs, user_input, error):
    aioclient_mock.post(URL, **mock_kwargs)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, **user_input}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


async def test_duplicate_aborts(hass, webhook_mock):
    from custom_components.grok_bot.config_flow import unique_id_for

    entry = make_entry(unique_id=unique_id_for(URL))
    entry.add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass, webhook_mock):
    entry = await setup_entry(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_AUTH_HEADER: "Bearer new", "send_test": False}
    )
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_AUTH_HEADER] == "Bearer new"


async def test_reconfigure(hass, aioclient_mock):
    new_url = "https://hooks.example.test/routine/new"
    aioclient_mock.post(URL, status=200)
    aioclient_mock.post(new_url, status=200)
    entry = await setup_entry(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_WEBHOOK_URL: new_url, CONF_AUTH_HEADER: "Bearer x", "send_test": True},
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_WEBHOOK_URL] == new_url


async def _options(hass, entry):
    return await hass.config_entries.options.async_init(entry.entry_id)


async def _menu(hass, flow, step):
    return await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": step}
    )


async def test_options_simple_menu_and_preset(hass, webhook_mock):
    entry = await setup_entry(hass)
    flow = await _options(hass, entry)
    assert flow["type"] is FlowResultType.MENU
    assert "watchers" not in flow["menu_options"]
    flow = await _menu(hass, flow, "preset")
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {CONF_PRESET: "errors_only"}
    )
    assert flow["type"] is FlowResultType.MENU
    flow = await _menu(hass, flow, "budget")
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {CONF_MAX_PER_HOUR: 50, CONF_MAX_PER_DAY: 10}
    )
    assert flow["errors"] == {"base": "hour_over_day"}
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {CONF_MAX_PER_HOUR: 5, CONF_MAX_PER_DAY: 40}
    )
    flow = await _menu(hass, flow, "finish")
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_WATCH_LOGS] is True
    assert entry.options[CONF_MAX_PER_HOUR] == 5


async def test_options_advanced(hass, webhook_mock):
    hass.states.async_set("sensor.temp", "20")
    entry = await setup_entry(hass)
    flow = await _options(hass, entry)
    flow = await _menu(hass, flow, "advanced_mode")
    assert "watchers" in flow["menu_options"]

    # filters need forwarded entities first
    aborted = await _menu(hass, flow, "entity_filter")
    assert aborted["reason"] == "no_forward_entities"

    flow = await _options(hass, entry)
    flow = await _menu(hass, flow, "advanced_mode")
    flow = await _menu(hass, flow, "forwarding")
    bad = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            CONF_FORWARD_ENTITIES: ["sensor.temp"],
            "state_action": "diagnose",
            "ignore_unavailable": True,
            CONF_FORWARD_EVENTS: ["state_changed"],
            "event_action": "report",
        },
    )
    assert bad["errors"] == {CONF_FORWARD_EVENTS: "event_blocked"}
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            CONF_FORWARD_ENTITIES: ["sensor.temp"],
            "state_action": "diagnose",
            "ignore_unavailable": True,
            CONF_FORWARD_EVENTS: ["zha_event"],
            "event_action": "report",
        },
    )
    flow = await _menu(hass, flow, "entity_filter")
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"filter_entity": "sensor.temp"}
    )
    assert flow["step_id"] == "filter_details"
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"above": 30, "min_interval": 60}
    )
    flow = await _menu(hass, flow, "watchers")
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            "logs": {
                "watch_logs": True,
                "log_level": "warning",
                "log_logger_mode": "allow",
                "log_loggers": ["custom_components.helios_tilt"],
                "log_dedupe": 600,
                "log_action": "fix",
            },
            "repairs": {"watch_repairs": True, "repairs_action": "diagnose"},
            "unavailable": {
                "watch_unavailable": ["sensor.temp"],
                "unavailable_minutes": 10,
                "unavailable_action": "report",
            },
            "automations": {"watch_automations": False, "automations_action": "report"},
            "setup": {"watch_setup": True, "setup_action": "fix"},
        },
    )
    flow = await _menu(hass, flow, "templates")
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {CONF_TEMPLATE_STATE: "{{ to_state.state }} now"}
    )
    flow = await _menu(hass, flow, "finish")
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    o = entry.options
    assert o[CONF_MODE] == "advanced"
    assert o[CONF_PRESET] == "custom"
    assert o[CONF_FILTERS] == {"sensor.temp": {"above": 30.0, "min_interval": 60}}
    assert o["log_action"] == "fix"
    assert o["log_dedupe"] == 600
    assert o[CONF_FORWARD_EVENTS] == ["zha_event"]
    assert o[CONF_TEMPLATE_STATE] == "{{ to_state.state }} now"
    await hass.async_block_till_done()
    assert entry.state.value == "loaded"  # reloaded with the new options
