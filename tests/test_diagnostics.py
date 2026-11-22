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
            "key_path": "/config/ssh/vps_key",
            "status_url": "http://10.0.0.1:8080/status",
            "username": "root",
            "name": "Private client",
            "email": "client@example.com",
            "display_ip": "198.51.100.20",
            "geoip": {"city": "Private City", "isp": "Private ISP"},
            "geo": {"city": "Another City", "isp": "Another ISP"},
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
    assert result["nested"]["key_path"] == "**REDACTED**"
    assert result["nested"]["status_url"] == "**REDACTED**"
    assert result["nested"]["username"] == "**REDACTED**"
    for key in ("name", "email", "display_ip", "geoip", "geo"):
        assert result["nested"][key] == "**REDACTED**"
    assert result["clients"][0]["last_ip"] == "**REDACTED**"
    assert result["clients"][1]["uuid"] == "**REDACTED**"
    assert result["safe"] == "visible"


def test_config_entry_diagnostics_include_connection_state_without_error_text():
    module = load_diagnostics_module()

    class Coordinator:
        mode = "ssh"
        update_interval = None
        last_update_success = False
        data = {"server": {"ip": "192.0.2.10"}}
        connection_state = "paused"
        last_success = "2026-09-16T20:00:00+00:00"
        last_error = "ssh: connect to host 192.0.2.10 port 22: Connection refused"
        consecutive_failures = 3
        next_retry = "2026-09-16T20:10:00+00:00"

    class Entry:
        entry_id = "test-entry"
        title = "ZverTBot VPS 192.0.2.10"
        data = {"mode": "ssh", "host": "192.0.2.10", "username": "root"}
        options = {"username": "admin"}

    class Hass:
        data = {
            "zvertbotvps": {
                "test-entry": Coordinator(),
            }
        }

    result = __import__("asyncio").run(
        module.async_get_config_entry_diagnostics(Hass(), Entry())
    )

    assert result["entry"]["title"] == "ZverTBot VPS"
    assert result["entry"]["data"]["username"] == "**REDACTED**"
    assert result["entry"]["options"]["username"] == "**REDACTED**"

    connection = result["coordinator"]["connection"]

    assert connection == {
        "state": "paused",
        "last_success": "2026-09-16T20:00:00+00:00",
        "consecutive_failures": 3,
        "next_retry": "2026-09-16T20:10:00+00:00",
    }
    assert "last_error" not in connection
    assert "192.0.2.10" not in str(result)


def test_diagnostics_exclude_vpn_client_collections():
    module = load_diagnostics_module()

    private_client = {
        "name": "Alice",
        "email": "alice@example.com",
        "display_ip": "203.0.113.8",
        "geoip": {"city": "Example City", "isp": "Example ISP"},
        "uuid": "private-client-uuid",
    }

    class Coordinator:
        mode = "ssh"
        update_interval = None
        last_update_success = True
        data = {
            "server": {"cpu": 12},
            "awg": {"clients": [private_client]},
            "xray": {"clients": [private_client]},
            "connections": [private_client],
            "services": {"xray": {"status": "active"}},
        }
        connection_state = "connected"
        last_success = "2026-11-22T08:00:00+00:00"
        last_error = None
        consecutive_failures = 0
        next_retry = None

    class Entry:
        entry_id = "test-entry"
        title = "ZverTBot VPS"
        data = {"mode": "ssh"}
        options = {}

    class Hass:
        data = {"zvertbotvps": {"test-entry": Coordinator()}}

    result = __import__("asyncio").run(
        module.async_get_config_entry_diagnostics(Hass(), Entry())
    )
    data = result["coordinator"]["data"]

    assert data["server"]["cpu"] == 12
    assert data["services"]["xray"]["status"] == "active"
    assert "awg" not in data
    assert "xray" not in data
    assert "connections" not in data
    assert "Alice" not in str(result)
    assert "alice@example.com" not in str(result)
    assert "203.0.113.8" not in str(result)
    assert "Example City" not in str(result)
    assert "Example ISP" not in str(result)
    assert "private-client-uuid" not in str(result)
