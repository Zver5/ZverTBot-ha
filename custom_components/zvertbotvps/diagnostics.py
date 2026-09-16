from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN


_REDACT_KEYS = {
    "host",
    "ip",
    "last_ip",
    "endpoint",
    "server_ip",
    "uuid",
    "id",
    "public_key",
    "key_path",
    "status_url",
}


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: (
                "**REDACTED**"
                if str(key).lower() in _REDACT_KEYS
                else _redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a ZverTBot VPS entry."""
    coordinator: DataUpdateCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )

    result: dict[str, Any] = {
        "entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "data": _redact(dict(entry.data)),
            "options": _redact(dict(entry.options)),
        }
    }

    if coordinator is None:
        result["coordinator"] = None
        return result

    result["coordinator"] = {
        "mode": getattr(coordinator, "mode", None),
        "update_interval": (
            coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None
        ),
        "last_update_success": coordinator.last_update_success,
        "connection": {
            "state": getattr(coordinator, "connection_state", None),
            "last_success": getattr(coordinator, "last_success", None),
            "last_error": getattr(coordinator, "last_error", None),
            "consecutive_failures": getattr(
                coordinator, "consecutive_failures", 0
            ),
            "next_retry": getattr(coordinator, "next_retry", None),
        },
        "data": _redact(coordinator.data),
    }

    return result
