"""Grok Bot for Home Assistant.

Sends opt-in tasks, events and problems to a Grok Bot routine webhook. Grok Bot
acts back in Home Assistant through its own connector, or through the optional
token-protected access webhook, and answers with `grok_bot.reply`.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntry,
    ConfigEntryChange,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.typing import ConfigType

from .api import GrokBotClient
from .const import (
    CONF_ACCESS_METHOD,
    CONF_AUTH_HEADER,
    CONF_WEBHOOK_URL,
    DOMAIN,
    HA_MCP_INSTALL_URL,
    INTEGRATION_VERSION,
    ISSUE_MCP_MISSING,
    ISSUE_NOT_CONNECTED,
    MCP_PATH,
    METHOD_MCP,
    SIGNAL_CONNECTED,
)
from .hub import GrokBotHub
from .mcp import MCP_DOMAINS, ha_mcp_installed, setup_links
from .services import async_setup_services
from .triggers import TriggerManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.CONVERSATION,
    Platform.NOTIFY,
    Platform.SENSOR,
    Platform.SWITCH,
]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_FILENAME = "grok-bot-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILENAME}"


@dataclass
class GrokBotData:
    """Runtime data of one config entry."""

    hub: GrokBotHub
    triggers: TriggerManager


type GrokBotConfigEntry = ConfigEntry[GrokBotData]


def _file_digest(path: Path) -> str:
    """Short hash of the card file (cache buster)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register actions and the dashboard card once."""
    async_setup_services(hass)
    card = Path(__file__).parent / "frontend" / CARD_FILENAME
    if hass.http is not None:
        await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(card), True)])
    if "frontend" in hass.config.components:
        digest = await hass.async_add_executor_job(_file_digest, card)
        add_extra_js_url(hass, f"{CARD_URL}?v={INTEGRATION_VERSION}-{digest}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GrokBotConfigEntry) -> bool:
    """Set up Grok Bot from a config entry."""
    client = GrokBotClient(hass, entry.data[CONF_WEBHOOK_URL], entry.data[CONF_AUTH_HEADER])
    hub = GrokBotHub(hass, entry, client)
    await hub.async_load()
    triggers = TriggerManager(hass, entry, hub)
    entry.runtime_data = GrokBotData(hub, triggers)

    await hub.access.async_start()
    _async_update_mcp_issue(hass, hub)

    @callback
    def _mcp_changed(change: ConfigEntryChange, changed: ConfigEntry) -> None:
        if changed.domain in MCP_DOMAINS:
            _async_update_mcp_issue(hass, hub)
            hub.notify()

    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_CONFIG_ENTRY_CHANGED, _mcp_changed))

    @callback
    def _connected(entry_id: str) -> None:
        if entry_id == entry.entry_id:
            _async_update_connected_issue(hass, hub)

    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_CONNECTED, _connected))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    triggers.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


@callback
def _async_update_mcp_issue(hass: HomeAssistant, hub: GrokBotHub) -> None:
    """Repair issue pointing at the MCP Server setup while it is missing."""
    issue_id = f"{ISSUE_MCP_MISSING}_{hub.entry.entry_id}"
    if hub.options[CONF_ACCESS_METHOD] == METHOD_MCP and not hub.mcp_ready:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_MCP_MISSING,
            translation_placeholders={**setup_links(), "mcp_path": MCP_PATH},
            learn_more_url=HA_MCP_INSTALL_URL,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
    _async_update_connected_issue(hass, hub)


@callback
def _async_update_connected_issue(hass: HomeAssistant, hub: GrokBotHub) -> None:
    """'Grok Bot not connected yet' while HA-MCP is installed and no reply arrived."""
    issue_id = f"{ISSUE_NOT_CONNECTED}_{hub.entry.entry_id}"
    if ha_mcp_installed(hass) and not hub.connected:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_NOT_CONNECTED,
            translation_placeholders={"name": hub.entry.title},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: GrokBotConfigEntry) -> bool:
    """Unload a config entry."""
    data = entry.runtime_data
    data.triggers.async_stop()
    data.hub.access.async_stop()
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_MCP_MISSING}_{entry.entry_id}")
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_NOT_CONNECTED}_{entry.entry_id}")
    ir.async_delete_issue(hass, DOMAIN, f"trusted_always_on_{entry.entry_id}")
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await data.hub.async_shutdown()
    return unloaded
