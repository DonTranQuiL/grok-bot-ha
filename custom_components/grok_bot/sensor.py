"""Grok Bot sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import GrokBotConfigEntry
from .access import allowed_actions
from .const import MAX_STATE_LEN, STATUSES
from .entity import GrokBotEntity
from .hub import GrokBotHub

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GrokBotSensorDescription(SensorEntityDescription):
    """Describes a Grok Bot sensor."""

    value_fn: Callable[[GrokBotHub], Any]
    attrs_fn: Callable[[GrokBotHub], dict[str, Any]] | None = None


def _reply_attrs(hub: GrokBotHub) -> dict[str, Any]:
    reply = hub.last_reply or {}
    return {
        "message": reply.get("message"),
        "title": reply.get("title"),
        "conversation_id": reply.get("conversation_id"),
        "received": reply.get("received"),
        "data": reply.get("data"),
        "history": list(hub.history),
    }


def _access_state(info: dict) -> str:
    if info["method"] == "mcp":
        return info["mcp_provider"] or "none"
    return info["method"]


SENSORS: tuple[GrokBotSensorDescription, ...] = (
    GrokBotSensorDescription(
        key="last_reply",
        value_fn=lambda h: ((h.last_reply or {}).get("message") or "")[:MAX_STATE_LEN] or None,
        attrs_fn=_reply_attrs,
    ),
    GrokBotSensorDescription(
        key="last_status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUSES,
        value_fn=lambda h: h.last_status,
        attrs_fn=lambda h: {"last_error": h.last_error},
    ),
    GrokBotSensorDescription(
        key="last_sent",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda h: h.last_sent,
    ),
    GrokBotSensorDescription(
        key="sends_hour",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="sends",
        value_fn=lambda h: h.sends_hour,
        attrs_fn=lambda h: {"limit": h.max_hour, "remaining": max(0, h.max_hour - h.sends_hour)},
    ),
    GrokBotSensorDescription(
        key="sends_day",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="sends",
        value_fn=lambda h: h.sends_day,
        attrs_fn=lambda h: {
            "limit": h.max_day,
            "remaining": max(0, h.max_day - h.sends_day),
            "paused": h.paused,
        },
    ),
    GrokBotSensorDescription(
        key="sent_total",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda h: h.stats["sent"],
    ),
    GrokBotSensorDescription(
        key="failed_total",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda h: h.stats["failed"],
    ),
    GrokBotSensorDescription(
        key="dropped_total",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda h: h.stats["dropped"],
    ),
    GrokBotSensorDescription(
        key="access_method",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=["ha_mcp", "mcp_server", "webhook", "none"],
        value_fn=lambda h: _access_state(h.access_info()),
        attrs_fn=lambda h: h.access_info(),
    ),
    GrokBotSensorDescription(
        key="access_url",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda h: h.access.url if h.access.enabled else None,
        attrs_fn=lambda h: {
            "source": h.access.url_source if h.access.enabled else "off",
            "access_level": h.access.level,
            "allowed_actions": allowed_actions(h.options),
        },
    ),
    GrokBotSensorDescription(
        key="last_action",
        value_fn=lambda h: h.access.audit[-1]["summary"] if h.access.audit else None,
        attrs_fn=lambda h: {
            "ok": h.access.audit[-1]["ok"] if h.access.audit else None,
            "time": h.access.audit[-1]["time"] if h.access.audit else None,
            "audit": list(h.access.audit),
        },
    ),
    GrokBotSensorDescription(
        key="pending",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda h: len(h.pending),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrokBotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data.hub
    async_add_entities(GrokBotSensor(hub, desc) for desc in SENSORS)


class GrokBotSensor(GrokBotEntity, SensorEntity):
    """A Grok Bot sensor."""

    entity_description: GrokBotSensorDescription
    _unrecorded_attributes = frozenset({"history", "data", "message", "audit"})

    def __init__(self, hub: GrokBotHub, description: GrokBotSensorDescription) -> None:
        super().__init__(hub, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        value = self.entity_description.value_fn(self.hub)
        if self.entity_description.device_class == SensorDeviceClass.TIMESTAMP and value:
            return dt_util.as_utc(value)
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.hub)
