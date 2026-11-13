"""Notify entity: notify.send_message reaches Grok Bot (opt-in)."""

from __future__ import annotations

from homeassistant.components.notify import NotifyEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GrokBotConfigEntry
from .const import CONF_ENABLE_NOTIFY, DOMAIN, STATUS_AUTH_FAILED, STATUS_FAILED
from .entity import GrokBotEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrokBotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data.hub
    if hub.options[CONF_ENABLE_NOTIFY]:
        async_add_entities([GrokBotNotify(hub, "notify")])


class GrokBotNotify(GrokBotEntity, NotifyEntity):
    """Send a message to Grok Bot."""

    _attr_name = None
    _attr_translation_key = "notify"

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        text = f"{title}\n{message}" if title else message
        result = await self.hub.async_send(
            "notify", text, source=self.entity_id, data={"title": title}
        )
        if result["status"] in (STATUS_FAILED, STATUS_AUTH_FAILED):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="send_failed")
