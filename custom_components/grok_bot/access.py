"""User-controlled access for Grok Bot into this Home Assistant.

Grok Bot's own Home Assistant connector only reaches the instances it was
connected to. For any other instance (e.g. a local test system) the user can
enable the token-protected *access webhook*. Every outgoing payload then carries
a `callback` block (URL, token, level, allowed actions, expiry) and Grok Bot
posts commands back:

    {"token": "...", "conversation_id": "...", "actions": [{"type": "...", ...}]}

and gets the results synchronously in the webhook response.
"""

from __future__ import annotations

from collections import deque
from datetime import timedelta
import hmac
import json
import logging
import secrets
import time as _time
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, HomeAssistant, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from .const import (
    ACCESS_OFF,
    ACCESS_REPLY,
    ACT_CALL_SERVICE,
    ACT_ENABLE_ENTITY,
    ACT_GET_HISTORY,
    ACT_GET_LOGS,
    ACT_GET_STATES,
    ACT_IGNORE_REPAIR,
    ACT_LIST_ENTRIES,
    ACT_LIST_REPAIRS,
    ACT_RELOAD_ENTRY,
    ACT_REPLY,
    AUDIT_LEN,
    BLOCKED_SERVICE_DOMAINS,
    BLOCKED_SERVICES,
    CALLBACK_PROTOCOL_VERSION,
    CONF_ACCESS_ACTIONS,
    CONF_ACCESS_DOMAINS,
    CONF_ACCESS_ENTITIES,
    CONF_ACCESS_LEVEL,
    CONF_ACCESS_MAX_RESPONSE,
    CONF_ACCESS_METHOD,
    CONF_ACCESS_NOTIFY,
    CONF_ACCESS_REQUIRE_PENDING,
    CONF_ACCESS_TTL,
    CONF_INBOUND_WEBHOOK_ID,
    DOMAIN,
    EVENT_ACTION,
    FIX_ACTIONS,
    LEVEL_ACTIONS,
    MAX_ACTIONS_PER_REQUEST,
    METHOD_MCP,
    METHOD_WEBHOOK,
    TOKEN_HEADER,
)

if TYPE_CHECKING:
    from .hub import GrokBotHub

_LOGGER = logging.getLogger(__name__)

URL_SOURCE_CLOUD = "cloud"
URL_SOURCE_EXTERNAL = "external"
URL_SOURCE_NONE = "none"
SESSIONS_LEN = 100


class AccessDenied(Exception):
    """An action is not allowed (reason is safe to return)."""


def access_method(options: dict[str, Any]) -> str:
    """mcp (default) | webhook | none (see options_of for the 0.1.0 migration)."""
    return options.get(CONF_ACCESS_METHOD) or METHOD_MCP


def effective_level(options: dict[str, Any]) -> str:
    """Access level of the access webhook ('off' unless the webhook method is used)."""
    if access_method(options) != METHOD_WEBHOOK:
        return ACCESS_OFF
    return options.get(CONF_ACCESS_LEVEL) or ACCESS_REPLY


def allowed_actions(options: dict[str, Any]) -> list[str]:
    """Action types allowed by the level AND the per-action toggles."""
    level_set = LEVEL_ACTIONS.get(effective_level(options), frozenset())
    toggles = options.get(CONF_ACCESS_ACTIONS)
    if toggles is None:
        toggles = list(level_set)
    return sorted(a for a in level_set if a in toggles)


def service_blocked(domain: str, service: str) -> bool:
    """The hard denylist: never callable, whatever the level or allowlist."""
    return domain in BLOCKED_SERVICE_DOMAINS or f"{domain}.{service}" in BLOCKED_SERVICES


def _ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(v) for v in value]


