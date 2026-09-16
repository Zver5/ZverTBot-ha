from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).parents[1]
PACKAGE = "custom_components.zvertbotvps"


def load_module():
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT / "custom_components" / "zvertbotvps")]
    sys.modules[PACKAGE] = package

    const = types.ModuleType(f"{PACKAGE}.const")
    const.DOMAIN = "zvertbotvps"
    sys.modules[f"{PACKAGE}.const"] = const

    coordinator_module = types.ModuleType(f"{PACKAGE}.coordinator")

    class ZverTBotCoordinator:
        pass

    coordinator_module.ZverTBotCoordinator = ZverTBotCoordinator
    sys.modules[f"{PACKAGE}.coordinator"] = coordinator_module

    binary_sensor = types.ModuleType("homeassistant.components.binary_sensor")

    class BinarySensorDeviceClass:
        CONNECTIVITY = "connectivity"
        RUNNING = "running"

    class BinarySensorEntity:
        pass

    binary_sensor.BinarySensorDeviceClass = BinarySensorDeviceClass
    binary_sensor.BinarySensorEntity = BinarySensorEntity

    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object

    update_coordinator = types.ModuleType(
        "homeassistant.helpers.update_coordinator"
    )

    class CoordinatorEntity:
        @classmethod
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, coordinator):
            self.coordinator = coordinator

    update_coordinator.CoordinatorEntity = CoordinatorEntity

    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    helpers = types.ModuleType("homeassistant.helpers")

    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.components": components,
            "homeassistant.components.binary_sensor": binary_sensor,
            "homeassistant.config_entries": config_entries,
            "homeassistant.core": core,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.update_coordinator": update_coordinator,
        }
    )

    path = ROOT / "custom_components" / "zvertbotvps" / "binary_sensor.py"
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE}.binary_sensor",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{PACKAGE}.binary_sensor"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_coordinator(module, state="connected"):
    class Entry:
        entry_id = "test-entry"

    class Coordinator(module.ZverTBotCoordinator):
        entry = Entry()
        mode = "ssh"
        connection_state = state
        last_success = "2026-09-16T20:00:00+00:00"
        last_error = "connection refused" if state != "connected" else None
        consecutive_failures = 3 if state != "connected" else 0
        next_retry = (
            "2026-09-16T20:10:00+00:00" if state == "paused" else None
        )

    return Coordinator()


def test_connection_binary_sensor_is_on_only_when_connected():
    module = load_module()

    connected = module.VPSConnectionBinarySensor(
        make_coordinator(module, "connected")
    )
    failed = module.VPSConnectionBinarySensor(
        make_coordinator(module, "failed")
    )
    paused = module.VPSConnectionBinarySensor(
        make_coordinator(module, "paused")
    )

    assert connected.is_on is True
    assert failed.is_on is False
    assert paused.is_on is False


def test_connection_binary_sensor_exposes_diagnostics():
    module = load_module()

    sensor = module.VPSConnectionBinarySensor(
        make_coordinator(module, "paused")
    )

    assert sensor.extra_state_attributes == {
        "state": "paused",
        "mode": "ssh",
        "last_success": "2026-09-16T20:00:00+00:00",
        "last_error": "connection refused",
        "consecutive_failures": 3,
        "next_retry": "2026-09-16T20:10:00+00:00",
    }


def test_connection_binary_sensor_has_stable_identity():
    module = load_module()

    sensor = module.VPSConnectionBinarySensor(
        make_coordinator(module, "connected")
    )

    assert sensor._attr_unique_id == "test-entry_connection"
    assert sensor._attr_name == "Connection"
    assert sensor._attr_device_class == "connectivity"
