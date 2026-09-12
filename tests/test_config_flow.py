from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FLOW = ROOT / "custom_components" / "zvertbotvps" / "config_flow.py"


def read_config_flow() -> str:
    return CONFIG_FLOW.read_text(encoding="utf-8")


def test_config_flow_has_ssh_key_source_step():
    source = read_config_flow()

    assert "async def async_step_ssh_key(" in source
    assert 'translation_key="ssh_key_source"' in source
    assert '"existing"' in source
    assert '"create"' in source


def test_config_flow_has_ssh_key_creation_step():
    source = read_config_flow()

    assert "async def async_step_ssh_key_create(" in source
    assert "generate_ssh_key_pair" in source
    assert "SSHKeyGenerationError" in source


def test_config_flow_has_public_key_step():
    source = read_config_flow()

    assert "async def async_step_ssh_key_public(" in source
    assert "public_key" in source
    assert "key_path" in source


def test_config_flow_routes_direct_ssh_to_key_selection():
    source = read_config_flow()

    ssh_marker = "async def async_step_ssh("
    ssh_start = source.index(ssh_marker)
    ssh_end = source.index("\n    @staticmethod", ssh_start)
    ssh_source = source[ssh_start:ssh_end]

    assert "async_step_ssh_key" in ssh_source


def test_config_flow_new_errors_have_translations():
    import json

    for language in ("ru", "en"):
        path = (
            ROOT
            / "custom_components"
            / "zvertbotvps"
            / "translations"
            / f"{language}.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        errors = data["config"]["error"]

        assert errors["invalid_key_name"]
        assert errors["key_generation_failed"]



def test_ssh_key_create_generates_key_and_stores_public_key():
    source = read_config_flow()

    start = source.index("    async def async_step_ssh_key_create(")
    end = source.index("\n    async def async_step_ssh_key_public(", start)
    block = source[start:end]

    assert "generate_ssh_key_pair" in block
    assert "await asyncio.to_thread(" in block
    assert 'Path("/config/ssh") / key_name' in block
    assert 'self._ssh_data["key_path"] = str(key_path)' in block
    assert "self._public_key = public_key" in block
    assert "return await self.async_step_ssh_key_public()" in block


def test_ssh_key_source_routes_existing_and_create_correctly():
    source = read_config_flow()

    start = source.index("    async def async_step_ssh_key(")
    end = source.index("\n    async def async_step_ssh_key_create(", start)
    block = source[start:end]

    assert 'user_input["source"] == "create"' in block
    assert "return await self.async_step_ssh_key_create()" in block
    assert "return await self._finish_ssh_setup()" in block


def test_ssh_key_public_step_passes_generated_key_to_description():
    source = read_config_flow()

    start = source.index("    async def async_step_ssh_key_public(")
    end = source.index("\n    async def _finish_ssh_setup(", start)
    block = source[start:end]

    assert 'step_id="ssh_key_public"' in block
    assert '"key_path": self._ssh_data["key_path"]' in block
    assert '"public_key": self._public_key' in block
    assert "description_placeholders=" in block


def test_finish_ssh_setup_uses_selected_key_and_creates_ssh_entry():
    source = read_config_flow()

    start = source.index("    async def _finish_ssh_setup(")
    end = source.index("\n    @staticmethod", start)
    block = source[start:end]

    assert "await self._test_ssh(self._ssh_data)" in block
    assert '"key_path": str(self._ssh_data["key_path"])' in block
    assert '"mode": MODE_SSH' in block
    assert '"poll_interval": int(self._ssh_data["poll_interval"])' in block

def test_config_flow_has_existing_key_step():
    source = read_config_flow()

    assert "async def async_step_ssh_key_existing" in source
    assert 'step_id="ssh_key_existing"' in source
    assert 'vol.Required(' in source
    assert '"key_path"' in source


def test_existing_key_step_has_translations():
    import json

    for language in ("ru", "en"):
        path = (
            ROOT
            / "custom_components"
            / "zvertbotvps"
            / "translations"
            / f"{language}.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        step = data["config"]["step"]["ssh_key_existing"]

        assert step["title"]
        assert step["description"]
        assert step["data"]["key_path"]

def test_finish_ssh_setup_preserves_existing_key_on_connection_error():
    source = read_config_flow()
    start = source.index("    async def _finish_ssh_setup(")
    end = source.index("\n    @staticmethod", start)
    block = source[start:end]

    assert 'self._ssh_key_source' in source
    assert 'step_id="ssh_key_existing"' in block
    assert 'default=self._ssh_data["key_path"]' in block
    assert 'errors={"base": "cannot_connect"}' in block


def test_finish_ssh_setup_returns_to_generated_public_key_on_error():
    source = read_config_flow()
    start = source.index("    async def _finish_ssh_setup(")
    end = source.index("\n    @staticmethod", start)
    block = source[start:end]

    assert 'self.async_step_ssh_key_public(' in block
    assert 'errors={"base": "cannot_connect"}' in block
    assert 'errors={"base": "invalid_response"}' in block


def test_generated_key_source_is_recorded():
    source = read_config_flow()

    assert 'self._ssh_key_source = "create"' in source
    assert 'self._ssh_key_source = "existing"' in source


def test_public_key_step_accepts_errors():
    source = read_config_flow()
    start = source.index("    async def async_step_ssh_key_public(")
    end = source.index("\n    async def _finish_ssh_setup(", start)
    block = source[start:end]

    assert "errors=None" in block
    assert "errors=errors or {}" in block
