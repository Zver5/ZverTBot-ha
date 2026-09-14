from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import ZverTBotCoordinator


_UNIT_MULTIPLIERS = {
    "b": 1,
    "kb": 1024,
    "kib": 1024,
    "mb": 1024**2,
    "mib": 1024**2,
    "gb": 1024**3,
    "gib": 1024**3,
    "tb": 1024**4,
    "tib": 1024**4,
}


def _device_info(coordinator: ZverTBotCoordinator) -> dict[str, Any]:
    return {
        "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
        "name": "ZverTBot",
        "manufacturer": "ZverTBot",
        "model": "VPS",
    }


def _parse_bytes(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    match = re.fullmatch(r"([0-9.]+)\s*([kmgt]?i?b)?", text, re.IGNORECASE)
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "b").lower()
    return number * _UNIT_MULTIPLIERS.get(unit, 1)


def _client_total_gb(client: dict[str, Any]) -> float:
    for key in ("total_bytes", "total"):
        value = _parse_bytes(client.get(key))
        if value is not None:
            return value / 1073741824
    down = _parse_bytes(client.get("downlink")) or 0
    up = _parse_bytes(client.get("uplink")) or 0
    return (down + up) / 1073741824


def _client_online(client: dict[str, Any]) -> bool:
    return bool(client.get("online")) or str(client.get("hs", "")).lower() == "active"


@dataclass(frozen=True)
class Metric:
    key: str
    name: str
    unit: str | None = None


