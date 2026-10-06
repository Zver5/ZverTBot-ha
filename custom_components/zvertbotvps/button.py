from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ZverTBotCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    coordinator: ZverTBotCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([VPSRefreshButton(coordinator), VPSReconnectButton(coordinator)])


class VPSActionButton(CoordinatorEntity[ZverTBotCoordinator], ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ZverTBotCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": "ZverTBot VPS",
            "manufacturer": "ZverTBot",
            "model": "VPS",
        }


class VPSRefreshButton(VPSActionButton):
    _attr_name = "Refresh VPS"

    def __init__(self, coordinator: ZverTBotCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_refresh"

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh_now()


class VPSReconnectButton(VPSActionButton):
    _attr_name = "Reconnect VPS"

    def __init__(self, coordinator: ZverTBotCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_reconnect"

    async def async_press(self) -> None:
        await self.coordinator.async_request_reconnect()