class AccessManager:
    """Token, URL, sessions, audit and the command executor of one entry."""

    def __init__(self, hass: HomeAssistant, hub: GrokBotHub) -> None:
        self.hass = hass
        self.hub = hub
        self.token: str = ""
        self.url: str | None = None
        self.url_source: str = URL_SOURCE_NONE
        self.sessions: dict[str, float] = {}
        self.audit: deque[dict[str, Any]] = deque(maxlen=AUDIT_LEN)
        self._registered = False

    # ------------------------------------------------------------- state
    @property
    def options(self) -> dict[str, Any]:
        return self.hub.options

    @property
    def level(self) -> str:
        return effective_level(self.options)

    @property
    def enabled(self) -> bool:
        return self.level != ACCESS_OFF

    @property
    def webhook_id(self) -> str | None:
        return self.hub.entry.data.get(CONF_INBOUND_WEBHOOK_ID)

    @property
    def ttl_seconds(self) -> float:
        return float(self.options[CONF_ACCESS_TTL]) * 60

    def load(self, data: dict[str, Any]) -> None:
        self.token = data.get("access_token") or secrets.token_urlsafe(32)
        self.audit.extend(data.get("audit", [])[-AUDIT_LEN:])

    def to_store(self) -> dict[str, Any]:
        return {"access_token": self.token, "audit": list(self.audit)}

    @callback
    def rotate_token(self) -> None:
        """New secret: the old token stops working immediately."""
        self.token = secrets.token_urlsafe(32)
        self.sessions.clear()
        self._log({"type": "rotate_token", "ok": True, "summary": "token rotated"})

    # ----------------------------------------------------------- lifecycle
    async def async_start(self) -> None:
        if not self.enabled or not self.webhook_id:
            return
        webhook.async_register(
            self.hass,
            DOMAIN,
            f"Grok Bot access ({self.hub.entry.title})",
            self.webhook_id,
            self._handle_webhook,
            local_only=False,
            allowed_methods=["POST"],
        )
        self._registered = True
        self.url, self.url_source = await self._async_resolve_url()
        if self.url is None:
            _LOGGER.info(
                "Grok Bot access is on but there is no external URL; set one under "
                "Settings > System > Network or log in to Home Assistant Cloud"
            )

    @callback
    def async_stop(self) -> None:
        if self._registered and self.webhook_id:
            webhook.async_unregister(self.hass, self.webhook_id)
        self._registered = False

    async def _async_resolve_url(self) -> tuple[str | None, str]:
        """Nabu Casa cloudhook when available, else the external URL."""
        webhook_id = self.webhook_id or ""
        if "cloud" in self.hass.config.components:
            from homeassistant.components import cloud

            if cloud.async_active_subscription(self.hass) and cloud.async_is_connected(self.hass):
                try:
                    return (
                        await cloud.async_get_or_create_cloudhook(self.hass, webhook_id),
                        URL_SOURCE_CLOUD,
                    )
                except Exception as err:
                    _LOGGER.debug("Cloudhook not available: %s", type(err).__name__)
        try:
            base = get_url(
                self.hass,
                allow_internal=False,
                allow_ip=True,
                prefer_external=True,
                prefer_cloud=False,
            )
        except NoURLAvailableError:
            return None, URL_SOURCE_NONE
        return f"{base}{webhook.async_generate_path(webhook_id)}", URL_SOURCE_EXTERNAL

    # ------------------------------------------------------------ sessions
    @callback
    def open_session(self, conversation_id: str) -> str | None:
        """Allow calls for this conversation until the TTL; returns expiry."""
        if not self.enabled:
            return None
        expires = _time.time() + self.ttl_seconds
        self.sessions[conversation_id] = expires
        while len(self.sessions) > SESSIONS_LEN:
            self.sessions.pop(next(iter(self.sessions)))
        return dt_util.utc_from_timestamp(expires).isoformat()

    def callback_block(self, conversation_id: str) -> dict[str, Any] | None:
        """The `callback` block for an outgoing payload (None when off)."""
        if not self.enabled or not self.url:
            return None
        expires = self.open_session(conversation_id)
        return {
            "protocol": CALLBACK_PROTOCOL_VERSION,
            "url": self.url,
            "token": self.token,
            "access_level": self.level,
            "allowed_actions": allowed_actions(self.options),
            "expires": expires,
            "conversation_id": conversation_id,
            "token_header": TOKEN_HEADER,
        }

    def _session_open(self, conversation_id: str | None) -> bool:
        if not conversation_id:
            return False
        expires = self.sessions.get(conversation_id)
        return expires is not None and expires > _time.time()

    # ------------------------------------------------------------- webhook
    def _token_ok(self, request: web.Request, body: dict[str, Any]) -> bool:
        supplied = request.headers.get(TOKEN_HEADER) or ""
        auth = request.headers.get("Authorization", "")
        if not supplied and auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        if not supplied:
            supplied = str(body.get("token") or "")
        return (
            bool(supplied)
            and bool(self.token)
            and hmac.compare_digest(supplied.encode(), self.token.encode())
        )

    async def _handle_webhook(
        self, hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
        if not self._token_ok(request, body):
            self._log({"type": "auth", "ok": False, "summary": "invalid token"}, fire=True)
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        result = await self.async_execute(body)
        status = 200 if result.get("results") else 400
        return web.Response(text=self._fit(result), status=status, content_type="application/json")

    def _fit(self, result: dict[str, Any]) -> str:
        """JSON response capped at the configured size."""
        limit = int(self.options[CONF_ACCESS_MAX_RESPONSE]) * 1024
        text = json.dumps(result, default=str, ensure_ascii=False)
        if len(text.encode()) <= limit:
            return text
        result["truncated"] = True
        for item in result.get("results", []):
            value = item.get("result")
            if isinstance(value, list) and len(value) > 5:
                item["result"] = value[:5]
                item["truncated"] = True
            elif isinstance(value, dict):
                for key, sub in list(value.items()):
                    if isinstance(sub, list) and len(sub) > 5:
                        value[key] = sub[:5]
                        item["truncated"] = True
        text = json.dumps(result, default=str, ensure_ascii=False)
        if len(text.encode()) <= limit:
            return text
        return json.dumps(
            {
                "ok": result.get("ok"),
                "truncated": True,
                "error": "response_too_large",
                "results": [
                    {"type": r.get("type"), "ok": r.get("ok"), "error": r.get("error")}
                    for r in result.get("results", [])
                ],
            }
        )

    # ------------------------------------------------------------ execute
    async def async_execute(self, body: dict[str, Any]) -> dict[str, Any]:
        """Run the actions of one inbound request (token already checked)."""
        conversation_id = body.get("conversation_id")
        actions = body.get("actions")
        if actions is None and body.get("message"):
            actions = [{"type": ACT_REPLY, **body}]  # 0.1.0 style reply body
        if not isinstance(actions, list) or not actions:
            return {"ok": False, "error": "no_actions", "results": []}
        if len(actions) > MAX_ACTIONS_PER_REQUEST:
            return {"ok": False, "error": "too_many_actions", "results": []}
        allowed = set(allowed_actions(self.options))
        require_open = bool(self.options[CONF_ACCESS_REQUIRE_PENDING])
        results = []
        for action in actions:
            kind = action.get("type") if isinstance(action, dict) else None
            item: dict[str, Any] = {"type": kind}
            try:
                if kind not in allowed:
                    raise AccessDenied(f"action '{kind}' not allowed at level {self.level}")
                awaiting = conversation_id in self.hub.pending
                if require_open and not (
                    self._session_open(conversation_id) or (kind == ACT_REPLY and awaiting)
                ):
                    raise AccessDenied("conversation not open or expired")
                item["result"] = await self._run(kind, action, conversation_id)
                item["ok"] = True
            except AccessDenied as err:
                item.update(ok=False, error="denied", reason=str(err))
            except (HomeAssistantError, ValueError, KeyError, TypeError) as err:
                item.update(ok=False, error=type(err).__name__, reason=str(err)[:300])
            results.append(item)
            self._audit(conversation_id, action if isinstance(action, dict) else {}, item)
        self.hub.save()
        return {
            "ok": all(r.get("ok") for r in results),
            "access_level": self.level,
            "conversation_id": conversation_id,
            "results": results,
        }

    async def _run(self, kind: str, action: dict[str, Any], cid: str | None) -> Any:
        hass = self.hass
        if kind == ACT_REPLY:
            message = str(action.get("message") or "").strip()
            if not message:
                raise ValueError("message required")
            return await self.hub.async_handle_reply(
                message,
                conversation_id=action.get("conversation_id") or cid,
                title=action.get("title"),
                data=action.get("data") if isinstance(action.get("data"), dict) else None,
                reply_to=action.get("reply_to"),
            )
        if kind == ACT_GET_STATES:
            return self._get_states(action)
        if kind == ACT_GET_HISTORY:
            return await self._get_history(action)
        if kind == ACT_LIST_REPAIRS:
            from .triggers import open_issues

            return open_issues(hass)
        if kind == ACT_GET_LOGS:
            return self._get_logs(action)
        if kind == ACT_LIST_ENTRIES:
            return self._list_entries(action)
        if kind == ACT_CALL_SERVICE:
            return await self._call_service(action)
        if kind == ACT_RELOAD_ENTRY:
            entry = hass.config_entries.async_get_entry(str(action.get("entry_id")))
            if entry is None:
                raise ValueError("entry not found")
            if entry.domain == DOMAIN:
                raise AccessDenied("Grok Bot can't reload itself")
            self._check_entry_entities(entry.entry_id)
            ok = await hass.config_entries.async_reload(entry.entry_id)
            return {"reloaded": ok, "state": entry.state.value}
        if kind == ACT_IGNORE_REPAIR:
            domain, issue_id = str(action.get("domain")), str(action.get("issue_id"))
            if ir.async_get(hass).async_get_issue(domain, issue_id) is None:
                raise ValueError("issue not found")
            ignore = bool(action.get("ignore", True))
            ir.async_ignore_issue(hass, domain, issue_id, ignore)
            return {"domain": domain, "issue_id": issue_id, "ignored": ignore}
        if kind == ACT_ENABLE_ENTITY:
            entity_id = str(action.get("entity_id"))
            self._check_entities([entity_id])
            registry = er.async_get(hass)
            entry = registry.async_get(entity_id)
            if entry is None:
                raise ValueError("entity not found")
            if entry.disabled_by is None:
                return {"entity_id": entity_id, "enabled": True, "changed": False}
            registry.async_update_entity(entity_id, disabled_by=None)
            return {"entity_id": entity_id, "enabled": True, "changed": True}
        raise AccessDenied(f"unknown action '{kind}'")

    # -------------------------------------------------------------- reads
    def _get_states(self, action: dict[str, Any]) -> list[dict[str, Any]]:
        entity_ids = _ids(action.get("entity_ids") or action.get("entity_id"))
        domains = set(_ids(action.get("domains") or action.get("domain")))
        limit = min(int(action.get("limit", 200)), 1000)
        include_attrs = bool(action.get("attributes", bool(entity_ids)))
        if entity_ids:
            states = [s for e in entity_ids if (s := self.hass.states.get(e))]
        else:
            states = [s for s in self.hass.states.async_all() if not domains or s.domain in domains]
        if only := action.get("state"):
            wanted = set(_ids(only))
            states = [s for s in states if s.state in wanted]
        out = []
        for state in states[:limit]:
            item = {
                "entity_id": state.entity_id,
                "state": state.state,
                "name": state.name,
                "last_changed": state.last_changed.isoformat(),
            }
            if include_attrs:
                item["attributes"] = dict(state.attributes)
            out.append(item)
        return out

    async def _get_history(self, action: dict[str, Any]) -> dict[str, Any]:
        entity_ids = _ids(action.get("entity_ids") or action.get("entity_id"))[:10]
        if not entity_ids:
            raise ValueError("entity_ids required")
        hours = max(0.1, min(float(action.get("hours", 6)), 48))
        if "recorder" not in self.hass.config.components:
            raise HomeAssistantError("recorder not loaded")
        from homeassistant.components.recorder import get_instance, history

        start = dt_util.utcnow() - timedelta(hours=hours)
        raw = await get_instance(self.hass).async_add_executor_job(
            history.get_significant_states,
            self.hass,
            start,
            None,
            entity_ids,
            None,
            True,
            True,
            False,
            True,
        )
        return {entity_id: summarize_history(states) for entity_id, states in raw.items()}

    def _get_logs(self, action: dict[str, Any]) -> list[dict[str, Any]]:
        level = str(action.get("level", "WARNING")).upper()
        rank = logging.getLevelName(level) if level in ("WARNING", "ERROR", "CRITICAL") else 30
        limit = min(int(action.get("limit", 30)), 100)
        handler = self.hass.data.get("system_log")
        records: list[dict[str, Any]] = []
        if handler is not None and hasattr(handler, "records"):
            records = handler.records.to_list()
        else:
            records = list(reversed(self.hub.recent_errors))
        out = []
        for rec in records:
            if logging.getLevelName(str(rec.get("level", "WARNING"))) < rank:
                continue
            msg = rec.get("message")
            out.append(
                {
                    "name": rec.get("name") or rec.get("logger"),
                    "level": rec.get("level"),
                    "message": (msg if isinstance(msg, list) else [msg])[:3],
                    "source": rec.get("source"),
                    "count": rec.get("count"),
                    "exception": (rec.get("exception") or "")[-1500:] or None,
                }
            )
            if len(out) >= limit:
                break
        return out

    def _list_entries(self, action: dict[str, Any]) -> list[dict[str, Any]]:
        domain = action.get("domain")
        problems_only = bool(action.get("problems_only", False))
        out = []
        for entry in self.hass.config_entries.async_entries():
            if domain and entry.domain != domain:
                continue
            if problems_only and entry.state not in (
                ConfigEntryState.SETUP_ERROR,
                ConfigEntryState.SETUP_RETRY,
                ConfigEntryState.FAILED_UNLOAD,
                ConfigEntryState.MIGRATION_ERROR,
            ):
                continue
            out.append(
                {
                    "entry_id": entry.entry_id,
                    "domain": entry.domain,
                    "title": entry.title,
                    "state": entry.state.value,
                    "reason": entry.reason,
                    "disabled_by": entry.disabled_by,
                }
            )
        return out

    # ------------------------------------------------------------- control
    def _check_entities(self, entity_ids: list[str]) -> None:
        allow = set(self.options[CONF_ACCESS_ENTITIES] or [])
        if allow and (not entity_ids or any(e not in allow for e in entity_ids)):
            raise AccessDenied("entity not in the access allowlist")

    def _check_entry_entities(self, entry_id: str) -> None:
        allow = set(self.options[CONF_ACCESS_ENTITIES] or [])
        if not allow:
            return
        entry_entities = {
            e.entity_id
            for e in er.async_entries_for_config_entry(er.async_get(self.hass), entry_id)
        }
        if not entry_entities & allow:
            raise AccessDenied("integration has no allowlisted entities")

    async def _call_service(self, action: dict[str, Any]) -> dict[str, Any]:
        domain = str(action.get("domain") or "")
        service = str(action.get("service") or "")
        if "." in domain and not service:
            domain, service = domain.split(".", 1)
        if not domain or not service:
            raise ValueError("domain and service required")
        if service_blocked(domain, service):
            raise AccessDenied(f"{domain}.{service} is always blocked")
        allow_domains = set(self.options[CONF_ACCESS_DOMAINS] or [])
        if allow_domains and domain not in allow_domains:
            raise AccessDenied(f"domain '{domain}' not in the access allowlist")
        if not self.hass.services.has_service(domain, service):
            raise ValueError(f"service {domain}.{service} not found")
        data = dict(action.get("data") or {})
        target = dict(action.get("target") or {})
        entity_ids = _ids(target.get("entity_id")) + _ids(data.get("entity_id"))
        wide = any(
            target.get(k) or data.get(k) for k in ("device_id", "area_id", "label_id", "floor_id")
        )
        if self.options[CONF_ACCESS_ENTITIES]:
            if wide:
                raise AccessDenied("only entity_id targets are allowed with an entity allowlist")
            self._check_entities(entity_ids)
        supports = self.hass.services.supports_response(domain, service)
        return_response = supports is SupportsResponse.ONLY or (
            supports is SupportsResponse.OPTIONAL and bool(action.get("return_response", False))
        )
        response = await self.hass.services.async_call(
            domain,
            service,
            {**data, **target},
            blocking=True,
            context=Context(),
            return_response=return_response,
        )
        return {"called": f"{domain}.{service}", "response": response}

    # --------------------------------------------------------------- audit
    def _audit(self, cid: str | None, action: dict[str, Any], item: dict[str, Any]) -> None:
        kind = item.get("type")
        summary = str(kind)
        if kind == ACT_CALL_SERVICE:
            target = action.get("target") or {}
            summary = f"{action.get('domain')}.{action.get('service')} {target.get('entity_id', '')}".strip()
        elif kind == ACT_RELOAD_ENTRY:
            summary = f"reload {action.get('entry_id')}"
        elif kind == ACT_IGNORE_REPAIR:
            summary = f"ignore {action.get('domain')}.{action.get('issue_id')}"
        elif kind == ACT_ENABLE_ENTITY:
            summary = f"enable {action.get('entity_id')}"
        record = {
            "conversation_id": cid,
            "type": kind,
            "ok": bool(item.get("ok")),
            "summary": summary[:200],
            "error": item.get("reason"),
        }
        changes = kind in (ACT_CALL_SERVICE, *FIX_ACTIONS)
        self._log(record, fire=True, notify=changes and record["ok"])

    @callback
    def _log(self, record: dict[str, Any], fire: bool = False, notify: bool = False) -> None:
        record = {"time": dt_util.utcnow().isoformat(), **record}
        self.audit.append(record)
        if fire:
            self.hass.bus.async_fire(
                EVENT_ACTION, {"config_entry_id": self.hub.entry.entry_id, **record}
            )
        if notify and self.options[CONF_ACCESS_NOTIFY]:
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": "Grok Bot action",
                        "message": f"Grok Bot ran: {record['summary']}",
                        "notification_id": f"{DOMAIN}_action_{int(_time.time())}",
                    },
                )
            )
        self.hub.save()
        self.hub.notify()


def summarize_history(states: list[Any]) -> dict[str, Any]:
    """Small summary of a state list: counts, numeric min/max and last changes."""
    values = []
    for st in states:
        if isinstance(st, dict):
            values.append((st.get("s") or st.get("state"), st.get("lu") or st.get("last_changed")))
        else:
            values.append((st.state, st.last_changed.isoformat()))
    nums = []
    for value, _ in values:
        try:
            nums.append(float(value))
        except (TypeError, ValueError):
            continue
    summary: dict[str, Any] = {
        "changes": len(values),
        "first": values[0][0] if values else None,
        "last": values[-1][0] if values else None,
        "recent": [{"state": v, "time": t} for v, t in values[-20:]],
    }
    if nums:
        summary.update(min=min(nums), max=max(nums), avg=round(sum(nums) / len(nums), 3))
    return summary
