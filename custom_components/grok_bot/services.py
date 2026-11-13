"""Grok Bot actions (services)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import (
    ACTION_DIAGNOSE,
    ACTION_FIX,
    ACTION_MODES,
    ACTION_REPORT,
    ATTR_ACTION_MODE,
    ATTR_BYPASS_BUDGET,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_CONTEXT_ENTITIES,
    ATTR_CONVERSATION_ID,
    ATTR_DATA,
    ATTR_EVENT_TYPE,
    ATTR_ISSUE_DOMAIN,
    ATTR_ISSUE_ID,
    ATTR_MESSAGE,
    ATTR_NOTIFY_USER,
    ATTR_REPLY_TO,
    ATTR_TARGET_ENTRY,
    ATTR_TITLE,
    DOMAIN,
    SERVICE_ASK,
    SERVICE_DIAGNOSE,
    SERVICE_FIX_ISSUE,
    SERVICE_HEALTH_REPORT,
    SERVICE_PING,
    SERVICE_REPLY,
    SERVICE_ROTATE_TOKEN,
    SERVICE_SEND_EVENT,
)

if TYPE_CHECKING:
    from .hub import GrokBotHub

_BASE = {
    vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    vol.Optional(ATTR_BYPASS_BUDGET, default=False): cv.boolean,
}
_COMMON = {
    **_BASE,
    vol.Optional(ATTR_CONTEXT_ENTITIES, default=[]): cv.entity_ids,
    vol.Optional(ATTR_REPLY_TO): vol.Any(None, cv.string),
    vol.Optional(ATTR_CONVERSATION_ID): vol.Any(None, cv.string),
    vol.Optional(ATTR_NOTIFY_USER, default=False): cv.boolean,
}

ASK_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_ACTION_MODE, default=ACTION_REPORT): vol.In(ACTION_MODES),
        vol.Optional(ATTR_DATA, default={}): dict,
        **_COMMON,
    }
)
SEND_EVENT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_EVENT_TYPE): cv.string,
        vol.Optional(ATTR_MESSAGE, default=""): cv.string,
        vol.Optional(ATTR_DATA, default={}): dict,
        vol.Optional(ATTR_ACTION_MODE, default=ACTION_REPORT): vol.In(ACTION_MODES),
        **_COMMON,
    }
)
DIAGNOSE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_MESSAGE, default=""): cv.string,
        vol.Optional(ATTR_ISSUE_ID): cv.string,
        vol.Optional(ATTR_ISSUE_DOMAIN): cv.string,
        vol.Optional(ATTR_TARGET_ENTRY): cv.string,
        **_COMMON,
    }
)
HEALTH_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ACTION_MODE, default=ACTION_DIAGNOSE): vol.In(ACTION_MODES),
        **_COMMON,
    }
)
PING_SCHEMA = vol.Schema(_BASE)
REPLY_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_CONVERSATION_ID): vol.Any(None, cv.string),
        vol.Optional(ATTR_TITLE): vol.Any(None, cv.string),
        vol.Optional(ATTR_REPLY_TO): vol.Any(None, cv.string),
        vol.Optional(ATTR_DATA, default={}): dict,
    }
)


def _hub(hass: HomeAssistant, call: ServiceCall) -> GrokBotHub:
    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    entries = [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED
    ]
    if entry_id:
        entries = [e for e in entries if e.entry_id == entry_id]
        if not entries:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_found",
                translation_placeholders={"entry_id": entry_id},
            )
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
    if len(entries) > 1:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="multiple_entries")
    return entries[0].runtime_data.hub


def _common(call: ServiceCall) -> dict[str, Any]:
    return {
        "context_entities": call.data.get(ATTR_CONTEXT_ENTITIES, []),
        "reply_to": call.data.get(ATTR_REPLY_TO) or None,
        "conversation_id": call.data.get(ATTR_CONVERSATION_ID) or None,
        "notify_user": call.data.get(ATTR_NOTIFY_USER, False),
        "bypass_budget": call.data.get(ATTR_BYPASS_BUDGET, False),
    }


def _target_entry_info(hass: HomeAssistant, entry_id: str | None) -> dict | None:
    if not entry_id:
        return None
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_found",
            translation_placeholders={"entry_id": entry_id},
        )
    return {
        "domain": entry.domain,
        "config_entry_id": entry.entry_id,
        "title": entry.title,
        "state": entry.state.value,
        "reason": entry.reason,
    }


def _issue(hass: HomeAssistant, call: ServiceCall) -> dict | None:
    from .triggers import issue_info

    issue_id = call.data.get(ATTR_ISSUE_ID)
    if not issue_id:
        return None
    domain = call.data.get(ATTR_ISSUE_DOMAIN)
    if not domain:
        from homeassistant.helpers import issue_registry as ir

        matches = [d for (d, i) in ir.async_get(hass).issues if i == issue_id]
        domain = matches[0] if matches else None
    info = issue_info(hass, domain, issue_id) if domain else None
    if info is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="issue_not_found",
            translation_placeholders={"issue_id": issue_id},
        )
    return info


def health_snapshot(hass: HomeAssistant, hub: GrokBotHub) -> dict[str, Any]:
    """Open repairs, failed integrations, unavailable entities, recent errors."""
    from .triggers import open_issues

    unavailable = [
        s.entity_id
        for s in hass.states.async_all()
        if s.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)
    ]
    failed = [
        {"domain": e.domain, "title": e.title, "state": e.state.value, "reason": e.reason}
        for e in hass.config_entries.async_entries()
        if e.state in (ConfigEntryState.SETUP_ERROR, ConfigEntryState.SETUP_RETRY)
    ]
    return {
        "repair_issues": open_issues(hass),
        "failed_integrations": failed,
        "unavailable_count": len(unavailable),
        "unavailable_entities": unavailable[:50],
        "recent_errors": list(hub.recent_errors)[-10:],
    }


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register every Grok Bot action."""

    async def ask(call: ServiceCall) -> ServiceResponse:
        hub = _hub(hass, call)
        return await hub.async_send(
            "ask",
            call.data[ATTR_MESSAGE],
            source="service",
            action_mode=call.data[ATTR_ACTION_MODE],
            data=call.data[ATTR_DATA],
            **_common(call),
        )

    async def send_event(call: ServiceCall) -> ServiceResponse:
        hub = _hub(hass, call)
        event_type = call.data[ATTR_EVENT_TYPE]
        return await hub.async_send(
            "custom_event",
            call.data[ATTR_MESSAGE] or f"Event {event_type}",
            source="service",
            action_mode=call.data[ATTR_ACTION_MODE],
            data={"event_type": event_type, "event_data": call.data[ATTR_DATA]},
            **_common(call),
        )

    async def diagnose(call: ServiceCall) -> ServiceResponse:
        return await _problem(call, ACTION_DIAGNOSE)

    async def fix_issue(call: ServiceCall) -> ServiceResponse:
        return await _problem(call, ACTION_FIX)

    async def _problem(call: ServiceCall, mode: str) -> ServiceResponse:
        hub = _hub(hass, call)
        issue = _issue(hass, call)
        target = _target_entry_info(hass, call.data.get(ATTR_TARGET_ENTRY))
        message = call.data.get(ATTR_MESSAGE) or ""
        if not (message or issue or target or call.data.get(ATTR_CONTEXT_ENTITIES)):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="nothing_to_diagnose"
            )
        if not message:
            what = (
                f"repair issue {issue['domain']}.{issue['issue_id']}"
                if issue
                else f"integration {target['domain']}"
                if target
                else "the attached entities"
            )
            verb = "Diagnose and, if safe, fix" if mode == ACTION_FIX else "Diagnose"
            message = f"{verb} {what}."
        return await hub.async_send(
            SERVICE_FIX_ISSUE if mode == ACTION_FIX else SERVICE_DIAGNOSE,
            message,
            source="service",
            action_mode=mode,
            data={"issue": issue, "config_entry": target},
            **_common(call),
        )

    async def health_report(call: ServiceCall) -> ServiceResponse:
        hub = _hub(hass, call)
        snap = health_snapshot(hass, hub)
        message = (
            f"Health report: {len(snap['repair_issues'])} repair issues, "
            f"{len(snap['failed_integrations'])} failed integrations, "
            f"{snap['unavailable_count']} unavailable entities, "
            f"{len(snap['recent_errors'])} recent errors."
        )
        return await hub.async_send(
            "health_report",
            message,
            source="service",
            action_mode=call.data[ATTR_ACTION_MODE],
            data=snap,
            **_common(call),
        )

    async def ping(call: ServiceCall) -> ServiceResponse:
        hub = _hub(hass, call)
        return await hub.async_send(
            "ping",
            "Ping from Home Assistant",
            source="service",
            bypass_budget=call.data[ATTR_BYPASS_BUDGET],
        )

    async def reply(call: ServiceCall) -> None:
        hub = _hub(hass, call)
        await hub.async_handle_reply(
            call.data[ATTR_MESSAGE],
            conversation_id=call.data.get(ATTR_CONVERSATION_ID) or None,
            title=call.data.get(ATTR_TITLE) or None,
            data=call.data[ATTR_DATA],
            reply_to=call.data.get(ATTR_REPLY_TO) or None,
        )

    async def rotate_token(call: ServiceCall) -> None:
        hub = _hub(hass, call)
        hub.access.rotate_token()

    optional = SupportsResponse.OPTIONAL
    for name, handler, schema, response in (
        (SERVICE_ASK, ask, ASK_SCHEMA, optional),
        (SERVICE_SEND_EVENT, send_event, SEND_EVENT_SCHEMA, optional),
        (SERVICE_DIAGNOSE, diagnose, DIAGNOSE_SCHEMA, optional),
        (SERVICE_FIX_ISSUE, fix_issue, DIAGNOSE_SCHEMA, optional),
        (SERVICE_HEALTH_REPORT, health_report, HEALTH_SCHEMA, optional),
        (SERVICE_PING, ping, PING_SCHEMA, optional),
        (SERVICE_REPLY, reply, REPLY_SCHEMA, SupportsResponse.NONE),
        (
            SERVICE_ROTATE_TOKEN,
            rotate_token,
            vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}),
            SupportsResponse.NONE,
        ),
    ):
        hass.services.async_register(
            DOMAIN, name, handler, schema=schema, supports_response=response
        )
