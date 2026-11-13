"""Base entity for Grok Bot."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, INTEGRATION_VERSION
from .hub import GrokBotHub


class GrokBotEntity(Entity):
    """Common device info + live updates from the hub."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: GrokBotHub, key: str) -> None:
        self.hub = hub
        self._attr_translation_key = key
        self._attr_unique_id = f"{hub.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.entry.entry_id)},
            name=hub.entry.title,
            manufacturer="DonTranQuiL",
            model="Grok Bot webhook",
            sw_version=INTEGRATION_VERSION,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://github.com/DonTranQuiL/grok-bot-ha",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self.hub.signal, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
