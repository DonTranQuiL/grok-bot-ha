"""Options flow saving: every sub-page saves on Submit; Trusted access end to end.

Regression for 0.1.2: Access -> Connect it in Grok Bot -> Save and close with
HA-MCP installed must leave `trusted` in entry.options and create the
Trusted access switch after the reload, and closing the dialog at any point
must not lose what was already submitted.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.grok_bot.const import (
    CONF_ALLOW_RESTART,
    CONF_ALLOW_YAML_EDIT,
    CONF_MAX_PER_DAY,
    CONF_MAX_PER_HOUR,
    CONF_MODE,
    CONF_TRUSTED,
    CONF_TRUSTED_CONFIRM,
    CONF_TRUSTED_DURATION,
)

from .conftest import setup_entry

TRUSTED_SWITCH = "switch.grok_bot_trusted_access"
TRUSTED_INPUT = {
    CONF_TRUSTED: True,
    CONF_TRUSTED_CONFIRM: True,
    CONF_ALLOW_YAML_EDIT: True,
    CONF_ALLOW_RESTART: True,
    CONF_TRUSTED_DURATION: "30m",
}
BASE = "/api/config/config_entries/options/flow"


@pytest.fixture
def ha_mcp(hass):
    """A loaded HA-MCP server entry (so the Connect step is shown)."""
    entry = MockConfigEntry(
        domain="ha_mcp_tools",
        title="HA-MCP Server",
        data={"entry_type": "server", "webhook_id": "mcp_secret_id"},
        state=ConfigEntryState.LOADED,
    )
    entry.add_to_hass(hass)
    yield entry
    entry.mock_state(hass, ConfigEntryState.NOT_LOADED)


def _switches(hass, entry) -> list[str]:
    reg = er.async_get(hass)
    return [
        e.entity_id
        for e in er.async_entries_for_config_entry(reg, entry.entry_id)
        if e.domain == "switch"
    ]


def _defaults(form: dict) -> dict:
    """What the frontend submits: every serialized default, like ha-form does."""
    return {f["name"]: f["default"] for f in form["data_schema"] if "default" in f}


async def test_trusted_access_connect_finish_over_http(hass, webhook_mock, hass_client, ha_mcp):
    """The exact UI path, through the REST API the frontend uses."""
    assert await async_setup_component(hass, "config", {})
    entry = await setup_entry(hass, mode="advanced")
    created = entry.modified_at
    assert TRUSTED_SWITCH not in _switches(hass, entry)
    client = await hass_client()

    resp = await client.post(BASE, json={"handler": entry.entry_id})
    menu = await resp.json()
    assert menu["type"] == "menu"
    assert menu["menu_options"].index("connect") == menu["menu_options"].index("access") + 1
    flow_id = menu["flow_id"]

    resp = await client.post(f"{BASE}/{flow_id}", json={"next_step_id": "access"})
    form = await resp.json()
    assert form["step_id"] == "access"
    resp = await client.post(f"{BASE}/{flow_id}", json={**_defaults(form), **TRUSTED_INPUT})
    connect = await resp.json()
    assert resp.status == 200, connect
    assert connect["step_id"] == "connect"
    resp = await client.post(f"{BASE}/{flow_id}", json={})
    assert (await resp.json())["type"] == "menu"
    resp = await client.post(f"{BASE}/{flow_id}", json={"next_step_id": "finish"})
    assert (await resp.json())["type"] == "create_entry"
    await hass.async_block_till_done()

    for key, value in TRUSTED_INPUT.items():
        assert entry.options[key] == value
    assert entry.modified_at > created
    assert entry.state is ConfigEntryState.LOADED
    assert TRUSTED_SWITCH in _switches(hass, entry)
    assert hass.states.get(TRUSTED_SWITCH).state == "off"
    assert entry.runtime_data.hub.trusted.enabled

    # the switch works after the reload
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": TRUSTED_SWITCH}, blocking=True
    )
    assert hass.states.get(TRUSTED_SWITCH).state == "on"


async def test_trusted_access_connect_finish_flow_manager(hass, webhook_mock, ha_mcp):
    entry = await setup_entry(hass, mode="advanced")
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "access"}
    )
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], TRUSTED_INPUT)
    assert flow["step_id"] == "connect"
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {})
    assert flow["type"] is FlowResultType.MENU
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "finish"}
    )
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_TRUSTED] is True
    assert entry.options[CONF_TRUSTED_CONFIRM] is True
    assert TRUSTED_SWITCH in _switches(hass, entry)


async def test_access_saved_when_dialog_closed_on_connect(hass, webhook_mock, ha_mcp):
    """Closing the dialog on the Connect page (X) keeps the Access changes."""
    entry = await setup_entry(hass, mode="advanced")
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "access"}
    )
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], TRUSTED_INPUT)
    assert flow["step_id"] == "connect"
    hass.config_entries.options.async_abort(flow["flow_id"])  # what the X does
    await hass.async_block_till_done()
    assert entry.options[CONF_TRUSTED] is True
    assert entry.state is ConfigEntryState.LOADED
    assert TRUSTED_SWITCH in _switches(hass, entry)


async def test_every_page_saves_on_submit(hass, webhook_mock):
    entry = await setup_entry(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "budget"}
    )
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {CONF_MAX_PER_HOUR: 7, CONF_MAX_PER_DAY: 70}
    )
    assert flow["type"] is FlowResultType.MENU
    await hass.async_block_till_done()
    assert entry.options[CONF_MAX_PER_HOUR] == 7

    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "advanced_mode"}
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_MODE] == "advanced"

    # a second page in the same dialog still builds on the first
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "budget"}
    )
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {**_form_defaults(flow), CONF_MAX_PER_HOUR: 8, CONF_MAX_PER_DAY: 80}
    )
    hass.config_entries.options.async_abort(flow["flow_id"])
    await hass.async_block_till_done()
    assert entry.options[CONF_MAX_PER_HOUR] == 8
    assert entry.options[CONF_MAX_PER_DAY] == 80
    assert entry.options[CONF_MODE] == "advanced"
    assert entry.state is ConfigEntryState.LOADED


def _form_defaults(form) -> dict:
    out = {}
    for key in form["data_schema"].schema:
        default = getattr(key, "default", None)
        if callable(default):
            out[str(key)] = default()
    return out


async def test_saved_options_never_alias_the_flow(hass, webhook_mock):
    """Later edits in the same dialog must be detected as changes."""
    entry = await setup_entry(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    for hour in (3, 4):
        flow = await hass.config_entries.options.async_configure(
            flow["flow_id"], {"next_step_id": "budget"}
        )
        flow = await hass.config_entries.options.async_configure(
            flow["flow_id"], {CONF_MAX_PER_HOUR: hour, CONF_MAX_PER_DAY: 40}
        )
        await hass.async_block_till_done()
        assert entry.options[CONF_MAX_PER_HOUR] == hour
    before = entry.modified_at
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "finish"}
    )
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.modified_at == before  # already saved, finish is a no-op
