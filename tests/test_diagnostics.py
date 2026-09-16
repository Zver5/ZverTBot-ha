from __future__ import annotations

import importlib.util
import sys
import types


def load_diagnostics_module():
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object

    update_coordinator = types.ModuleType(
        "homeassistant.helpers.update_coordinator"
    )
    update_coordinator.DataUpdateCoordinator = object

    homeassistant = types.ModuleType("homeassistant")
    helpers = types.ModuleType("homeassistant.helpers")

    package = types.ModuleType("zvertbotvps")
    package.__path__ = []
    const = types.ModuleType("zvertbotvps.const")
    const.DOMAIN = "zvertbotvps"

    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.config_entries": config_entries,
            "homeassistant.core": core,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.update_coordinator": update_coordinator,
            "zvertbotvps": package,
            "zvertbotvps.const": const,
        }
    )

    spec = importlib.util.spec_from_file_location(
        "zvertbotvps.diagnostics",
        "custom_components/zvertbotvps/diagnostics.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_redact_masks_sensitive_values_recursively():
    module = load_diagnostics_module()

    data = {
        "host": "10.0.0.1",
        "nested": {
            "ip": "192.0.2.10",
            "endpoint": "https://secret.example",
            "public_key": "ssh-ed25519 AAAA-secret",
        },
        "clients": [
            {"last_ip": "198.51.100.10"},
            {"uuid": "secret-uuid"},
        ],
        "safe": "visible",
    }

    result = module._redact(data)

    assert result["host"] == "**REDACTED**"
    assert result["nested"]["ip"] == "**REDACTED**"
    assert result["nested"]["endpoint"] == "**REDACTED**"
    assert result["nested"]["public_key"] == "**REDACTED**"
    assert result["clients"][0]["last_ip"] == "**REDACTED**"
    assert result["clients"][1]["uuid"] == "**REDACTED**"
    assert result["safe"] == "visible"


def test_config_entry_diagnostics_include_connection_state():
    module = load_diagnostics_module()

    class Coordinator:
        mode = "ssh"
        update_interval = None
        last_update_success = False
        data = {"server": {"ip": "192.0.2.10"}}
        connection_state = "paused"
        last_success = "2026-09-16T20:00:00+00:00"
        last_error = "connection refused"
        consecutive_failures = 3
        next_retry = "2026-09-16T20:10:00+00:00"

    class Entry:
        entry_id = "test-entry"
        title = "Test VPS"
        data = {"mode": "ssh", "host": "192.0.2.10"}
        options = {}

    class Hass:
        data = {
            "zvertbotvps": {
                "test-entry": Coordinator(),
            }
        }

    result = __import__("asyncio").run(
        module.async_get_config_entry_diagnostics(Hass(), Entry())
    )

    connection = result["coordinator"]["connection"]

    assert connection == {
        "state": "paused",
        "last_success": "2026-09-16T20:00:00+00:00",
        "last_error": "connection refused",
        "consecutive_failures": 3,
        "next_retry": "2026-09-16T20:10:00+00:00",
    }
