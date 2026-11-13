"""Switches: pause all sending, and the opt-in trusted access window."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GrokBotConfigEntry
from .entity import GrokBotEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrokBotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data.hub
    entities: list[SwitchEntity] = [GrokBotPauseSwitch(hub, "pause")]
    if hub.trusted.enabled:
        entities.append(GrokBotTrustedSwitch(hub, "trusted"))
    async_add_entities(entities)


class GrokBotPauseSwitch(GrokBotEntity, SwitchEntity):
    """On = nothing is sent to Grok Bot (manual or automatic)."""

    @property
    def is_on(self) -> bool:
        return self.hub.paused

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.hub.async_set_paused(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.hub.async_set_paused(False)


class GrokBotTrustedSwitch(GrokBotEntity, SwitchEntity):
    """On = Grok Bot may edit allowlisted YAML files and restart (trusted window)."""

    _attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool:
        return self.hub.trusted.active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        t = self.hub.trusted
        return {
            "until": t.until_iso,
            "allow_yaml_edit": t.allow_yaml_edit,
            "allow_restart": t.allow_restart,
            "backups": [b["backup"] for b in t.backups[-5:]],
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.hub.trusted.turn_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.hub.trusted.turn_off()
