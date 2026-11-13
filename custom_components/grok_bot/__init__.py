"""Grok Bot for Home Assistant.

Sends opt-in tasks, events and problems to a Grok Bot routine webhook. Grok Bot
acts back in Home Assistant through its own connector and answers with the
`grok_bot.reply` action (or the optional inbound webhook).
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import GrokBotClient
from .const import (
    CONF_AUTH_HEADER,
    CONF_ENABLE_INBOUND_WEBHOOK,
    CONF_INBOUND_WEBHOOK_ID,
    CONF_WEBHOOK_URL,
    DOMAIN,
    INTEGRATION_VERSION,
)
from .hub import GrokBotHub
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

    if hub.options[CONF_ENABLE_INBOUND_WEBHOOK] and (
        webhook_id := entry.data.get(CONF_INBOUND_WEBHOOK_ID)
    ):
        webhook.async_register(
            hass,
            DOMAIN,
            f"Grok Bot replies ({entry.title})",
            webhook_id,
            _make_webhook_handler(entry),
            allowed_methods=["POST"],
        )
        hub.inbound_webhook_url = webhook.async_generate_path(webhook_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    triggers.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: GrokBotConfigEntry) -> bool:
    """Unload a config entry."""
    data = entry.runtime_data
    data.triggers.async_stop()
    if webhook_id := entry.data.get(CONF_INBOUND_WEBHOOK_ID):
        webhook.async_unregister(hass, webhook_id)
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    await data.hub.async_shutdown()
    return unloaded


def _make_webhook_handler(entry: GrokBotConfigEntry):
    async def _handle(hass: HomeAssistant, webhook_id: str, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "invalid_json"}, status=400)
        if not isinstance(body, dict) or not str(body.get("message", "")).strip():
            return web.json_response({"error": "message_required"}, status=400)
        result = await entry.runtime_data.hub.async_handle_reply(
            str(body["message"]),
            conversation_id=body.get("conversation_id"),
            title=body.get("title"),
            data=body.get("data") if isinstance(body.get("data"), dict) else None,
            reply_to=body.get("reply_to"),
        )
        return web.json_response({"ok": True, **result})

    return _handle
