"""Actions, budget, pause, replies, notify, Assist and buttons."""

from __future__ import annotations

from homeassistant.components import conversation
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.grok_bot.const import DOMAIN

from .conftest import URL, posted, setup_entry


async def _ask(hass, **data):
    return await hass.services.async_call(
        DOMAIN, "ask", {"message": "hello", **data}, blocking=True, return_response=True
    )


async def test_ask_payload_and_response(hass, webhook_mock):
    hass.states.async_set("sensor.temp", "21.5", {"unit_of_measurement": "°C"})
    await setup_entry(hass)
    sent = async_capture_events(hass, "grok_bot_sent")
    resp = await _ask(
        hass,
        context_entities=["sensor.temp"],
        reply_to="input_text.answer",
        conversation_id="c1",
        notify_user=True,
        action_mode="diagnose",
    )
    assert resp["status"] == "sent"
    assert resp["conversation_id"] == "c1"
    assert resp["sends_last_24h"] == 1
    assert resp["remaining_last_hour"] == 19
    payload = posted(webhook_mock)[0]
    assert payload["type"] == "ask"
    assert payload["message"] == "hello"
    assert payload["source"] == "service"
    assert payload["reply_to"] == "input_text.answer"
    assert payload["notify_user"] is True
    assert payload["action_mode"] == "diagnose"
    assert payload["allow_fix"] is False
    assert payload["context"][0]["state"] == "21.5"
    assert payload["context"][0]["attributes"]["unit_of_measurement"] == "°C"
    assert payload["ha_instance"]["name"]
    assert payload["reply_with"]["service"] == "grok_bot.reply"
    assert payload["timestamp"]
    assert len(sent) == 1
    headers = webhook_mock.mock_calls[0][3]
    assert headers["Authorization"] == "Bearer super-secret-token"
    assert hass.states.get("sensor.grok_bot_last_status").state == "sent"
    assert hass.states.get("sensor.grok_bot_sends_last_24_hours").state == "1"


async def test_budget_drops_and_bypass(hass, webhook_mock):
    await setup_entry(hass, max_per_hour=2, max_per_day=3)
    dropped = async_capture_events(hass, "grok_bot_dropped")
    assert (await _ask(hass))["status"] == "sent"
    assert (await _ask(hass))["status"] == "sent"
    resp = await _ask(hass)
    assert resp["status"] == "dropped_budget"
    assert len(posted(webhook_mock)) == 2  # dropped, not queued
    assert dropped[0].data["reason"] == "dropped_budget"
    resp = await _ask(hass, bypass_budget=True)
    assert resp["status"] == "sent"
    assert resp["sends_last_24h"] == 3  # bypass still counts
    assert hass.states.get("sensor.grok_bot_dropped_total").state == "1"
    # reset button clears the counters
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.grok_bot_reset_budget_counters"}, blocking=True
    )
    assert (await _ask(hass))["status"] == "sent"


async def test_pause_switch_blocks_everything(hass, webhook_mock):
    await setup_entry(hass)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.grok_bot_pause_sending"}, blocking=True
    )
    resp = await _ask(hass, bypass_budget=True)
    assert resp["status"] == "dropped_paused"
    assert posted(webhook_mock) == []
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.grok_bot_pause_sending"}, blocking=True
    )
    assert (await _ask(hass))["status"] == "sent"


async def test_auth_failure_starts_reauth(hass, aioclient_mock):
    aioclient_mock.post(URL, status=401)
    entry = await setup_entry(hass)
    resp = await _ask(hass)
    assert resp["status"] == "auth_failed"
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flows and flows[0]["context"]["source"] == "reauth"
    assert entry.state.value == "loaded"


async def test_reply_updates_sensor_event_and_input_text(hass, webhook_mock):
    assert await async_setup_component(hass, "input_text", {"input_text": {"answer": {"max": 20}}})
    await setup_entry(hass)
    replies = async_capture_events(hass, "grok_bot_reply")
    await _ask(hass, reply_to="input_text.answer", conversation_id="c9")
    await hass.services.async_call(
        DOMAIN,
        "reply",
        {"message": "The tilt motor was stuck, I reset it.", "conversation_id": "c9"},
        blocking=True,
    )
    state = hass.states.get("sensor.grok_bot_last_reply")
    assert state.state == "The tilt motor was stuck, I reset it."
    assert state.attributes["conversation_id"] == "c9"
    assert [h["direction"] for h in state.attributes["history"]] == ["out", "in"]
    assert replies[0].data["reply_to"] == "input_text.answer"
    assert hass.states.get("input_text.answer").state == "The tilt motor was st"[:20]
    assert hass.states.get("sensor.grok_bot_awaiting_reply").state == "0"


async def test_reply_to_persistent_notification_and_no_loop(hass, webhook_mock):
    await setup_entry(hass, enable_notify=True)
    await hass.services.async_call(
        DOMAIN,
        "reply",
        {"message": "hi", "reply_to": "notify.grok_bot"},
        blocking=True,
    )
    assert posted(webhook_mock) == []  # never loops back to Grok Bot
    await hass.services.async_call(
        DOMAIN,
        "reply",
        {"message": "hello there", "reply_to": "persistent_notification"},
        blocking=True,
    )


