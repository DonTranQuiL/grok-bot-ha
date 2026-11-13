"""Trusted access: opt-in YAML edits and restarts for repairs (Advanced, off by default).

Grok Bot edits files through its own connector (e.g. HA-MCP file tools). This
module adds the Home Assistant side safety net:

* ``grok_bot.prepare_change``: timestamped backup of an allowlisted file under
  ``/config/.grok_bot_backups/`` before any edit;
* ``grok_bot.restore_backup``: put a backup back;
* ``grok_bot.safe_restart``: check the configuration first and only restart when
  it is valid and restarts are allowed. When a conversation still awaits its
  reply the restart waits for that reply (at most ``RESTART_REPLY_GRACE``
  seconds), and the awaiting conversation is kept in the Store so a reply that
  arrives after the restart still lands in the right conversation.

Trusted is only active while the option is on, the warning is confirmed and the
*Trusted access* switch is on (by default for a 30 minute window that then
auto-reverts). Every action is audited and announced in a persistent notification.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
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
    BACKUP_DIR,
    BACKUPS_LEN,
    CONF_ALLOW_RESTART,
    CONF_ALLOW_YAML_EDIT,
    CONF_TRUSTED,
    CONF_TRUSTED_CONFIRM,
    CONF_TRUSTED_DURATION,
    DOMAIN,
    ISSUE_TRUSTED_ALWAYS,
    RESTART_AFTER_REPLY,
    RESTART_REPLY_GRACE,
    STATUS_RESTARTING,
    TRUSTED_ALWAYS,
    TRUSTED_DENY,
    TRUSTED_DIRS,
    TRUSTED_DURATIONS,
    TRUSTED_FILES,
    YAML_OPERATIONS,
)

if TYPE_CHECKING:
    from .hub import GrokBotHub

FOREVER = "forever"


def resolve_allowed(config_dir: str, path: str) -> Path:
    """Absolute path of an allowlisted config file, or ServiceValidationError."""
    root = Path(config_dir).resolve()
    raw = Path(path)
    candidate = (raw if raw.is_absolute() else root / raw).resolve()
    try:
        rel = candidate.relative_to(root)
    except ValueError:
        raise _deny("path_not_allowed", path) from None
    parts = rel.parts
    if not parts or any(p in TRUSTED_DENY or p.startswith(".") for p in parts):
        raise _deny("path_not_allowed", path)
    allowed = (len(parts) == 1 and parts[0] in TRUSTED_FILES) or (
        parts[0] in TRUSTED_DIRS and candidate.suffix in (".yaml", ".yml")
    )
    if not allowed:
        raise _deny("path_not_allowed", path)
    return candidate


def _deny(key: str, value: str = "") -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key=key, translation_placeholders={"value": value}
    )


class TrustedManager:
    """State of the trusted window plus the backup/restore/restart helpers."""

    def __init__(self, hass: HomeAssistant, hub: GrokBotHub) -> None:
        self.hass = hass
        self.hub = hub
        self.until: float | str | None = None  # epoch, FOREVER or None (off)
        self.backups: list[dict[str, Any]] = []
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
    def allow_yaml_edit(self) -> bool:
        return self.active and bool(self.options[CONF_ALLOW_YAML_EDIT])

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
        self.until = FOREVER if data.get("trusted_until") == FOREVER else None
        self.backups = list(data.get("backups", []))[-BACKUPS_LEN:]

    def to_store(self) -> dict[str, Any]:
        return {
            "trusted_until": FOREVER if self.until == FOREVER else None,
            "backups": self.backups,
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
            "allow_yaml_edit": self.allow_yaml_edit,
            "allow_restart": self.allow_restart,
            "trusted_until": self.until_iso,
            "always_on": self.until == FOREVER,
            "edit_service": f"{DOMAIN}.edit_yaml",
            "backup_service": f"{DOMAIN}.prepare_change",
            "restore_service": f"{DOMAIN}.restore_backup",
            "restart_service": f"{DOMAIN}.safe_restart",
        }

    # ----------------------------------------------------------- actions
    async def async_prepare_change(self, path: str) -> dict[str, Any]:
        self._require(self.allow_yaml_edit, "yaml_edit_not_allowed")
        config_dir = self.hass.config.config_dir
        stamp = dt_util.now().strftime("%Y%m%d-%H%M%S-%f")

        def _copy() -> tuple[str, str]:
            target = resolve_allowed(config_dir, path)
            if not target.is_file():
                raise _deny("file_not_found", path)
            root = Path(config_dir).resolve()
            rel = str(target.relative_to(root))
            backup = root / BACKUP_DIR / f"{rel.replace(os.sep, '__')}.{stamp}.bak"
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            return rel, str(backup)

        try:
            rel, backup = await self.hass.async_add_executor_job(_copy)
        except ServiceValidationError:
            self._record("prepare_change", False, f"denied: {path}")
            raise
        item = {"path": rel, "backup": backup, "time": dt_util.utcnow().isoformat()}
        self.backups = [*self.backups, item][-BACKUPS_LEN:]
        self._record("prepare_change", True, f"backup of {rel} -> {Path(backup).name}")
        return {"path": rel, "backup_path": backup}

    async def async_restore_backup(self, backup_path: str) -> dict[str, Any]:
        self._require(self.allow_yaml_edit, "yaml_edit_not_allowed")
        item = next((b for b in self.backups if b["backup"] == backup_path), None)
        if item is None:
            raise _deny("backup_not_found", backup_path)
        config_dir = self.hass.config.config_dir
        backup = Path(item["backup"])

        def _restore() -> None:
            target = resolve_allowed(config_dir, item["path"])
            if not backup.is_file():
                raise _deny("backup_not_found", backup_path)
            shutil.copy2(backup, target)

        await self.hass.async_add_executor_job(_restore)
        self._record(
            "restore_backup", True, f"restored {item['path']} from {backup.name}", notify=True
        )
        return {"path": item["path"], "restored_from": str(backup)}

    async def async_edit_yaml(
        self,
        path: str,
        operation: str,
        *,
        key: str | None = None,
        value: Any = None,
        find: str | None = None,
        replace: str = "",
        count: int = 0,
    ) -> dict[str, Any]:
        """Backup, edit, validate YAML, check_config, and auto-restore on failure.

        Works on top-level keys (http, homeassistant, frontend, ...) that HA-MCP's
        trust boundary refuses, preserving the rest of the file text.
        """
        self._require(self.allow_yaml_edit, "yaml_edit_not_allowed")
        if operation not in YAML_OPERATIONS:
            raise _deny("invalid_operation", operation)
        if operation in ("remove_key", "set_key") and not _valid_key(key):
            raise _deny("invalid_key", str(key))
        if operation == "replace_text" and not find:
            raise _deny("invalid_find")
        prepared = await self.async_prepare_change(path)
        config_dir = self.hass.config.config_dir
        rel, backup = prepared["path"], prepared["backup_path"]

        def _apply() -> tuple[bool, str | None]:
            target = resolve_allowed(config_dir, rel)
            text = target.read_text(encoding="utf-8")
            new = apply_yaml_edit(
                text, operation, key=key, value=value, find=find, replace=replace, count=count
            )
            if new == text:
                return False, None
            if err := validate_yaml(new):
                return False, err
            target.write_text(new, encoding="utf-8")
            return True, None

        summary = f"{operation} {key or repr(find)} in {rel}"
        try:
            changed, yaml_error = await self.hass.async_add_executor_job(_apply)
        except ServiceValidationError:
            self._record("edit_yaml", False, f"{summary}: failed")
            raise
        if yaml_error:
            self._record("edit_yaml", False, f"{summary}: invalid YAML, file left unchanged")
            return {
                "ok": False,
                "changed": False,
                "path": rel,
                "backup_path": backup,
                "errors": [yaml_error],
                "restored": False,
            }
        if not changed:
            self._record("edit_yaml", True, f"{summary}: nothing to change")
            return {"ok": True, "changed": False, "path": rel, "backup_path": backup, "errors": []}
        errors = await async_check_config(self.hass)
        if errors:
            await self.async_restore_backup(backup)
            self._record("edit_yaml", False, f"{summary}: config check failed, backup restored")
            return {
                "ok": False,
                "changed": False,
                "path": rel,
                "backup_path": backup,
                "errors": errors,
                "restored": True,
            }
        self._record("edit_yaml", True, f"{summary}: done, config check passed")
        return {
            "ok": True,
            "changed": True,
            "path": rel,
            "backup_path": backup,
            "errors": [],
            "restart_required": True,
        }

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


# ---------------------------------------------------------------- YAML edits
_TOP_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:(\s|$)")


def _valid_key(key: str | None) -> bool:
    return bool(key) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key or "") is not None


def _blocks(lines: list[str], key: str) -> list[tuple[int, int]]:
    """(start, end) line ranges of every top-level ``key:`` block (duplicates too)."""
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(lines):
        m = _TOP_KEY.match(lines[i])
        if m and m.group(1) == key:
            j = i + 1
            while j < len(lines):
                line = lines[j]
                if line.strip() and not line[0].isspace() and not line.startswith("#"):
                    break
                j += 1
            # keep trailing blank/comment lines with the next block
            while j - 1 > i and (not lines[j - 1].strip() or lines[j - 1].startswith("#")):
                j -= 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def _remove_blocks(text: str, key: str) -> str:
    lines = text.splitlines(keepends=True)
    for start, end in reversed(_blocks(lines, key)):
        del lines[start:end]
    return "".join(lines)


def _dump(key: str, value: Any) -> str:
    import yaml

    dumped = yaml.safe_dump({key: value}, default_flow_style=False, sort_keys=False)
    return dumped if dumped.endswith("\n") else dumped + "\n"


def apply_yaml_edit(
    text: str,
    operation: str,
    *,
    key: str | None = None,
    value: Any = None,
    find: str | None = None,
    replace: str = "",
    count: int = 0,
) -> str:
    """Pure text edit; comments and the rest of the file are preserved."""
    if operation == "remove_key":
        return _remove_blocks(text, str(key))
    if operation == "set_key":
        lines = text.splitlines(keepends=True)
        blocks = _blocks(lines, str(key))
        block = _dump(str(key), value)
        if not blocks:
            sep = "" if not text or text.endswith("\n") else "\n"
            return f"{text}{sep}{block}"
        first = blocks[0][0]
        for start, end in reversed(blocks):
            del lines[start:end]
        lines.insert(first, block)
        return "".join(lines)
    if operation == "replace_text":
        if find not in text:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="text_not_found",
                translation_placeholders={"value": str(find)[:80]},
            )
        return text.replace(str(find), replace, count if count > 0 else -1)
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="invalid_operation")


def validate_yaml(text: str) -> str | None:
    """None when the text parses as YAML (HA tags like !secret/!include allowed)."""
    import yaml

    class _Loader(yaml.SafeLoader):
        pass

    def _any_tag(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> Any:
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        return loader.construct_mapping(node)

    _Loader.add_multi_constructor("!", _any_tag)
    try:
        yaml.load(text, Loader=_Loader)
    except yaml.YAMLError as err:
        return f"Invalid YAML: {err}"[:500]
    return None
