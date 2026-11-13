"""Opt-in automatic triggers: state/event forwarding and problem watchers.

Nothing here is active unless the user picked it in the options flow, and every
send goes through the hub's budget, pause switch and quiet hours.
"""

from __future__ import annotations

import contextlib
import logging
import time as _time
import traceback
from typing import Any

from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntry,
    ConfigEntryChange,
    ConfigEntryState,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)

from .const import (
    BLOCKED_EVENT_TYPES,
    CONF_AUTOMATIONS_ACTION,
    CONF_EVENT_ACTION,
    CONF_FILTERS,
    CONF_FORWARD_ENTITIES,
    CONF_FORWARD_EVENTS,
    CONF_IGNORE_UNAVAILABLE,
    CONF_LOG_ACTION,
    CONF_LOG_DEDUPE,
    CONF_LOG_LEVEL,
    CONF_LOG_LOGGER_MODE,
    CONF_LOG_LOGGERS,
    CONF_MIN_INTERVAL,
    CONF_REPAIRS_ACTION,
    CONF_SETUP_ACTION,
    CONF_STATE_ACTION,
    CONF_TEMPLATE_EVENT,
    CONF_TEMPLATE_ISSUE,
    CONF_TEMPLATE_STATE,
    CONF_UNAVAILABLE_ACTION,
    CONF_UNAVAILABLE_MINUTES,
    CONF_WATCH_AUTOMATIONS,
    CONF_WATCH_LOGS,
    CONF_WATCH_REPAIRS,
    CONF_WATCH_SETUP,
    CONF_WATCH_UNAVAILABLE,
    DOMAIN,
    FILTER_ABOVE,
    FILTER_ATTRIBUTE,
    FILTER_BELOW,
    FILTER_MIN_INTERVAL,
    FILTER_TO_STATES,
    LOGGER_MODE_ALLOW,
    LOGGER_MODE_DENY,
    STATUS_DROPPED_COOLDOWN,
)
from .hub import GrokBotHub

_LOGGER = logging.getLogger(__name__)
_OWN_LOGGERS = (f"custom_components.{DOMAIN}", f"homeassistant.components.{DOMAIN}")
_AUTOMATION_LOGGERS = (
    "homeassistant.components.automation",
    "homeassistant.components.script",
)
_SETUP_LOGGERS = ("homeassistant.setup", "homeassistant.config_entries")
_BAD_STATES = (STATE_UNAVAILABLE, STATE_UNKNOWN)


def event_type_allowed(event_type: str) -> bool:
    """Event types that may be forwarded (no loops, no floods)."""
    event_type = (event_type or "").strip()
    return bool(event_type) and not (
        event_type in BLOCKED_EVENT_TYPES or event_type.startswith(DOMAIN)
    )


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def state_passes_filter(
    old: State | None, new: State, rule: dict[str, Any], ignore_unavailable: bool
) -> bool:
    """Decide whether a state change of an allowlisted entity is forwarded."""
    if ignore_unavailable and new.state in _BAD_STATES:
        return False
    attribute = (rule.get(FILTER_ATTRIBUTE) or "").strip()
    to_states = [str(s) for s in rule.get(FILTER_TO_STATES) or []]
    above, below = _num(rule.get(FILTER_ABOVE)), _num(rule.get(FILTER_BELOW))

    def value_of(state: State | None) -> Any:
        if state is None:
            return None
        return state.attributes.get(attribute) if attribute else state.state

    new_value, old_value = value_of(new), value_of(old)
    if new_value == old_value:
        return False  # attribute-only noise / nothing relevant changed
    if to_states and str(new_value) not in to_states:
        return False
    if above is None and below is None:
        return True

    def in_range(value: Any) -> bool:
        num = _num(value)
        if num is None:
            return False
        return (above is None or num > above) and (below is None or num < below)

    # Threshold rules fire on crossing into the range, not on every change.
    return in_range(new_value) and not in_range(old_value)


