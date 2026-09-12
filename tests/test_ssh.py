import importlib.util
import json
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
    const.DEFAULT_SSH_PORT = 22
    const.DEFAULT_SSH_USERNAME = "root"
    sys.modules[f"{PACKAGE}.const"] = const

    normalize = types.ModuleType(f"{PACKAGE}.normalize")

    def normalize_status(value):
        return value

    normalize.normalize_status = normalize_status
    sys.modules[f"{PACKAGE}.normalize"] = normalize

    path = ROOT / "custom_components" / "zvertbotvps" / "ssh.py"
    spec = importlib.util.spec_from_file_location(f"{PACKAGE}.ssh", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{PACKAGE}.ssh"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_keygen_module():
    path = ROOT / "custom_components" / "zvertbotvps" / "keygen.py"
    spec = importlib.util.spec_from_file_location(f"{PACKAGE}.keygen", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{PACKAGE}.keygen"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_ssh_command_uses_vps_status_endpoint():
    module = load_module()

    client = module.SSHStatusClient(
        "192.0.2.1",
        "root",
        "/root/.ssh/vps_key",
        2222,
    )

    command = client._ssh_command()

    assert command[0] == "/usr/bin/ssh"
    assert command[1:4] == ["-i", "/root/.ssh/vps_key", "-p"]
    assert command[4] == "2222"
    assert "root@192.0.2.1" in command
    assert command[-1].endswith(
        "http://127.0.0.1:8080/vps-status.json"
    )


def test_read_fails_when_ssh_key_is_missing(tmp_path):
    module = load_module()

    client = module.SSHStatusClient(
        "example",
        "root",
        str(tmp_path / "missing_key"),
    )

    try:
        client.read()
    except module.SSHStatusError as err:
        assert "SSH key not found" in str(err)
    else:
        raise AssertionError("Expected SSHStatusError")


def test_read_parses_valid_response(tmp_path, monkeypatch):
    module = load_module()

    key = tmp_path / "key"
    key.write_text("test")

    payload = {
        "server": {"ip": "192.0.2.1"},
        "system": {},
    }

    class Result:
        returncode = 0
        stdout = json.dumps(payload)
        stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: Result())

    client = module.SSHStatusClient(
        "example",
        "root",
        str(key),
    )

    assert client.read() == payload


def test_read_rejects_invalid_json(tmp_path, monkeypatch):
    module = load_module()

    key = tmp_path / "key"
    key.write_text("test")

    class Result:
        returncode = 0
        stdout = "{not-json"
        stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: Result())

    client = module.SSHStatusClient(
        "example",
        "root",
        str(key),
    )

    try:
        client.read()
    except module.SSHStatusResponseError as err:
        assert "invalid JSON" in str(err)
    else:
        raise AssertionError("Expected SSHStatusError")


def test_read_rejects_invalid_vps_payload(tmp_path, monkeypatch):
    module = load_module()

    key = tmp_path / "key"
    key.write_text("test")

    class Result:
        returncode = 0
        stdout = json.dumps({"system": {}})
        stderr = ""

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: Result())

    client = module.SSHStatusClient(
        "example",
        "root",
        str(key),
    )

    try:
        client.read()
    except module.SSHStatusResponseError as err:
        assert "invalid status response" in str(err)
    else:
        raise AssertionError("Expected SSHStatusError")


def test_read_vps_status_uses_one_client_and_closes(monkeypatch):
    module = load_module()

    calls = []

    class FakeClient:
        def __init__(self, host, username, key_path, port):
            calls.append(("init", host, username, key_path, port))

        def read(self):
            calls.append(("read",))
            return {"server": {"ip": "192.0.2.1"}}

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(module, "SSHStatusClient", FakeClient)

    result = module.read_vps_status(
        "example",
        "root",
        "/tmp/key",
        22,
    )

    assert result == {"server": {"ip": "192.0.2.1"}}
    assert calls == [
        ("init", "example", "root", "/tmp/key", 22),
        ("read",),
        ("close",),
    ]


def test_default_ssh_key_path_is_container_accessible():
    const_path = ROOT / "custom_components" / "zvertbotvps" / "const.py"
    namespace = {}
    exec(compile(const_path.read_text(), const_path, "exec"), namespace)

    assert namespace["DEFAULT_SSH_KEY_PATH"] == "/config/ssh/vps_key"


def test_generate_ssh_key_pair_creates_ed25519_key(tmp_path):
    module = load_keygen_module()

    private_key = tmp_path / "zvertbot_vps"

    public_key = module.generate_ssh_key_pair(private_key)

    assert private_key.is_file()
    assert Path(f"{private_key}.pub").is_file()
    assert public_key.startswith("ssh-ed25519 ")
    assert private_key.stat().st_mode & 0o777 == 0o600


def test_generate_ssh_key_pair_cleans_partial_files_on_ssh_keygen_failure(
    tmp_path, monkeypatch
):
    module = load_keygen_module()
    private_key = tmp_path / "zvertbot_vps"
    public_key = Path(f"{private_key}.pub")

    class Result:
        returncode = 1
        stdout = ""
        stderr = "ssh-keygen failed"

    def fake_run(*args, **kwargs):
        private_key.write_text("partial", encoding="utf-8")
        public_key.write_text("partial", encoding="utf-8")
        return Result()

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    try:
        module.generate_ssh_key_pair(private_key)
    except module.SSHKeyGenerationError as err:
        assert "ssh-keygen failed" in str(err)
    else:
        raise AssertionError("Expected SSHKeyGenerationError")

    assert not private_key.exists()
    assert not public_key.exists()


def test_generate_ssh_key_pair_refuses_existing_key(tmp_path):
    module = load_keygen_module()

    private_key = tmp_path / "zvertbot_vps"
    private_key.write_text("existing", encoding="utf-8")

    try:
        module.generate_ssh_key_pair(private_key)
    except module.SSHKeyGenerationError as err:
        assert "already exists" in str(err)
    else:
        raise AssertionError("Expected SSHKeyGenerationError")