async def test_inbound_webhook(hass, webhook_mock, hass_client_no_auth):
    entry = await setup_entry(hass, access_method="webhook", access_require_pending=False)
    token = entry.runtime_data.hub.access.token
    client = await hass_client_no_auth()
    resp = await client.post("/api/webhook/inbound-test-id", json={"message": "no token"})
    assert resp.status == 401
    resp = await client.post(
        "/api/webhook/inbound-test-id",
        json={"message": "from webhook"},
        headers={"X-Grok-Bot-Token": token},
    )
    assert resp.status == 200
    assert hass.states.get("sensor.grok_bot_last_reply").state == "from webhook"
    resp = await client.post(
        "/api/webhook/inbound-test-id", json={"nope": 1}, headers={"X-Grok-Bot-Token": token}
    )
    assert resp.status == 400


async def test_inbound_webhook_off_by_default(hass, webhook_mock, hass_client_no_auth):
    await setup_entry(hass)
    client = await hass_client_no_auth()
    await client.post("/api/webhook/inbound-test-id", json={"message": "x"})
    assert hass.states.get("sensor.grok_bot_last_reply").state == "unknown"


async def test_send_event_and_ping(hass, webhook_mock):
    await setup_entry(hass)
    await hass.services.async_call(
        DOMAIN,
        "send_event",
        {"event_type": "doorbell", "data": {"door": "front"}},
        blocking=True,
        return_response=True,
    )
    await hass.services.async_call(DOMAIN, "ping", {}, blocking=True, return_response=True)
    first, second = posted(webhook_mock)
    assert first["type"] == "custom_event"
    assert first["data"] == {"event_type": "doorbell", "event_data": {"door": "front"}}
    assert second["type"] == "ping"


async def test_diagnose_and_fix_issue(hass, webhook_mock):
    await setup_entry(hass)
    ir.async_create_issue(
        hass,
        "zha",
        "radio_lost",
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="radio_lost",
    )
    resp = await hass.services.async_call(
        DOMAIN, "fix_issue", {"issue_id": "radio_lost"}, blocking=True, return_response=True
    )
    assert resp["status"] == "sent"
    payload = posted(webhook_mock)[0]
    assert payload["type"] == "fix_issue"
    assert payload["allow_fix"] is True
    assert payload["action_mode"] == "fix"
    assert payload["data"]["issue"]["domain"] == "zha"
    assert "radio_lost" in payload["message"]
    await hass.services.async_call(
        DOMAIN,
        "diagnose",
        {"message": "Why is the hallway light slow?"},
        blocking=True,
        return_response=True,
    )
    assert posted(webhook_mock)[1]["allow_fix"] is False
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "diagnose", {}, blocking=True, return_response=True)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "fix_issue", {"issue_id": "nope"}, blocking=True, return_response=True
        )


async def test_health_report_and_buttons(hass, webhook_mock):
    hass.states.async_set("light.broken", "unavailable")
    await setup_entry(hass)
    resp = await hass.services.async_call(
        DOMAIN, "health_report", {}, blocking=True, return_response=True
    )
    assert resp["status"] == "sent"
    payload = posted(webhook_mock)[0]
    assert payload["action_mode"] == "diagnose"
    assert "light.broken" in payload["data"]["unavailable_entities"]
    for button in ("send_test_ping", "send_health_report", "fix_open_repairs"):
        await hass.services.async_call(
            "button", "press", {"entity_id": f"button.grok_bot_{button}"}, blocking=True
        )
    kinds = [p["type"] for p in posted(webhook_mock)]
    assert kinds == ["health_report", "ping", "health_report", "fix_issue"]
    assert posted(webhook_mock)[-1]["allow_fix"] is True


async def test_unknown_entry_id(hass, webhook_mock):
    await setup_entry(hass)
    with pytest.raises(ServiceValidationError):
        await _ask(hass, config_entry_id="missing")


async def test_notify_entity_opt_in(hass, webhook_mock):
    await setup_entry(hass)
    assert hass.states.get("notify.grok_bot") is None
    assert hass.states.get("conversation.grok_bot") is None


async def test_notify_entity(hass, webhook_mock):
    await setup_entry(hass, enable_notify=True)
    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": "notify.grok_bot", "message": "Washer done", "title": "Laundry"},
        blocking=True,
    )
    payload = posted(webhook_mock)[0]
    assert payload["type"] == "notify"
    assert payload["message"] == "Laundry\nWasher done"


async def test_conversation_agent(hass, webhook_mock):
    await setup_entry(hass, enable_conversation=True)
    result = await conversation.async_converse(
        hass, "turn the porch light on", None, Context(), agent_id="conversation.grok_bot"
    )
    speech = result.response.speech["plain"]["speech"]
    assert speech == "Sent to Grok Bot. I'll answer shortly."
    payload = posted(webhook_mock)[0]
    assert payload["type"] == "conversation"
    assert payload["message"] == "turn the porch light on"
    assert payload["conversation_id"] == result.conversation_id
    result = await conversation.async_converse(
        hass,
        "doe het licht aan",
        None,
        Context(),
        language="nl",
        agent_id="conversation.grok_bot",
    )
    assert "Grok Bot" in result.response.speech["plain"]["speech"]
    assert result.response.speech["plain"]["speech"].startswith("Doorgestuurd")
