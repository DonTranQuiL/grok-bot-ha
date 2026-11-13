"""Diagnostics with every secret redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import GrokBotConfigEntry
from .const import CONF_AUTH_HEADER, CONF_INBOUND_WEBHOOK_ID, CONF_WEBHOOK_URL

TO_REDACT = {
    CONF_AUTH_HEADER,
    CONF_WEBHOOK_URL,
    CONF_INBOUND_WEBHOOK_ID,
    "access_url",
    "access_token",
    "token",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GrokBotConfigEntry
) -> dict[str, Any]:
    hub = entry.runtime_data.hub
    return {
        "entry": async_redact_data(
            {"title": entry.title, "data": dict(entry.data), "options": dict(entry.options)},
            TO_REDACT,
        ),
        "webhook_host": hub.client.host,
        "runtime": async_redact_data(
            {
                "paused": hub.paused,
                "stats": hub.stats,
                "sends_last_hour": hub.sends_hour,
                "sends_last_24h": hub.sends_day,
                "limits": {"hour": hub.max_hour, "day": hub.max_day},
                "last_status": hub.last_status,
                "last_error": hub.last_error,
                "pending_conversations": len(hub.pending),
                "history": [
                    {k: v for k, v in item.items() if k != "message"} for item in hub.history
                ],
                "access_level": hub.access.level,
                "access_url": hub.access.url,
                "access_url_source": hub.access.url_source,
                "access_token": hub.access.token,
                "open_sessions": len(hub.access.sessions),
                "audit": list(hub.access.audit),
            },
            TO_REDACT,
        ),
    }
