"""Grok Bot hub: budget, gating, payload building, delivery and replies."""

from __future__ import annotations

from collections import deque
from datetime import datetime, time, timedelta
import json
import logging
import time as _time
from typing import Any
import uuid

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.storage import Store
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util

from .api import GrokBotClient
from .const import (
    ACTION_FIX,
    ACTION_REPORT,
    CONF_ACCESS_METHOD,
    CONF_ENABLE_INBOUND_WEBHOOK,
    CONF_INCLUDE_ATTRIBUTES,
    CONF_MAX_PAYLOAD,
    CONF_MAX_PER_DAY,
    CONF_MAX_PER_HOUR,
    CONF_QUIET_END,
    CONF_QUIET_HOURS,
    CONF_QUIET_START,
    CONF_REPLY_TIMEOUT,
    CONF_WEBHOOK_URL,
    DEFAULT_OPTIONS,
    DOMAIN,
    EVENT_DROPPED,
    EVENT_FAILED,
    EVENT_REPLY,
    EVENT_SENT,
    INTEGRATION_VERSION,
    MAX_MESSAGE_LEN,
    MAX_STATE_LEN,
    METHOD_MCP,
    METHOD_NONE,
    METHOD_WEBHOOK,
    PAYLOAD_SCHEMA_VERSION,
    SERVICE_REPLY,
    SIGNAL_CONNECTED,
    SIGNAL_UPDATE,
    STATUS_ANSWERED_ELSEWHERE,
    STATUS_AUTH_FAILED,
    STATUS_DROPPED_BUDGET,
    STATUS_DROPPED_PAUSED,
    STATUS_DROPPED_QUIET,
    STATUS_DROPPED_TOO_LARGE,
    STATUS_FAILED,
    STATUS_IDLE,
    STATUS_SENT,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
HISTORY_LEN = 20
PENDING_LEN = 50
HOUR = 3600
DAY = 86400


def options_of(entry: ConfigEntry) -> dict[str, Any]:
    """Entry options merged over the defaults (0.1.0 options migrated)."""
    opts = {**DEFAULT_OPTIONS, **entry.options}
    if entry.options.get(CONF_ENABLE_INBOUND_WEBHOOK) and (CONF_ACCESS_METHOD not in entry.options):
        opts[CONF_ACCESS_METHOD] = METHOD_WEBHOOK
    return opts


def _parse_time(value: Any) -> time | None:
    if isinstance(value, time):
        return value
    try:
        return time.fromisoformat(str(value))
    except ValueError:
        return None


def in_quiet_hours(now: datetime, start: Any, end: Any) -> bool:
    """True when local `now` falls in [start, end) (may wrap midnight)."""
    start_t, end_t = _parse_time(start), _parse_time(end)
    if start_t is None or end_t is None or start_t == end_t:
        return False
    current = now.time()
    if start_t < end_t:
        return start_t <= current < end_t
    return current >= start_t or current < end_t


def state_snapshot(state: State | None, include_attributes: bool) -> dict | None:
    """JSON-friendly snapshot of an entity state."""
    if state is None:
        return None
    snap: dict[str, Any] = {
        "entity_id": state.entity_id,
        "state": state.state,
        "name": state.name,
        "last_changed": state.last_changed.isoformat(),
    }
    if include_attributes:
        snap["attributes"] = {k: v for k, v in state.attributes.items() if k != "entity_picture"}
    return snap


class SendBudget:
    """Rolling 1 h / 24 h counters of sends (persisted)."""

    def __init__(self, sends: list[float] | None = None) -> None:
        self._sends: deque[float] = deque(sorted(sends or []))

    def prune(self, now: float | None = None) -> None:
        now = _time.time() if now is None else now
        while self._sends and self._sends[0] <= now - DAY:
            self._sends.popleft()

    def count(self, window: int, now: float | None = None) -> int:
        now = _time.time() if now is None else now
        self.prune(now)
        return sum(1 for ts in self._sends if ts > now - window)

    def allowed(self, max_hour: int, max_day: int, now: float | None = None) -> bool:
        return self.count(HOUR, now) < max_hour and self.count(DAY, now) < max_day

    def record(self, now: float | None = None) -> None:
        self._sends.append(_time.time() if now is None else now)

    def reset(self) -> None:
        self._sends.clear()

    def as_list(self) -> list[float]:
        return list(self._sends)


class GrokBotHub:
    """Everything one config entry needs at runtime."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: GrokBotClient) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self.budget = SendBudget()
        self.paused = False
        self.stats: dict[str, int] = {"sent": 0, "failed": 0, "dropped": 0}
        self.last_sent: datetime | None = None
        self.last_status: str = STATUS_IDLE
        self.last_error: str | None = None
        self.last_reply: dict[str, Any] | None = None
        self.history: deque[dict[str, Any]] = deque(maxlen=HISTORY_LEN)
        self.pending: dict[str, dict[str, Any]] = {}
        self.connected = False
        self.recent_errors: deque[dict[str, Any]] = deque(maxlen=25)
        self._unsubs: list = []
        self._last_drop_log = 0.0
        from .access import AccessManager

        self.access = AccessManager(hass, self)
        from .trusted import TrustedManager

        self.trusted = TrustedManager(hass, self)

    # ----------------------------------------------------------------- setup
    @property
    def options(self) -> dict[str, Any]:
        return options_of(self.entry)

    @property
    def signal(self) -> str:
        return SIGNAL_UPDATE.format(self.entry.entry_id)

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.budget = SendBudget(data.get("sends"))
        self.paused = bool(data.get("paused", False))
        self.stats.update(data.get("stats", {}))
        self.last_reply = data.get("last_reply")
        self.history.extend(data.get("history", [])[-HISTORY_LEN:])
        if ts := data.get("last_sent"):
            self.last_sent = dt_util.parse_datetime(ts)
        self.last_status = data.get("last_status", STATUS_IDLE)
        self.connected = bool(data.get("connected", False))
        self.access.load(data)
        self.trusted.load(data)
        self.trusted.update_issue()
        self._unsubs.append(
            async_track_time_interval(self.hass, self._async_tick, timedelta(minutes=1))
        )

    @callback
    def _async_tick(self, _now: datetime) -> None:
        """Roll the budget window and expire replies that happened elsewhere."""
        self.budget.prune()
        self.trusted.async_tick()
        self.async_expire_pending()
        self._notify()

    @callback
    def async_expire_pending(self, now: float | None = None) -> int:
        """Treat conversations older than the reply timeout as answered in the app."""
        timeout = float(self.options[CONF_REPLY_TIMEOUT]) * 60
        if timeout <= 0:
            return 0
        now = _time.time() if now is None else now
        stale = [
            cid
            for cid, item in self.pending.items()
            if now - float(item.get("created", now)) >= timeout
        ]
        return self._mark_handled(stale)

    @callback
    def async_mark_all_handled(self) -> int:
        """Button: every awaiting conversation was answered in the Grok Bot app."""
        return self._mark_handled(list(self.pending))

    def _mark_handled(self, cids: list[str]) -> int:
        for cid in cids:
            self.pending.pop(cid, None)
        if cids:
            self.last_status = STATUS_ANSWERED_ELSEWHERE
            self._save()
            self._notify()
        return len(cids)

    # ------------------------------------------------------------- access
    def mcp_info(self) -> dict[str, Any]:
        """HA-MCP (preferred) or core MCP Server detection, see mcp.py."""
        from .mcp import detect_mcp

        return detect_mcp(self.hass, self.external_url())

    @property
    def mcp_ready(self) -> bool:
        return bool(self.mcp_info()["ready"])

    def setup_prompt(self, language: str | None = None) -> str:
        from .prompt import setup_prompt

        info = self.mcp_info()
        hint = info["connector_url_hint"] if info["provider"] == "ha_mcp" else None
        return setup_prompt(
            self.hass,
            webhook_url=self.entry.data[CONF_WEBHOOK_URL],
            mcp_url=hint,
            language=language,
        )

    def external_url(self) -> str | None:
        try:
            return get_url(self.hass, allow_internal=False, allow_ip=True, prefer_external=True)
        except NoURLAvailableError:
            return None

    def access_info(self) -> dict[str, Any]:
        """The `access` block: how Grok Bot can reach back into this instance."""
        from .access import access_method

        method = access_method(self.options)
        external = self.external_url()
        mcp = self.mcp_info()
        if (method == METHOD_WEBHOOK and not self.access.url) or (
            method == METHOD_MCP and not mcp["ready"]
        ):
            method_live = METHOD_NONE
        else:
            method_live = method
        return {
            "method": method_live,
            "configured_method": method,
            "mcp_ready": mcp["ready"],
            "mcp_provider": mcp["provider"],
            "connector_url_hint": mcp["connector_url_hint"],
            "ha_instance": {
                "name": self.hass.config.location_name,
                "external_url": external,
                "config_entry_id": self.entry.entry_id,
            },
        }

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "sends": self.budget.as_list(),
            "paused": self.paused,
            "stats": self.stats,
            "last_reply": self.last_reply,
            "history": list(self.history),
            "last_sent": self.last_sent.isoformat() if self.last_sent else None,
            "last_status": self.last_status,
            "connected": self.connected,
            **self.access.to_store(),
            **self.trusted.to_store(),
        }

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(self._data_to_save, 5)

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._data_to_save())

    @callback
    def _notify(self) -> None:
        async_dispatcher_send(self.hass, self.signal)

    save = _save
    notify = _notify

    # ---------------------------------------------------------------- budget
    @property
    def sends_hour(self) -> int:
        return self.budget.count(HOUR)

    @property
    def sends_day(self) -> int:
        return self.budget.count(DAY)

    @property
    def max_hour(self) -> int:
        return int(self.options[CONF_MAX_PER_HOUR])

    @property
    def max_day(self) -> int:
        return int(self.options[CONF_MAX_PER_DAY])

    @callback
    def async_set_paused(self, paused: bool) -> None:
        self.paused = paused
        self._save()
        self._notify()

    @callback
    def async_reset_budget(self) -> None:
        self.budget.reset()
        self._save()
        self._notify()

    # -------------------------------------------------------------- payloads
    @callback
    def render_template(self, template: str | None, variables: dict[str, Any], default: str) -> str:
        """Render an optional user template; fall back to `default`."""
        if not template:
            return default
        try:
            rendered = Template(template, self.hass).async_render(variables, parse_result=False)
        except TemplateError as err:
            _LOGGER.debug("Grok Bot message template failed: %s", err)
            return default
        return str(rendered).strip() or default

    def _context(self, entity_ids: list[str] | None) -> list[dict]:
        include = bool(self.options[CONF_INCLUDE_ATTRIBUTES])
        out = []
        for entity_id in entity_ids or []:
            snap = state_snapshot(self.hass.states.get(entity_id), include)
            out.append(snap or {"entity_id": entity_id, "state": None})
        return out

    def build_payload(
        self,
        kind: str,
        message: str,
        *,
        source: str,
        context: list[dict] | None = None,
        reply_to: str | None = None,
        conversation_id: str | None = None,
        notify_user: bool = False,
        action_mode: str = ACTION_REPORT,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """The JSON document posted to the Grok Bot webhook (see README)."""
        payload = {
            "schema": PAYLOAD_SCHEMA_VERSION,
            "type": kind,
            "message": (message or "")[:MAX_MESSAGE_LEN],
            "source": source,
            "context": context or [],
            "reply_to": reply_to,
            "conversation_id": conversation_id,
            "notify_user": notify_user,
            "action_mode": action_mode,
            "allow_fix": action_mode == ACTION_FIX,
            "data": data or {},
            "timestamp": dt_util.utcnow().isoformat(),
            "ha_instance": {
                "name": self.hass.config.location_name,
                "version": HA_VERSION,
                "integration_version": INTEGRATION_VERSION,
                "config_entry_id": self.entry.entry_id,
                "time_zone": str(self.hass.config.time_zone),
            },
            "reply_with": {
                "service": f"{DOMAIN}.{SERVICE_REPLY}",
                "data": {
                    "config_entry_id": self.entry.entry_id,
                    "conversation_id": conversation_id,
                    "message": "<your answer>",
                },
            },
        }
        payload["access"] = self.access_info()
        if trusted := self.trusted.payload_block(action_mode, action_mode == ACTION_FIX):
            payload["access"].update(trusted)
        if conversation_id and (cb := self.access.callback_block(conversation_id)):
            payload["callback"] = cb
        return payload

    @staticmethod
    def _size(payload: dict) -> int:
        return len(json.dumps(payload, default=str, ensure_ascii=False).encode())

    def fit_payload(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Shrink a payload to the size limit, or None when impossible."""
        limit = int(self.options[CONF_MAX_PAYLOAD])
        if self._size(payload) <= limit:
            return payload
        payload["truncated"] = True
        for ctx in payload["context"]:
            ctx.pop("attributes", None)
        if self._size(payload) <= limit:
            return payload
        for key in ("traceback", "event_data", "attributes"):
            payload["data"].pop(key, None)
        if self._size(payload) <= limit:
            return payload
        payload["context"] = [
            {"entity_id": c.get("entity_id"), "state": c.get("state")} for c in payload["context"]
        ]
        while self._size(payload) > limit and len(payload["message"]) > 200:
            payload["message"] = payload["message"][: len(payload["message"]) // 2]
        return payload if self._size(payload) <= limit else None

    # --------------------------------------------------------------- sending
    async def async_send(
        self,
        kind: str,
        message: str,
        *,
        source: str,
        context_entities: list[str] | None = None,
        reply_to: str | None = None,
        conversation_id: str | None = None,
        notify_user: bool = False,
        action_mode: str = ACTION_REPORT,
        data: dict[str, Any] | None = None,
        automatic: bool = False,
        bypass_budget: bool = False,
    ) -> dict[str, Any]:
        """Gate, build and deliver one payload. Never queues, never retries."""
        conversation_id = conversation_id or uuid.uuid4().hex
        result: dict[str, Any] = {"conversation_id": conversation_id, "type": kind}
        opts = self.options

        if self.paused:
            return self._drop(result, STATUS_DROPPED_PAUSED, source)
        if (
            automatic
            and opts[CONF_QUIET_HOURS]
            and in_quiet_hours(dt_util.now(), opts[CONF_QUIET_START], opts[CONF_QUIET_END])
        ):
            return self._drop(result, STATUS_DROPPED_QUIET, source)
        if (automatic or not bypass_budget) and not self.budget.allowed(
            self.max_hour, self.max_day
        ):
            return self._drop(result, STATUS_DROPPED_BUDGET, source)

        payload = self.fit_payload(
            self.build_payload(
                kind,
                message,
                source=source,
                context=self._context(context_entities),
                reply_to=reply_to,
                conversation_id=conversation_id,
                notify_user=notify_user,
                action_mode=action_mode,
                data=data,
            )
        )
        if payload is None:
            return self._drop(result, STATUS_DROPPED_TOO_LARGE, source)

        self.budget.record()
        delivery = await self.client.async_post(payload)
        self.last_sent = dt_util.utcnow()
        result["http_status"] = delivery.http_status
        self._remember(
            {
                "direction": "out",
                "type": kind,
                "source": source,
                "message": payload["message"][:MAX_STATE_LEN],
                "conversation_id": conversation_id,
                "time": self.last_sent.isoformat(),
            }
        )
        if delivery.ok:
            self.stats["sent"] += 1
            self.last_status = STATUS_SENT
            self.last_error = None
            self.pending[conversation_id] = {
                "reply_to": reply_to,
                "type": kind,
                "created": _time.time(),
            }
            while len(self.pending) > PENDING_LEN:
                self.pending.pop(next(iter(self.pending)))
            self.hass.bus.async_fire(
                EVENT_SENT,
                {
                    "config_entry_id": self.entry.entry_id,
                    "type": kind,
                    "source": source,
                    "conversation_id": conversation_id,
                },
            )
        else:
            self.stats["failed"] += 1
            self.last_status = STATUS_AUTH_FAILED if delivery.auth_failed else STATUS_FAILED
            self.last_error = delivery.error
            _LOGGER.debug("Grok Bot delivery failed: %s", delivery.error)
            self.hass.bus.async_fire(
                EVENT_FAILED,
                {
                    "config_entry_id": self.entry.entry_id,
                    "type": kind,
                    "error": delivery.error,
                    "conversation_id": conversation_id,
                },
            )
            if delivery.auth_failed:
                self.entry.async_start_reauth(self.hass)
        result["status"] = self.last_status
        result.update(self._budget_info())
        self._save()
        self._notify()
        return result

    def _budget_info(self) -> dict[str, int]:
        return {
            "sends_last_hour": self.sends_hour,
            "sends_last_24h": self.sends_day,
            "remaining_last_hour": max(0, self.max_hour - self.sends_hour),
            "remaining_last_24h": max(0, self.max_day - self.sends_day),
        }

    def _drop(self, result: dict[str, Any], reason: str, source: str) -> dict:
        self.stats["dropped"] += 1
        self.last_status = reason
        now = _time.monotonic()
        if now - self._last_drop_log > HOUR:
            # Info, not warning: our own warnings must never feed the log watcher.
            _LOGGER.info(
                "Grok Bot send dropped (%s); further drops are logged at debug level for an hour",
                reason,
            )
            self._last_drop_log = now
        else:
            _LOGGER.debug("Grok Bot send dropped (%s) from %s", reason, source)
        self.hass.bus.async_fire(
            EVENT_DROPPED,
            {
                "config_entry_id": self.entry.entry_id,
                "reason": reason,
                "type": result["type"],
                "source": source,
            },
        )
        result["status"] = reason
        result.update(self._budget_info())
        self._save()
        self._notify()
        return result

    def _remember(self, item: dict[str, Any]) -> None:
        self.history.append(item)

    # --------------------------------------------------------------- replies
    async def async_handle_reply(
        self,
        message: str,
        *,
        conversation_id: str | None = None,
        title: str | None = None,
        data: dict[str, Any] | None = None,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        """A reply from Grok Bot (via grok_bot.reply or the inbound webhook)."""
        pending = self.pending.pop(conversation_id or "", None) or {}
        if not self.connected:
            self.connected = True
            async_dispatcher_send(self.hass, SIGNAL_CONNECTED, self.entry.entry_id)
        target = reply_to or pending.get("reply_to")
        now = dt_util.utcnow().isoformat()
        self.last_reply = {
            "message": message,
            "title": title,
            "conversation_id": conversation_id,
            "received": now,
            "data": data or {},
        }
        self._remember(
            {
                "direction": "in",
                "type": "reply",
                "message": message[:MAX_STATE_LEN],
                "title": title,
                "conversation_id": conversation_id,
                "time": now,
            }
        )
        self.hass.bus.async_fire(
            EVENT_REPLY,
            {
                "config_entry_id": self.entry.entry_id,
                "message": message,
                "title": title,
                "conversation_id": conversation_id,
                "reply_to": target,
                "data": data or {},
            },
        )
        delivered = await self._deliver_reply(target, message, title)
        self._save()
        self._notify()
        return {"delivered_to": target if delivered else None}

    async def _deliver_reply(self, target: str | None, message: str, title: str | None) -> bool:
        if not target or "." not in target:
            return False
        domain, name = target.split(".", 1)
        services = self.hass.services
        if target.startswith(f"notify.{DOMAIN}"):
            return False  # never loop a reply back to Grok Bot itself
        if domain == "input_text" and self.hass.states.get(target):
            max_len = int(self.hass.states.get(target).attributes.get("max", MAX_STATE_LEN))
            await services.async_call(
                "input_text",
                "set_value",
                {"entity_id": target, "value": message[:max_len]},
                blocking=True,
            )
            return True
        if domain == "notify" and self.hass.states.get(target):
            await services.async_call(
                "notify",
                "send_message",
                {"entity_id": target, "message": message, "title": title},
                blocking=True,
            )
            return True
        if domain == "notify" and services.has_service("notify", name):
            payload = {"message": message}
            if title:
                payload["title"] = title
            await services.async_call("notify", name, payload, blocking=True)
            return True
        if target == "persistent_notification.create" or domain == ("persistent_notification"):
            await services.async_call(
                "persistent_notification",
                "create",
                {"message": message, "title": title or "Grok Bot"},
                blocking=True,
            )
            return True
        _LOGGER.debug("Grok Bot reply target %s not found", target)
        return False
