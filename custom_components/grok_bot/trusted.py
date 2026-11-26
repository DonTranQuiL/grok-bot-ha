"""Trusted access: opt-in restarts for repairs (Advanced, off by default).

``grok_bot.safe_restart`` checks the configuration first and only restarts when
it is valid and restarts are allowed. When a conversation still awaits its
reply the restart waits for that reply (at most ``RESTART_REPLY_GRACE``
seconds), and the awaiting conversation is kept in the Store so a reply that
arrives after the restart still lands in the right conversation.

Trusted is only active while the option is on, the warning is confirmed and the
*Trusted access* switch is on (by default for a 30 minute window that then
auto-reverts). Every action is audited and announced in a persistent notification.
"""

from __future__ import annotations

import time as _time
from typing import TYPE_CHECKING, Any

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import (
    ACTION_FIX,
    CONF_ALLOW_RESTART,
    CONF_TRUSTED,
    CONF_TRUSTED_CONFIRM,
    CONF_TRUSTED_DURATION,
    DOMAIN,
    ISSUE_TRUSTED_ALWAYS,
    RESTART_AFTER_REPLY,
    RESTART_REPLY_GRACE,
    STATUS_RESTARTING,
    TRUSTED_ALWAYS,
    TRUSTED_DURATIONS,
)

if TYPE_CHECKING:
    from .hub import GrokBotHub

FOREVER = "forever"


def _deny(key: str, value: str = "") -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key=key, translation_placeholders={"value": value}
    )


