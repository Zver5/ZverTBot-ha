import importlib.util
import sys
import types
from pathlib import Path


def load_sensor_module():
    package_name = "custom_components.zvertbotvps"

    package = types.ModuleType(package_name)
    package.__path__ = [
        str(Path(__file__).parents[1] / "custom_components" / "zvertbotvps")
    ]
    sys.modules[package_name] = package

    sensor = types.ModuleType("homeassistant.components.sensor")

    class SensorEntity:
        pass

    class SensorDeviceClass:
        TIMESTAMP = "timestamp"

    sensor.SensorEntity = SensorEntity
    sensor.SensorDeviceClass = SensorDeviceClass

    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = type("ConfigEntry", (), {})

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = type("HomeAssistant", (), {})

    const = types.ModuleType("homeassistant.const")
    const.PERCENTAGE = "%"

    update_coordinator = types.ModuleType(
        "homeassistant.helpers.update_coordinator"
    )

    class CoordinatorEntity:
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, coordinator=None):
            self.coordinator = coordinator

    update_coordinator.CoordinatorEntity = CoordinatorEntity

    dt = types.ModuleType("homeassistant.util.dt")

    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    helpers = types.ModuleType("homeassistant.helpers")
    util = types.ModuleType("homeassistant.util")

    homeassistant.components = components
    homeassistant.config_entries = config_entries
    homeassistant.const = const
    homeassistant.core = core
    homeassistant.helpers = helpers
    homeassistant.util = util

    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.components": components,
            "homeassistant.components.sensor": sensor,
            "homeassistant.config_entries": config_entries,
            "homeassistant.const": const,
            "homeassistant.core": core,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.update_coordinator": update_coordinator,
            "homeassistant.util": util,
            "homeassistant.util.dt": dt,
        }
    )

    const_module = types.ModuleType(f"{package_name}.const")
    const_module.DOMAIN = "zvertbotvps"
    sys.modules[f"{package_name}.const"] = const_module

    coordinator_module = types.ModuleType(f"{package_name}.coordinator")

    class ZverTBotCoordinator:
        pass

    coordinator_module.ZverTBotCoordinator = ZverTBotCoordinator
    sys.modules[f"{package_name}.coordinator"] = coordinator_module

    module_name = f"{package_name}.sensor"
    path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "zvertbotvps"
        / "sensor.py"
    )
    spec = importlib.util.spec_from_file_location(
        module_name,
        path,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_all_stats_attributes_exclude_large_duplicate_collections():
    module = load_sensor_module()

    class Coordinator:
        server_ip = "192.0.2.1"
        mode = "tunnel"
        data = {
            "server": {"ip": "192.0.2.1"},
            "system": {},
            "services": {},
            "backup": {},
            "fail2ban": {},
            "connections": [],
            "awg": {
                "clients": [{"name": "Valya", "ip": "10.66.66.4", "total": "68.70 GB"}],
            },
            "xray": {
                "clients": [{"name": "Test", "total": "1 GB"}],
            },
            "awg_clients": [{"name": "Valya", "total": "68.70 GB"}],
            "xray_clients": [{"name": "Test", "total": "1 GB"}],
            "updated_at": "2026-09-12T10:00:00+03:00",
        }

    sensor = object.__new__(module.VPSAllStatsSensor)
    sensor.coordinator = Coordinator()

    attrs = sensor.extra_state_attributes

    assert attrs["server_ip"] == "192.0.2.1"
    assert attrs["updated_at"] == "2026-09-12T10:00:00+03:00"
    assert "peers" not in attrs
    assert "xray_clients" not in attrs
    assert "awg_clients" not in attrs
    assert "awg" not in attrs
    assert "xray" not in attrs


def test_client_identity_distinguishes_clients_with_same_ip():
    module = load_sensor_module()

    first = {
        "name": "Shkurin",
        "ip": "192.0.2.10",
        "proto": "vless",
    }
    second = {
        "name": "ZverX",
        "ip": "192.0.2.10",
        "proto": "vless",
    }

    assert module._client_identity("xray", first) != module._client_identity(
        "xray", second
    )


def test_xray_client_name_uses_normal_casing():
    module = load_sensor_module()

    class Coordinator:
        entry = type("Entry", (), {"entry_id": "test"})()
        data = {
            "xray": {
                "clients": [
                    {
                        "name": "ValyaX",
                        "ip": "192.0.2.10",
                        "total": "1 GB",
                    }
                ]
            }
        }

        def clients(self, kind):
            return self.data.get(kind, {}).get("clients", [])

    sensor = module.VPSClientSensor(
        Coordinator(),
        "xray",
        {"name": "ValyaX", "ip": "192.0.2.10"},
    )

    assert sensor._attr_name == "Xray Client ValyaX"
