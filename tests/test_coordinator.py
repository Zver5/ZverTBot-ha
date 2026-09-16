from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
PACKAGE = "custom_components.zvertbotvps"


def load_module():
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT / "custom_components" / "zvertbotvps")]
    sys.modules[PACKAGE] = package

    const = types.ModuleType(f"{PACKAGE}.const")
    const.DEFAULT_HTTP_TIMEOUT = 10
    const.DEFAULT_POLL_INTERVAL = 60
    const.DEFAULT_SSH_BACKOFF = 600
    const.DEFAULT_SSH_KEY_PATH = "/config/ssh/vps_key"
    const.DEFAULT_SSH_PORT = 22
    const.DEFAULT_SSH_USERNAME = "root"
    const.DEFAULT_STATUS_URL = "http://127.0.0.1:8080/vps-status.json"
    const.DOMAIN = "zvertbotvps"
    const.MODE_SSH = "ssh"
    sys.modules[f"{PACKAGE}.const"] = const

    normalize = types.ModuleType(f"{PACKAGE}.normalize")

    def normalize_status(value):
        return value

    normalize.normalize_status = normalize_status
    sys.modules[f"{PACKAGE}.normalize"] = normalize

    ssh = types.ModuleType(f"{PACKAGE}.ssh")

    class SSHStatusError(Exception):
        pass

    class SSHStatusResponseError(SSHStatusError):
        pass

    class SSHStatusClient:
        def __init__(self, host, username, key_path, port):
            self.host = host
            self.username = username
            self.key_path = key_path
            self.port = port

        def read(self):
            raise NotImplementedError

        def close(self):
            pass

    ssh.SSHStatusClient = SSHStatusClient
    ssh.SSHStatusError = SSHStatusError
    ssh.SSHStatusResponseError = SSHStatusResponseError
    sys.modules[f"{PACKAGE}.ssh"] = ssh

    aiohttp = types.ModuleType("aiohttp")

    class ClientError(Exception):
        pass

    aiohttp.ClientError = ClientError
    sys.modules["aiohttp"] = aiohttp

    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object

    aiohttp_client = types.ModuleType(
        "homeassistant.helpers.aiohttp_client"
    )
    aiohttp_client.async_get_clientsession = lambda hass: None

    update_coordinator = types.ModuleType(
        "homeassistant.helpers.update_coordinator"
    )

    class UpdateFailed(Exception):
        pass

    class DataUpdateCoordinator:
        @classmethod
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, *args, **kwargs):
            self.data = {}
            self.update_interval = kwargs.get("update_interval")
            self.last_update_success = None

        async def async_shutdown(self):
            pass

    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.UpdateFailed = UpdateFailed

    homeassistant = types.ModuleType("homeassistant")
    helpers = types.ModuleType("homeassistant.helpers")

    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.config_entries": config_entries,
            "homeassistant.core": core,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.aiohttp_client": aiohttp_client,
            "homeassistant.helpers.update_coordinator": update_coordinator,
        }
    )

    path = ROOT / "custom_components" / "zvertbotvps" / "coordinator.py"
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE}.coordinator",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{PACKAGE}.coordinator"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_entry(mode="tunnel"):
    class Entry:
        data = {
            "mode": mode,
            "host": "example",
            "username": "root",
            "key_path": "/tmp/key",
            "port": 22,
        }
        options = {}

    return Entry()


def make_coordinator(module, mode="tunnel"):
    return module.ZverTBotCoordinator(object(), make_entry(mode))


def test_initial_connection_state_is_unknown():
    module = load_module()

    coordinator = make_coordinator(module)

    assert coordinator.connection_state == "unknown"
    assert coordinator.last_success is None
    assert coordinator.last_error is None
    assert coordinator.consecutive_failures == 0
    assert coordinator.next_retry is None


def test_tunnel_success_marks_connection_connected(monkeypatch):
    module = load_module()
    coordinator = make_coordinator(module)

    class Response:
        def raise_for_status(self):
            pass

        async def json(self, content_type=None):
            return {"server": {"ip": "192.0.2.1"}}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    coordinator.session = Session()

    result = asyncio.run(coordinator._async_update_tunnel())

    assert result["server"]["ip"] == "192.0.2.1"
    assert coordinator.connection_state == "connected"
    assert coordinator.last_success is not None
    assert coordinator.last_error is None
    assert coordinator.consecutive_failures == 0


