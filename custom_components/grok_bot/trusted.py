"""Trusted access: opt-in YAML edits and restarts for repairs (Advanced, off by default).

Grok Bot edits files through its own connector (e.g. HA-MCP file tools). This
module adds the Home Assistant side safety net:

* ``grok_bot.prepare_change``: timestamped backup of an allowlisted file under
  ``/config/.grok_bot_backups/`` before any edit;
* ``grok_bot.restore_backup``: put a backup back;
* ``grok_bot.safe_restart``: check the configuration first and only restart when
  it is valid and restarts are allowed.

Trusted is only active while the option is on, the warning is confirmed and the
*Trusted access* switch is on (by default for a 30 minute window that then
auto-reverts). Every action is audited and announced in a persistent notification.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import time as _time
from typing import TYPE_CHECKING, Any

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .const import (
    ACTION_FIX,
    BACKUP_DIR,
    BACKUPS_LEN,
    CONF_ALLOW_RESTART,
    CONF_ALLOW_YAML_EDIT,
    CONF_TRUSTED,
    CONF_TRUSTED_CONFIRM,
    CONF_TRUSTED_WINDOW,
    CONF_TRUSTED_WINDOW_MINUTES,
    DOMAIN,
    TRUSTED_DENY,
    TRUSTED_DIRS,
    TRUSTED_FILES,
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
        return self.until == FOREVER or float(self.until) > _time.time()

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
        if self.options[CONF_TRUSTED_WINDOW]:
            minutes = float(self.options[CONF_TRUSTED_WINDOW_MINUTES])
            self.until = _time.time() + minutes * 60
        else:
            self.until = FOREVER
        self._record("trusted_on", True, f"trusted access on until {self.until_iso}")

    @callback
    def turn_off(self, reason: str = "switched off") -> None:
        was = self.until is not None
        self.until = None
        if was:
            self._record("trusted_off", True, f"trusted access off ({reason})")

    @callback
    def async_tick(self) -> None:
        """Auto-revert an expired window."""
        if self.until not in (None, FOREVER) and float(self.until) <= _time.time():
            self.turn_off("window expired")

    def payload_block(self, action_mode: str, allow_fix: bool) -> dict[str, Any] | None:
        """Trusted flags for `access`, only for fix requests while trusted is active."""
        if not (self.active and action_mode == ACTION_FIX and allow_fix):
            return None
        return {
            "trusted": True,
            "allow_yaml_edit": self.allow_yaml_edit,
            "allow_restart": self.allow_restart,
            "trusted_until": self.until_iso,
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

    async def async_safe_restart(self) -> dict[str, Any]:
        self._require(self.allow_restart, "restart_not_allowed")
        errors = await async_check_config(self.hass)
        if errors:
            self._record("safe_restart", False, "config invalid, not restarting", notify=True)
            return {"valid": False, "restarting": False, "errors": errors}
        self._record("safe_restart", True, "config valid, restarting Home Assistant", notify=True)
        self.hub.save()
        await async_restart(self.hass)
        return {"valid": True, "restarting": True, "errors": []}

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
