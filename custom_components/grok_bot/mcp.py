"""Detect which MCP server Grok Bot can use to reach back into this instance.

Order of preference:
1. HA-MCP (``ha_mcp_tools``, homeassistant-ai/ha-mcp), its "HA-MCP Server" entry.
   Remote URL: ``<external or Nabu Casa URL>/api/webhook/<webhook id>`` as shown on
   the HA-MCP Configure screen (we never read or forward that id).
2. Core MCP Server (``mcp_server``): ``<external URL>/api/mcp`` with OAuth or a
   long-lived access token; the selected LLM API / Assist exposure decides scope.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import (
    HA_MCP_DOMAIN,
    HA_MCP_INSTALL_URL,
    HA_MCP_SERVER_ENTRY_TYPE,
    HA_MCP_SETUP_URL,
    MCP_DOMAIN,
    MCP_PATH,
    MCP_SETUP_URL,
    PROVIDER_HA_MCP,
    PROVIDER_MCP_SERVER,
)

MCP_DOMAINS = (HA_MCP_DOMAIN, MCP_DOMAIN)


def _ha_mcp_server_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    entries = hass.config_entries.async_entries(HA_MCP_DOMAIN)
    servers = [e for e in entries if e.data.get("entry_type") == HA_MCP_SERVER_ENTRY_TYPE]
    # Older HA-MCP releases had no entry_type; their entry title names the server.
    return servers or [e for e in entries if "server" in (e.title or "").lower()]


def _loaded(entries: list[ConfigEntry]) -> bool:
    return any(e.state is ConfigEntryState.LOADED for e in entries)


def detect_mcp(hass: HomeAssistant, external_url: str | None = None) -> dict[str, Any]:
    """Provider, readiness and a connector URL hint (no secrets)."""
    base = external_url or "https://<your-external-or-nabu-casa-url>"
    ha_mcp = _ha_mcp_server_entries(hass)
    core = hass.config_entries.async_entries(MCP_DOMAIN)
    ha_mcp_hint = f"{base}/api/webhook/<HA-MCP webhook id from its Configure screen>"
    core_hint = f"{base}{MCP_PATH}"
    if _loaded(ha_mcp):
        provider, ready, hint = PROVIDER_HA_MCP, True, ha_mcp_hint
    elif _loaded(core):
        provider, ready, hint = PROVIDER_MCP_SERVER, True, core_hint
    elif ha_mcp:
        provider, ready, hint = PROVIDER_HA_MCP, False, ha_mcp_hint
    elif core:
        provider, ready, hint = PROVIDER_MCP_SERVER, False, core_hint
    else:
        provider, ready, hint = None, False, None
    return {
        "provider": provider,
        "ready": ready,
        "connector_url_hint": hint,
        "ha_mcp_installed": bool(hass.config_entries.async_entries(HA_MCP_DOMAIN)),
        "mcp_server_installed": bool(core),
    }


def ha_mcp_installed(hass: HomeAssistant) -> bool:
    """Gate for the connect step, setup prompt and 'not connected' repair."""
    return bool(_ha_mcp_server_entries(hass))


def setup_links() -> dict[str, str]:
    return {
        "ha_mcp_install_url": HA_MCP_INSTALL_URL,
        "ha_mcp_setup_url": HA_MCP_SETUP_URL,
        "mcp_setup_url": MCP_SETUP_URL,
    }