METRICS = (
    Metric("system.cpu", "VPS CPU Load", PERCENTAGE),
    Metric("system.memory_percent", "VPS RAM Used", PERCENTAGE),
    Metric("system.disk.percent", "VPS Disk Used", PERCENTAGE),
    Metric("system.disk.free_gb", "VPS Disk Free", "GB"),
    Metric("system.disk.used_gb", "VPS Disk Used Space", "GB"),
    Metric("system.disk.total_gb", "VPS Disk Total Space", "GB"),
    Metric("fail2ban.currently_banned", "VPS Fail2Ban Banned Now"),
    Metric("fail2ban.total_banned", "VPS Fail2Ban Banned Total"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    coordinator: ZverTBotCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        VPSMetricSensor(coordinator, metric) for metric in METRICS
    ]
    entities += [
        VPSAllStatsSensor(coordinator),
        VPSConnectionsSensor(coordinator),
        VPSAWGClientsSensor(coordinator),
        VPSXrayClientsSensor(coordinator),
        VPSVPNTrafficSensor(coordinator),
        VPSBackupSensor(coordinator),
        VPSBackupLastSensor(coordinator),
        VPSBackupSizeSensor(coordinator),
        VPSBackupNextSensor(coordinator),
        VPSStatsUpdatedSensor(coordinator),
        VPSFreshnessSensor(coordinator),
    ]

    await _remove_legacy_client_entities(hass, entry)
    async_add_entities(entities)


async def _remove_legacy_client_entities(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Remove legacy per-client entities from older integration versions."""
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_"

    for entity in list(registry.entities.values()):
        if entity.config_entry_id != entry.entry_id:
            continue
        if entity.unique_id and (
            entity.unique_id.startswith(f"{prefix}awg:")
            or entity.unique_id.startswith(f"{prefix}xray:")
        ):
            registry.async_remove(entity.entity_id)


class VPSBaseEntity(CoordinatorEntity[ZverTBotCoordinator], SensorEntity):
    _attr_has_entity_name = False

    def __init__(self, coordinator: ZverTBotCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = _device_info(coordinator)


class VPSMetricSensor(VPSBaseEntity):
    def __init__(self, coordinator: ZverTBotCoordinator, metric: Metric) -> None:
        super().__init__(coordinator)
        self.metric = metric
        self._attr_name = metric.name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{metric.key.replace('.', '_')}"
        self._attr_native_unit_of_measurement = metric.unit

    @property
    def native_value(self):
        value: Any = self.coordinator.data
        for part in self.metric.key.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        return value


class VPSAllStatsSensor(VPSBaseEntity):
    """Compatibility/state hub for the existing VPS dashboard."""

    _attr_name = "VPS All Stats"

    def __init__(self, coordinator: ZverTBotCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_all_stats"

    @property
    def native_value(self):
        return len(self.coordinator.data.get("connections", []))

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        return {
            "server_ip": self.coordinator.server_ip,
            "connection_mode": self.coordinator.mode,
            "server": data.get("server", {}),
            "system": data.get("system", {}),
            "services": data.get("services", {}),
            "backup": data.get("backup", {}),
            "fail2ban": data.get("fail2ban", {}),
            "connections": data.get("connections", []),
            "updated_at": data.get("updated_at"),
        }


class VPSConnectionsSensor(VPSBaseEntity):
    _attr_name = "VPS Active Connections"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_connections"

    @property
    def native_value(self):
        return len(self.coordinator.data.get("connections", []))

    @property
    def extra_state_attributes(self):
        return {"connections": self.coordinator.data.get("connections", [])}


class _CountSensor(VPSBaseEntity):
    collection_key = ""
    label = "Count"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = self.label
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{self.collection_key}_count"

    @property
    def native_value(self):
        return len(self.coordinator.clients(self.collection_key))

    @property
    def extra_state_attributes(self):
        return {"clients": self.coordinator.clients(self.collection_key)}


class VPSAWGClientsSensor(_CountSensor):
    collection_key = "awg"
    label = "VPS AWG Clients"


class VPSXrayClientsSensor(_CountSensor):
    collection_key = "xray"
    label = "VPS Xray Clients"


class VPSVPNTrafficSensor(VPSBaseEntity):
    _attr_name = "VPS VPN Traffic"
    _attr_native_unit_of_measurement = "GB"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_vpn_traffic"

    @property
    def native_value(self):
        return self.coordinator.data.get("system", {}).get("vpn_total_gb")


class VPSBackupSensor(VPSBaseEntity):
    _attr_name = "VPS Backup Status"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_backup_status"

    @property
    def native_value(self):
        return self.coordinator.data.get("backup", {}).get("status")


class VPSBackupLastSensor(VPSBaseEntity):
    _attr_name = "VPS Backup Last"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_backup_last"

    @property
    def native_value(self):
        value = self.coordinator.data.get("backup", {}).get("last_backup")
        return dt_util.parse_datetime(value) if value else None


class VPSBackupSizeSensor(VPSBaseEntity):
    _attr_name = "VPS Backup Size"
    _attr_native_unit_of_measurement = "MB"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_backup_size"

    @property
    def native_value(self):
        return self.coordinator.data.get("backup", {}).get("size_mb")


class VPSBackupNextSensor(VPSBaseEntity):
    _attr_name = "VPS Backup Next"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_backup_next"

    @property
    def native_value(self):
        value = self.coordinator.data.get("backup", {}).get("next_run")
        return dt_util.parse_datetime(value) if value else None


class VPSStatsUpdatedSensor(VPSBaseEntity):
    _attr_name = "VPS Stats Last Check"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_stats_last_check"

    @property
    def native_value(self):
        value = self.coordinator.data.get("updated_at")
        return dt_util.parse_datetime(value) if value else None


class VPSFreshnessSensor(VPSBaseEntity):
    _attr_name = "VPS Status Age"
    _attr_native_unit_of_measurement = "min"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_status_age"

    @property
    def native_value(self):
        value = self.coordinator.data.get("updated_at")
        if not value:
            return None
        timestamp = dt_util.parse_datetime(value)
        if timestamp is None:
            return None
        return round(max(0, (dt_util.utcnow() - timestamp).total_seconds() / 60), 1)

    @property
    def extra_state_attributes(self):
        return {"updated_at": self.coordinator.data.get("updated_at")}
