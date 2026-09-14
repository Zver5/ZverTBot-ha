from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    DEFAULT_HTTP_TIMEOUT,
    DEFAULT_SSH_HOST,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SSH_KEY_PATH,
    DEFAULT_SSH_PORT,
    DEFAULT_SSH_USERNAME,
    DEFAULT_STATUS_URL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    MODE_SSH,
    MODE_TUNNEL,
)
from .keygen import SSHKeyGenerationError, generate_ssh_key_pair
from .normalize import normalize_status
from .ssh import SSHStatusClient, SSHStatusError, SSHStatusResponseError, read_vps_status


class CannotConnect(HomeAssistantError):
    """Connection failed."""


class InvalidResponse(HomeAssistantError):
    """VPS status response was invalid."""


_LOGGER = logging.getLogger(__name__)


class ZverTBotConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 5

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        from . import ZverTBotOptionsFlow
        return ZverTBotOptionsFlow()

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self._mode = user_input["mode"]
            return await (
                self.async_step_ssh()
                if self._mode == MODE_SSH
                else self.async_step_tunnel()
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("mode", default=MODE_TUNNEL): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[MODE_TUNNEL, MODE_SSH],
                            translation_key="connection_mode",
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_tunnel(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = await self._test_tunnel(user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidResponse:
                errors["base"] = "invalid_response"
            else:
                server_ip = str(data.get("server", {}).get("ip", ""))
                await self.async_set_unique_id(f"zvertbotvps:{server_ip or user_input['status_url']}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"ZverTBot VPS {server_ip}" if server_ip else "ZverTBot VPS",
                    data={"mode": MODE_TUNNEL, "status_url": user_input["status_url"]},
                    options={
                        "status_url": user_input["status_url"],
                        "poll_interval": int(user_input["poll_interval"]),
                        "http_timeout": int(user_input["http_timeout"]),
                    },
                )
        return self.async_show_form(
            step_id="tunnel",
            data_schema=vol.Schema(
                {
                    vol.Required("status_url", default=DEFAULT_STATUS_URL): str,
                    vol.Required("poll_interval", default=DEFAULT_POLL_INTERVAL): vol.All(vol.Coerce(int), vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL)),
                    vol.Required("http_timeout", default=DEFAULT_HTTP_TIMEOUT): vol.All(vol.Coerce(int), vol.Range(min=3, max=60)),
                }
            ),
            errors=errors,
        )

    async def async_step_ssh(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            values = {
                **user_input,
                "host": str(user_input["host"]).strip(),
                "username": str(user_input["username"]).strip(),
            }

            if not values["host"]:
                errors["host"] = "required"
            elif not values["username"]:
                errors["username"] = "required"

            if errors:
                return self.async_show_form(
                    step_id="ssh",
                    data_schema=self._ssh_schema(values),
                    errors=errors,
                )

            self._ssh_data = values
            return await self.async_step_ssh_key()

        return self.async_show_form(
            step_id="ssh",
            data_schema=self._ssh_schema(),
            errors=errors,
        )

    async def async_step_ssh_key(self, user_input=None):
        if user_input is not None:
            if user_input["source"] == "create":
                return await self.async_step_ssh_key_create()

            return await self.async_step_ssh_key_existing()

        return self.async_show_form(
            step_id="ssh_key",
            data_schema=vol.Schema(
                {
                    vol.Required("source", default="existing"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["existing", "create"],
                            translation_key="ssh_key_source",
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_ssh_key_existing(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            key_path = str(user_input["key_path"]).strip()

            if not key_path:
                errors["key_path"] = "required"
            else:
                self._ssh_data["key_path"] = key_path
                self._ssh_key_source = "existing"
                return await self._finish_ssh_setup()

        return self.async_show_form(
            step_id="ssh_key_existing",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "key_path",
                        default=DEFAULT_SSH_KEY_PATH,
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_ssh_key_create(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            key_name = str(user_input["key_name"]).strip()

            if not key_name:
                errors["key_name"] = "required"
            elif Path(key_name).name != key_name or key_name in {".", ".."}:
                errors["key_name"] = "invalid_key_name"
            else:
                key_path = Path("/config/ssh") / key_name
                try:
                    await asyncio.to_thread(
                        key_path.parent.mkdir,
                        parents=True,
                        exist_ok=True,
                    )
                    public_key = await asyncio.to_thread(
                        generate_ssh_key_pair,
                        key_path,
                    )
                except (SSHKeyGenerationError, OSError) as err:
                    errors["base"] = "key_generation_failed"
                    # Keep the detailed reason in logs, never in the UI.
                    _LOGGER.exception("Unable to create SSH key at %s: %s", key_path, err)
                else:
                    self._ssh_data["key_path"] = str(key_path)
                    self._public_key = public_key
                    self._ssh_key_source = "create"
                    return await self.async_step_ssh_key_public()

            if errors:
                return self.async_show_form(
                    step_id="ssh_key_create",
                    data_schema=vol.Schema(
                        {
                            vol.Required(
                                "key_name",
                                default=key_name,
                            ): str,
                        }
                    ),
                    errors=errors,
                )

        return self.async_show_form(
            step_id="ssh_key_create",
            data_schema=vol.Schema(
                {
                    vol.Required("key_name", default="vps_key"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_ssh_key_public(
        self, user_input=None, errors=None
    ):
        if user_input is not None:
            return await self._finish_ssh_setup()

        return self.async_show_form(
            step_id="ssh_key_public",
            data_schema=vol.Schema({}),
            errors=errors or {},
            description_placeholders={
                "key_path": self._ssh_data["key_path"],
                "public_key": self._public_key,
            },
        )

    async def _finish_ssh_setup(self):
        try:
            data = await self._test_ssh(self._ssh_data)
        except CannotConnect:
            if getattr(self, "_ssh_key_source", None) == "create":
                return await self.async_step_ssh_key_public(
                    errors={"base": "cannot_connect"}
                )
            return self.async_show_form(
                step_id="ssh_key_existing",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            "key_path",
                            default=self._ssh_data["key_path"],
                        ): str,
                    }
                ),
                errors={"base": "cannot_connect"},
            )
        except InvalidResponse:
            if getattr(self, "_ssh_key_source", None) == "create":
                return await self.async_step_ssh_key_public(
                    errors={"base": "invalid_response"}
                )
            return self.async_show_form(
                step_id="ssh_key_existing",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            "key_path",
                            default=self._ssh_data["key_path"],
                        ): str,
                    }
                ),
                errors={"base": "invalid_response"},
            )

        server_ip = str(data.get("server", {}).get("ip", ""))
        host = str(self._ssh_data["host"]).strip()
        await self.async_set_unique_id(f"zvertbotvps:{server_ip or host}")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"ZverTBot VPS {server_ip or host}",
            data={
                "mode": MODE_SSH,
                "host": host,
                "port": int(self._ssh_data["port"]),
                "username": str(self._ssh_data["username"]),
                "key_path": str(self._ssh_data["key_path"]),
            },
            options={
                "poll_interval": int(self._ssh_data["poll_interval"]),
            },
        )

    @staticmethod
    def _ssh_schema(current: dict | None = None) -> vol.Schema:
        current = current or {}
        return vol.Schema(
            {
                vol.Required("host", default=current.get("host", DEFAULT_SSH_HOST)): str,
                vol.Required("port", default=int(current.get("port", DEFAULT_SSH_PORT))): vol.Coerce(int),
                vol.Required(
                    "username",
                    default=current.get("username", DEFAULT_SSH_USERNAME),
                ): str,
                vol.Required(
                    "poll_interval",
                    default=int(current.get("poll_interval", DEFAULT_POLL_INTERVAL)),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
                ),
            }
        )

    async def _test_tunnel(self, user_input: dict) -> dict:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(str(user_input["status_url"]), timeout=int(user_input["http_timeout"])) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
        except Exception as err:
            raise CannotConnect from err
        if not isinstance(data, dict) or not isinstance(data.get("server"), dict):
            raise InvalidResponse
        return normalize_status(data)

    async def _test_ssh(self, user_input: dict) -> dict:
        host = str(user_input["host"]).strip()
        key_path = Path(str(user_input["key_path"])).expanduser()
        if not host or not key_path.is_file():
            raise CannotConnect
        try:
            return await asyncio.to_thread(
                read_vps_status,
                host,
                str(user_input["username"]),
                str(key_path),
                int(user_input["port"]),
            )
        except SSHStatusResponseError as err:
            raise InvalidResponse from err
        except SSHStatusError as err:
            raise CannotConnect from err