class TrustedManager:
    """State of the trusted window plus the restart helper."""

    def __init__(self, hass: HomeAssistant, hub: GrokBotHub) -> None:
        self.hass = hass
        self.hub = hub
        self.until: float | str | None = None  # epoch, FOREVER or None (off)
        self._restart_unsub: Any = None
        self._restart_waiting: set[str] = set()
        self._restart_fired = False

    # ------------------------------------------------------------- state
    @property
    def options(self) -> dict[str, Any]:
        return self.hub.options

    @property
    def enabled(self) -> bool:
        """The Advanced option is on and the warning was confirmed."""
        return bool(self.options[CONF_TRUSTED] and self.options[CONF_TRUSTED_CONFIRM])

    @property
    def active(self) -> bool:
        if not self.enabled or self.until is None:
            return False
        if self.until == FOREVER:
            return self.always_on
        return float(self.until) > _time.time()

    @property
    def always_on(self) -> bool:
        return self.options[CONF_TRUSTED_DURATION] == TRUSTED_ALWAYS

    @property
    def allow_restart(self) -> bool:
        return self.active and bool(self.options[CONF_ALLOW_RESTART])

    @property
    def until_iso(self) -> str | None:
        if not self.active:
            return None
        if self.until == FOREVER:
            return FOREVER
        return dt_util.utc_from_timestamp(float(self.until)).isoformat()

    def load(self, data: dict[str, Any]) -> None:
        # A restart never keeps a timed window open; "forever" survives restarts.
        # Backups from older versions that edited YAML are ignored.
        self.until = FOREVER if data.get("trusted_until") == FOREVER else None

    def to_store(self) -> dict[str, Any]:
        return {
            "trusted_until": FOREVER if self.until == FOREVER else None,
        }

    @callback
    def turn_on(self) -> None:
        if not self.enabled:
            raise _deny("trusted_disabled")
        minutes = TRUSTED_DURATIONS.get(self.options[CONF_TRUSTED_DURATION], 30)
        if minutes is None:
            self.until = FOREVER
        else:
            self.until = _time.time() + minutes * 60
        self._record("trusted_on", True, f"trusted access on until {self.until_iso}")
        self.update_issue()

    @callback
    def turn_off(self, reason: str = "switched off") -> None:
        was = self.until is not None
        self.until = None
        if was:
            self._record("trusted_off", True, f"trusted access off ({reason})")
        self.update_issue()

    @callback
    def async_tick(self) -> None:
        """Auto-revert an expired window (or 'Always on' that is no longer chosen)."""
        if self.until == FOREVER and not (self.always_on and self.enabled):
            self.turn_off("trusted window changed")
        elif self.until not in (None, FOREVER) and float(self.until) <= _time.time():
            self.turn_off("window expired")
        self.update_issue()

    @callback
    def update_issue(self) -> None:
        """Extra warning while Trusted access is on with 'Always on'."""
        issue_id = f"{ISSUE_TRUSTED_ALWAYS}_{self.hub.entry.entry_id}"
        if self.active and self.until == FOREVER:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_TRUSTED_ALWAYS,
                translation_placeholders={"name": self.hub.entry.title},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    def payload_block(self, action_mode: str, allow_fix: bool) -> dict[str, Any] | None:
        """Trusted flags for `access`, only for fix requests while trusted is active."""
        if not (self.active and action_mode == ACTION_FIX and allow_fix):
            return None
        return {
            "trusted": True,
            "allow_restart": self.allow_restart,
            "trusted_until": self.until_iso,
            "always_on": self.until == FOREVER,
            "restart_service": f"{DOMAIN}.safe_restart",
        }

    # ----------------------------------------------------------- actions
    @property
    def restart_scheduled(self) -> bool:
        return self._restart_unsub is not None

    async def async_safe_restart(self, conversation_id: str | None = None) -> dict[str, Any]:
        """Check the configuration, then restart once the awaited reply is in.

        With ``conversation_id`` the restart waits for that conversation's reply;
        without one it waits for any conversation that is still awaiting a reply.
        Either way it never waits longer than ``RESTART_REPLY_GRACE`` seconds.
        """
        self._require(self.allow_restart, "restart_not_allowed")
        errors = await async_check_config(self.hass)
        if errors:
            self._record("safe_restart", False, "config invalid, not restarting", notify=True)
            return {"valid": False, "restarting": False, "errors": errors}
        hub = self.hub
        if conversation_id:
            waiting = [conversation_id] if conversation_id in hub.pending else []
        else:
            waiting = list(hub.pending)
        hub.restart_marker = {
            "time": dt_util.utcnow().isoformat(),
            "conversation_id": conversation_id,
            "conversations": list(hub.pending),
        }
        for item in hub.pending.values():
            item["restarting"] = True
        if self.restart_scheduled:
            self._restart_waiting.update(waiting)
            await hub.async_save_now()
            return self._restart_result(waiting)
        if not waiting:
            self._record(
                "safe_restart", True, "config valid, restarting Home Assistant", notify=True
            )
            await hub.async_save_now()
            self._restart_fired = True
            await async_restart(self.hass)
            return {"valid": True, "restarting": True, "errors": [], "delay": 0}
        self._restart_waiting = set(waiting)
        self._restart_fired = False
        self._restart_unsub = async_call_later(
            self.hass, RESTART_REPLY_GRACE, self._async_restart_now
        )
        hub.last_status = STATUS_RESTARTING
        self._record(
            "safe_restart",
            True,
            "config valid, restarting Home Assistant after the reply "
            f"(at most {RESTART_REPLY_GRACE} s)",
            notify=True,
        )
        await hub.async_save_now()
        hub.notify()
        return self._restart_result(waiting)

    @staticmethod
    def _restart_result(waiting: list[str]) -> dict[str, Any]:
        return {
            "valid": True,
            "restarting": True,
            "errors": [],
            "delay": RESTART_REPLY_GRACE,
            "waiting_for_reply": waiting,
            "note": "Send grok_bot.reply now; Home Assistant restarts right after it arrives.",
        }

    @callback
    def async_reply_arrived(self, conversation_id: str) -> None:
        """The awaited reply is in: restart after a short pause (reply saved first)."""
        if not self.restart_scheduled or self._restart_fired:
            return
        if conversation_id not in self._restart_waiting and conversation_id:
            return
        self._restart_unsub()
        self._restart_unsub = async_call_later(
            self.hass, RESTART_AFTER_REPLY, self._async_restart_now
        )
        self._restart_waiting.clear()

    async def _async_restart_now(self, _now: Any = None) -> None:
        if self._restart_fired:
            return
        self._restart_fired = True
        self._restart_unsub = None
        await self.hub.async_save_now()
        await async_restart(self.hass)

    @callback
    def async_cancel_restart(self) -> None:
        """Entry unloaded before a delayed restart went ahead: forget it."""
        if self._restart_unsub is None:
            return
        self._restart_unsub()
        self._restart_unsub = None
        self._restart_waiting.clear()
        if not self._restart_fired:
            self.hub.restart_marker = None
            for item in self.hub.pending.values():
                item.pop("restarting", None)

    def record_restart_done(self, marker: dict[str, Any], waiting: list[str]) -> None:
        """Audit entry on the first start after safe_restart (no notification)."""
        summary = "Home Assistant is back after the restart"
        if waiting:
            summary += f", waiting for the result of {len(waiting)} conversation(s)"
        self._record("restart_done", True, summary, notify=False)

    # ------------------------------------------------------------ helpers
    def _require(self, ok: bool, key: str) -> None:
        if not ok:
            self._record(key, False, f"denied: {key}", notify=True)
            raise _deny(key)

    def _record(self, kind: str, ok: bool, summary: str, notify: bool = True) -> None:
        """Audit sensor + grok_bot_action event + a persistent notification, always."""
        name = kind if kind.startswith("trusted") else f"trusted_{kind}"
        self.hub.access._log(
            {"type": name, "ok": ok, "summary": summary, "trusted": True}, fire=True
        )
        if notify:
            persistent_notification.async_create(
                self.hass,
                f"Grok Bot (trusted): {summary}",
                title="Grok Bot trusted action",
                notification_id=f"{DOMAIN}_trusted_{_time.time_ns()}_{kind}",
            )


async def async_check_config(hass: HomeAssistant) -> list[str]:
    """Errors from a full configuration check (empty = valid)."""
    from homeassistant.helpers.check_config import async_check_ha_config_file

    result = await async_check_ha_config_file(hass)
    return [str(err) for err in result.errors]


async def async_restart(hass: HomeAssistant) -> None:
    """Schedule the restart so the service call can still return its response."""
    hass.async_create_task(hass.services.async_call("homeassistant", "restart", blocking=False))
