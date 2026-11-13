"""Grok Bot buttons (manual sends; they count toward the budget)."""

from __future__ import annotations

from homeassistant.components import persistent_notification
from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GrokBotConfigEntry
from .const import ACTION_DIAGNOSE, ACTION_FIX, SETUP_NOTIFICATION_ID
from .entity import GrokBotEntity
from .services import health_snapshot

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrokBotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data.hub
    async_add_entities(
        [
            GrokBotButton(hub, "ping"),
            GrokBotButton(hub, "health_report"),
            GrokBotButton(hub, "fix_repairs"),
            GrokBotButton(hub, "reset_budget"),
            GrokBotButton(hub, "rotate_token"),
            GrokBotButton(hub, "mark_handled"),
            GrokBotButton(hub, "clear_history"),
            GrokBotButton(hub, "setup_prompt"),
        ]
    )


class GrokBotButton(GrokBotEntity, ButtonEntity):
    """One Grok Bot button."""

    def __init__(self, hub, key: str) -> None:
        super().__init__(hub, key)
        if key in ("ping", "reset_budget", "rotate_token", "setup_prompt"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        elif key == "clear_history":
            self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        hub = self.hub
        key = self._attr_translation_key
        if key == "ping":
            await hub.async_send("ping", "Ping from Home Assistant", source=self.entity_id)
        elif key == "reset_budget":
            hub.async_reset_budget()
        elif key == "rotate_token":
            hub.access.rotate_token()
        elif key == "clear_history":
            await hub.async_clear_history()
        elif key == "mark_handled":
            hub.async_mark_all_handled()
        elif key == "setup_prompt":
            persistent_notification.async_create(
                self.hass,
                f"```\n{hub.setup_prompt()}\n```",
                title="Grok Bot setup prompt",
                notification_id=SETUP_NOTIFICATION_ID.format(hub.entry.entry_id),
            )
        else:
            snap = health_snapshot(self.hass, hub)
            if key == "fix_repairs":
                await hub.async_send(
                    "fix_issue",
                    f"Fix the {len(snap['repair_issues'])} open repair issues where "
                    "a safe, reversible fix exists.",
                    source=self.entity_id,
                    action_mode=ACTION_FIX,
                    data={"repair_issues": snap["repair_issues"]},
                )
            else:
                await hub.async_send(
                    "health_report",
                    "Health report requested from the dashboard.",
                    source=self.entity_id,
                    action_mode=ACTION_DIAGNOSE,
                    data=snap,
                )
