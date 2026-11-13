"""Shared fixtures for Grok Bot tests."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.grok_bot.const import (
    CONF_AUTH_HEADER,
    CONF_INBOUND_WEBHOOK_ID,
    CONF_WEBHOOK_URL,
    DEFAULT_OPTIONS,
    DOMAIN,
)

URL = "https://hooks.example.test/routine/abc123"
AUTH = "Bearer super-secret-token"


@pytest.fixture(autouse=True)
async def auto_enable_custom_integrations(hass, enable_custom_integrations):
    """Load custom_components/grok_bot (and HA core, needed by Assist)."""
    assert await async_setup_component(hass, "homeassistant", {})


def make_entry(unique_id: str = "test-unique", **options: Any) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Grok Bot",
        unique_id=unique_id,
        data={
            "name": "Grok Bot",
            CONF_WEBHOOK_URL: URL,
            CONF_AUTH_HEADER: AUTH,
            CONF_INBOUND_WEBHOOK_ID: "inbound-test-id",
        },
        options={**DEFAULT_OPTIONS, **options},
    )


@pytest.fixture
def webhook_mock(aioclient_mock):
    """Grok Bot webhook that accepts everything."""
    aioclient_mock.post(URL, status=200, json={"ok": True})
    return aioclient_mock


def posted(aioclient_mock) -> list[dict]:
    """All JSON payloads posted to the webhook."""
    out = []
    for _method, url, data, _headers in aioclient_mock.mock_calls:
        if str(url) == URL:
            out.append(json.loads(data))
    return out


async def setup_entry(hass, **options):
    entry = make_entry(**options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
