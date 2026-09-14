from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ZverTBotCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    coordinator: ZverTBotCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [VPSServiceBinarySensor(coordinator, name) for name in coordinator.data.get("services", {})]
    async_add_entities(entities)


class VPSServiceBinarySensor(CoordinatorEntity[ZverTBotCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator, service_name: str):
        super().__init__(coordinator)
        self.service_name = service_name
        self._attr_name = f"Service {service_name}"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_service_{service_name}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "ZverTBot VPS",
            "manufacturer": "ZverTBot",
            "model": "VPS",
        }

    @property
    def is_on(self):
        value = self.coordinator.service(self.service_name).get("status")
        return value in (1, True, "1", "active", "running", "up", "online")

    @property
    def extra_state_attributes(self):
        return {"uptime": self.coordinator.service(self.service_name).get("uptime")}
