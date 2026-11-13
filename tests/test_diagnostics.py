"""Diagnostics redaction, payload size limit, persistence and unload."""

from __future__ import annotations

import json

from custom_components.grok_bot.diagnostics import async_get_config_entry_diagnostics

from .conftest import AUTH, URL, posted, setup_entry


async def test_diagnostics_redacts_secrets(hass, webhook_mock):
    entry = await setup_entry(hass, enable_inbound_webhook=True)
    await hass.services.async_call(
        "grok_bot", "ask", {"message": "private text"}, blocking=True, return_response=True
    )
    diag = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(diag, default=str)
    assert AUTH not in dumped
    assert "super-secret-token" not in dumped
    assert URL not in dumped
    assert "inbound-test-id" not in dumped
    assert "private text" not in dumped
    assert diag["entry"]["data"]["auth_header"] == "**REDACTED**"
    assert diag["entry"]["data"]["webhook_url"] == "**REDACTED**"
    assert diag["runtime"]["stats"]["sent"] == 1
    assert diag["webhook_host"] == "hooks.example.test"


async def test_secret_never_logged(hass, aioclient_mock, caplog):
    import aiohttp

    aioclient_mock.post(URL, exc=aiohttp.ClientConnectionError("down"))
    await setup_entry(hass)
    caplog.set_level("DEBUG")
    resp = await hass.services.async_call(
        "grok_bot", "ask", {"message": "x"}, blocking=True, return_response=True
    )
    assert resp["status"] == "failed"
    assert "super-secret-token" not in caplog.text
    assert URL not in caplog.text
    assert hass.states.get("sensor.grok_bot_failed_total").state == "1"


async def test_payload_size_limit(hass, webhook_mock):
    hass.states.async_set("sensor.big", "1", {"blob": "x" * 5000})
    await setup_entry(hass, max_payload_bytes=2000)
    resp = await hass.services.async_call(
        "grok_bot",
        "ask",
        {"message": "y" * 3000, "context_entities": ["sensor.big"]},
        blocking=True,
        return_response=True,
    )
    assert resp["status"] == "sent"
    payload = posted(webhook_mock)[0]
    assert payload["truncated"] is True
    assert "attributes" not in payload["context"][0]
    assert len(json.dumps(payload).encode()) <= 2000


async def test_budget_and_pause_survive_reload(hass, webhook_mock):
    entry = await setup_entry(hass)
    await hass.services.async_call(
        "grok_bot", "ask", {"message": "x"}, blocking=True, return_response=True
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.grok_bot_pause_sending"}, blocking=True
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("switch.grok_bot_pause_sending").state == "on"
    assert hass.states.get("sensor.grok_bot_sends_last_24_hours").state == "1"
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state.value == "not_loaded"
