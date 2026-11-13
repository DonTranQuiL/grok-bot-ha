"""Switch that pauses all sending to Grok Bot."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    async_add_entities([GrokBotPauseSwitch(entry.runtime_data.hub, "pause")])


class GrokBotPauseSwitch(GrokBotEntity, SwitchEntity):
    """On = nothing is sent to Grok Bot (manual or automatic)."""

    @property
    def is_on(self) -> bool:
        return self.hub.paused

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.hub.async_set_paused(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.hub.async_set_paused(False)