class TriggerManager:
    """Owns every automatic listener of one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, hub: GrokBotHub):
        self.hass = hass
        self.entry = entry
        self.hub = hub
        self._unsubs: list[CALLBACK_TYPE] = []
        self._cooldown: dict[str, float] = {}
        self._unavailable_timers: dict[str, CALLBACK_TYPE] = {}
        self._dedupe: dict[str, list[float | int]] = {}
        self._log_handler: _GrokBotLogHandler | None = None

    @property
    def opts(self) -> dict[str, Any]:
        return self.hub.options

    # ------------------------------------------------------------ lifecycle
    @callback
    def async_start(self) -> None:
        opts = self.opts
        if entities := opts[CONF_FORWARD_ENTITIES]:
            self._unsubs.append(async_track_state_change_event(self.hass, entities, self._on_state))
        for event_type in opts[CONF_FORWARD_EVENTS]:
            if event_type_allowed(event_type):
                self._unsubs.append(self.hass.bus.async_listen(event_type, self._on_event))
        if watched := opts[CONF_WATCH_UNAVAILABLE]:
            self._unsubs.append(
                async_track_state_change_event(self.hass, watched, self._on_unavailable_change)
            )
            for entity_id in watched:
                state = self.hass.states.get(entity_id)
                if state and state.state in _BAD_STATES:
                    self._arm_unavailable(entity_id)
        if opts[CONF_WATCH_REPAIRS]:
            self._unsubs.append(
                self.hass.bus.async_listen(ir.EVENT_REPAIRS_ISSUE_REGISTRY_UPDATED, self._on_repair)
            )
        if opts[CONF_WATCH_SETUP]:
            self._unsubs.append(
                async_dispatcher_connect(
                    self.hass, SIGNAL_CONFIG_ENTRY_CHANGED, self._on_entry_changed
                )
            )
        if opts[CONF_WATCH_LOGS] or opts[CONF_WATCH_AUTOMATIONS] or opts[CONF_WATCH_SETUP]:
            self._log_handler = _GrokBotLogHandler(self)
            logging.getLogger().addHandler(self._log_handler)

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for cancel in self._unavailable_timers.values():
            cancel()
        self._unavailable_timers.clear()
        if self._log_handler:
            logging.getLogger().removeHandler(self._log_handler)
            self._log_handler = None

    # -------------------------------------------------------------- helpers
    def _cooling_down(self, key: str, interval: float) -> bool:
        now = _time.monotonic()
        last = self._cooldown.get(key)
        if last is not None and now - last < interval:
            return True
        self._cooldown[key] = now
        return False

    def _dedupe_hit(self, key: str) -> int | None:
        """None if within the dedupe window, else the suppressed repeat count."""
        window = float(self.opts[CONF_LOG_DEDUPE])
        now = _time.monotonic()
        seen = self._dedupe.get(key)
        if seen is not None and now - seen[0] < window:
            seen[1] += 1
            return None
        repeats = int(seen[1]) if seen else 0
        self._dedupe[key] = [now, 0]
        if len(self._dedupe) > 500:
            self._dedupe.pop(next(iter(self._dedupe)))
        return repeats

    def _send(self, kind: str, message: str, **kwargs: Any) -> None:
        self.entry.async_create_background_task(
            self.hass,
            self.hub.async_send(kind, message, automatic=True, **kwargs),
            f"{DOMAIN}_{kind}",
        )

    # --------------------------------------------------------- state / event
    @callback
    def _on_state(self, event: Event) -> None:
        new: State | None = event.data["new_state"]
        old: State | None = event.data["old_state"]
        if new is None:
            return
        rule = self.opts[CONF_FILTERS].get(new.entity_id, {})
        if not state_passes_filter(old, new, rule, self.opts[CONF_IGNORE_UNAVAILABLE]):
            return
        interval = float(rule.get(FILTER_MIN_INTERVAL) or self.opts[CONF_MIN_INTERVAL])
        if self._cooling_down(f"state:{new.entity_id}", interval):
            self.hub.stats["dropped"] += 1
            self.hass.bus.async_fire(
                f"{DOMAIN}_dropped",
                {
                    "config_entry_id": self.entry.entry_id,
                    "reason": STATUS_DROPPED_COOLDOWN,
                    "type": "state_changed",
                    "source": new.entity_id,
                },
            )
            return
        default = (
            f"{new.name} ({new.entity_id}) changed from "
            f"{old.state if old else 'none'} to {new.state}."
        )
        variables = {
            "entity_id": new.entity_id,
            "from_state": old,
            "to_state": new,
            "trigger": {"platform": "state", "entity_id": new.entity_id},
        }
        message = self.hub.render_template(self.opts[CONF_TEMPLATE_STATE], variables, default)
        self._send(
            "state_changed",
            message,
            source=new.entity_id,
            context_entities=[new.entity_id],
            action_mode=self.opts[CONF_STATE_ACTION],
            data={
                "entity_id": new.entity_id,
                "from_state": old.state if old else None,
                "to_state": new.state,
                "rule": rule,
            },
        )

    @callback
    def _on_event(self, event: Event) -> None:
        if self._cooling_down(f"event:{event.event_type}", float(self.opts[CONF_MIN_INTERVAL])):
            return
        event_data = dict(event.data)
        default = f"Home Assistant event {event.event_type} fired."
        message = self.hub.render_template(
            self.opts[CONF_TEMPLATE_EVENT],
            {
                "event_type": event.event_type,
                "event_data": event_data,
                "trigger": {"platform": "event", "event": event_data},
            },
            default,
        )
        self._send(
            "event",
            message,
            source=event.event_type,
            action_mode=self.opts[CONF_EVENT_ACTION],
            data={"event_type": event.event_type, "event_data": event_data},
        )

    # ------------------------------------------------------- problem types
    def _issue_message(self, kind: str, default: str, info: dict[str, Any]) -> str:
        return self.hub.render_template(
            self.opts[CONF_TEMPLATE_ISSUE],
            {"kind": kind, "issue": info, "trigger": {"platform": kind, **info}},
            default,
        )

    @callback
    def _on_unavailable_change(self, event: Event) -> None:
        new: State | None = event.data["new_state"]
        entity_id = event.data["entity_id"]
        if new is not None and new.state in _BAD_STATES:
            if entity_id not in self._unavailable_timers:
                self._arm_unavailable(entity_id)
        elif cancel := self._unavailable_timers.pop(entity_id, None):
            cancel()

    @callback
    def _arm_unavailable(self, entity_id: str) -> None:
        minutes = float(self.opts[CONF_UNAVAILABLE_MINUTES])

        @callback
        def _fire(_now: Any) -> None:
            self._unavailable_timers.pop(entity_id, None)
            state = self.hass.states.get(entity_id)
            if state is None or state.state not in _BAD_STATES:
                return
            info = {
                "entity_id": entity_id,
                "state": state.state,
                "minutes": minutes,
                "since": state.last_changed.isoformat(),
            }
            self._send(
                "entity_unavailable",
                self._issue_message(
                    "entity_unavailable",
                    f"{state.name} ({entity_id}) has been {state.state} for {minutes:g} minutes.",
                    info,
                ),
                source=entity_id,
                context_entities=[entity_id],
                action_mode=self.opts[CONF_UNAVAILABLE_ACTION],
                data=info,
            )

        self._unavailable_timers[entity_id] = async_call_later(self.hass, minutes * 60, _fire)

    @callback
    def _on_repair(self, event: Event) -> None:
        if event.data.get("action") != "create":
            return
        domain, issue_id = event.data["domain"], event.data["issue_id"]
        if domain == DOMAIN:
            return
        info = issue_info(self.hass, domain, issue_id)
        if info is None or info.get("ignored"):
            return
        self._send(
            "repair_issue",
            self._issue_message(
                "repair_issue",
                f"New repair issue from {domain}: {issue_id}.",
                info,
            ),
            source=f"repairs.{domain}",
            action_mode=self.opts[CONF_REPAIRS_ACTION],
            data=info,
        )

    @callback
    def _on_entry_changed(self, change: ConfigEntryChange, entry: ConfigEntry) -> None:
        if change != ConfigEntryChange.UPDATED or entry.domain == DOMAIN:
            return
        if entry.state not in (
            ConfigEntryState.SETUP_ERROR,
            ConfigEntryState.SETUP_RETRY,
        ):
            return
        if self._dedupe_hit(f"setup:{entry.entry_id}:{entry.state.value}") is None:
            return
        info = {
            "domain": entry.domain,
            "config_entry_id": entry.entry_id,
            "title": entry.title,
            "state": entry.state.value,
            "reason": entry.reason,
        }
        self._send(
            "setup_failed",
            self._issue_message(
                "setup_failed",
                f"Integration {entry.domain} ({entry.title}) failed to set up: "
                f"{entry.state.value}. {entry.reason or ''}".strip(),
                info,
            ),
            source=f"config_entry.{entry.domain}",
            action_mode=self.opts[CONF_SETUP_ACTION],
            data=info,
        )

    @callback
    def async_process_log(self, rec: dict[str, Any]) -> None:
        """Handle a captured log record (already on the event loop)."""
        name: str = rec["name"]
        opts = self.opts
        if name.startswith(_AUTOMATION_LOGGERS) and rec["levelno"] >= logging.ERROR:
            if not opts[CONF_WATCH_AUTOMATIONS]:
                return
            kind, action = "automation_error", opts[CONF_AUTOMATIONS_ACTION]
        elif (
            name.startswith(_SETUP_LOGGERS)
            and rec["levelno"] >= logging.ERROR
            and opts[CONF_WATCH_SETUP]
        ):
            kind, action = "setup_error", opts[CONF_SETUP_ACTION]
        else:
            if not opts[CONF_WATCH_LOGS]:
                return
            if rec["levelno"] < logging.getLevelName(opts[CONF_LOG_LEVEL]):
                return
            loggers = [lg.strip() for lg in opts[CONF_LOG_LOGGERS] if lg.strip()]
            matched = any(name == lg or name.startswith(f"{lg}.") for lg in loggers)
            mode = opts[CONF_LOG_LOGGER_MODE]
            if mode == LOGGER_MODE_ALLOW and not matched:
                return
            if mode == LOGGER_MODE_DENY and matched:
                return
            kind, action = "log_error", opts[CONF_LOG_ACTION]
        repeats = self._dedupe_hit(f"{kind}:{name}:{rec['template']}")
        if repeats is None:
            return
        info = {
            "logger": name,
            "level": rec["level"],
            "source": rec["source"],
            "repeats_suppressed": repeats,
            "traceback": rec["traceback"],
        }
        self.hub.recent_errors.append(
            {k: v for k, v in info.items() if k != "traceback"} | {"message": rec["message"][:500]}
        )
        self._send(
            kind,
            self._issue_message(kind, f"{rec['level']} from {name}: {rec['message']}", info),
            source=name,
            action_mode=action,
            data=info,
        )


def issue_info(hass: HomeAssistant, domain: str, issue_id: str) -> dict | None:
    """JSON-friendly description of a repair issue."""
    issue = ir.async_get(hass).async_get_issue(domain, issue_id)
    if issue is None:
        return None
    return {
        "domain": issue.domain,
        "issue_id": issue.issue_id,
        "severity": str(issue.severity) if issue.severity else None,
        "translation_key": issue.translation_key,
        "translation_placeholders": issue.translation_placeholders,
        "learn_more_url": issue.learn_more_url,
        "is_fixable": issue.is_fixable,
        "breaks_in_ha_version": issue.breaks_in_ha_version,
        "ignored": issue.dismissed_version is not None,
        "created": issue.created.isoformat() if issue.created else None,
    }


def open_issues(hass: HomeAssistant) -> list[dict]:
    """All active, not-ignored repair issues."""
    out = []
    for (domain, issue_id), issue in ir.async_get(hass).issues.items():
        if not issue.active or issue.dismissed_version is not None:
            continue
        if info := issue_info(hass, domain, issue_id):
            out.append(info)
    return out


class _GrokBotLogHandler(logging.Handler):
    """Captures WARNING+ records and hands them to the event loop."""

    def __init__(self, manager: TriggerManager) -> None:
        super().__init__(level=logging.WARNING)
        self._manager = manager
        self._loop = manager.hass.loop

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(_OWN_LOGGERS):
            return
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        tb = None
        if record.exc_info:
            tb = "".join(traceback.format_exception(*record.exc_info))[-4000:]
        rec = {
            "name": record.name,
            "level": record.levelname,
            "levelno": record.levelno,
            "message": message[:2000],
            "template": str(record.msg)[:200],
            "source": f"{record.pathname}:{record.lineno}",
            "traceback": tb,
        }
        with contextlib.suppress(RuntimeError):  # loop closed during shutdown
            self._loop.call_soon_threadsafe(self._manager.async_process_log, rec)