def test_tunnel_failure_marks_connection_failed():
    module = load_module()
    coordinator = make_coordinator(module)

    class Session:
        def get(self, *args, **kwargs):
            raise module.ClientError("connection refused")

    coordinator.session = Session()

    with pytest.raises(module.UpdateFailed, match="connection refused"):
        asyncio.run(coordinator._async_update_tunnel())

    assert coordinator.connection_state == "failed"
    assert coordinator.last_success is None
    assert coordinator.last_error == "connection refused"
    assert coordinator.consecutive_failures == 1


def test_tunnel_failures_increment_and_success_resets_counter():
    module = load_module()
    coordinator = make_coordinator(module)

    class FailingSession:
        def get(self, *args, **kwargs):
            raise module.ClientError("timeout")

    coordinator.session = FailingSession()

    for expected in (1, 2):
        with pytest.raises(module.UpdateFailed):
            asyncio.run(coordinator._async_update_tunnel())
        assert coordinator.consecutive_failures == expected

    class Response:
        def raise_for_status(self):
            pass

        async def json(self, content_type=None):
            return {"server": {"ip": "192.0.2.1"}}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class WorkingSession:
        def get(self, *args, **kwargs):
            return Response()

    coordinator.session = WorkingSession()

    asyncio.run(coordinator._async_update_tunnel())

    assert coordinator.connection_state == "connected"
    assert coordinator.consecutive_failures == 0
    assert coordinator.last_error is None
    assert coordinator.last_success is not None


def test_invalid_tunnel_payload_marks_connection_failed():
    module = load_module()
    coordinator = make_coordinator(module)

    class Response:
        def raise_for_status(self):
            pass

        async def json(self, content_type=None):
            return {"system": {}}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    coordinator.session = Session()

    with pytest.raises(module.UpdateFailed, match="invalid"):
        asyncio.run(coordinator._async_update_tunnel())

    assert coordinator.connection_state == "failed"
    assert coordinator.consecutive_failures == 1
    assert "invalid" in coordinator.last_error


def test_ssh_failure_enters_backoff_and_sets_next_retry(monkeypatch):
    module = load_module()
    coordinator = make_coordinator(module, "ssh")

    calls = []

    class Client:
        def read(self):
            calls.append("read")
            raise module.SSHStatusError("connection refused")

        def close(self):
            calls.append("close")

    coordinator._ssh_client = Client()

    with pytest.raises(module.UpdateFailed, match="Unable to read VPS status"):
        asyncio.run(coordinator._async_update_ssh())

    assert calls == ["read", "close"]
    assert coordinator.connection_state == "paused"
    assert coordinator.last_error == "connection refused"
    assert coordinator.consecutive_failures == 1
    assert coordinator.next_retry is not None

    retry_at = datetime.fromisoformat(coordinator.next_retry)
    assert retry_at.tzinfo is not None
    assert retry_at > datetime.now(timezone.utc)


def test_ssh_backoff_prevents_second_connection_attempt():
    module = load_module()
    coordinator = make_coordinator(module, "ssh")

    calls = []

    class Client:
        def read(self):
            calls.append("read")
            raise module.SSHStatusError("connection refused")

        def close(self):
            calls.append("close")

    coordinator._ssh_client = Client()

    with pytest.raises(module.UpdateFailed):
        asyncio.run(coordinator._async_update_ssh())

    with pytest.raises(module.UpdateFailed, match="reconnect paused"):
        asyncio.run(coordinator._async_update_ssh())

    assert calls == ["read", "close"]
    assert coordinator.connection_state == "paused"
    assert coordinator.consecutive_failures == 1


def test_ssh_success_clears_failure_state_and_retry():
    module = load_module()
    coordinator = make_coordinator(module, "ssh")

    class Client:
        def read(self):
            return {"server": {"ip": "192.0.2.1"}}

        def close(self):
            pass

    coordinator._ssh_client = Client()

    result = asyncio.run(coordinator._async_update_ssh())

    assert result["server"]["ip"] == "192.0.2.1"
    assert coordinator.connection_state == "connected"
    assert coordinator.last_success is not None
    assert coordinator.last_error is None
    assert coordinator.consecutive_failures == 0
    assert coordinator.next_retry is None


def test_ssh_invalid_payload_marks_connection_failed():
    module = load_module()
    coordinator = make_coordinator(module, "ssh")

    class Client:
        def read(self):
            return {"system": {}}

        def close(self):
            pass

    coordinator._ssh_client = Client()

    with pytest.raises(module.UpdateFailed, match="invalid"):
        asyncio.run(coordinator._async_update_ssh())

    assert coordinator.connection_state == "failed"
    assert coordinator.last_error is not None
    assert "invalid" in coordinator.last_error
    assert coordinator.consecutive_failures == 1
