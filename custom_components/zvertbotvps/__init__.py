from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, OptionsFlowWithReload
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

import voluptuous as vol

from .config_flow import CannotConnect, InvalidResponse
from .const import (
    DEFAULT_HTTP_TIMEOUT,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SSH_HOST,
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
from .coordinator import ZverTBotCoordinator
from .normalize import normalize_status
from .ssh import SSHStatusClient, SSHStatusError, read_vps_status

PLATFORMS = ["sensor", "binary_sensor"]

_LOGGER = logging.getLogger(__name__)


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up ZverTBot VPS frontend resources."""
    static_path = Path(__file__).parent / "static"
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                "/api/zvertbotvps/static",
                str(static_path),
                False,
            )
        ]
    )
    add_extra_js_url(hass, "/api/zvertbotvps/static/zvertbot-panel.js")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = ZverTBotCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coordinator is not None:
            await coordinator.async_shutdown()
    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.version < 5:
        hass.config_entries.async_update_entry(entry, version=5)
    return True


class ZverTBotOptionsFlow(OptionsFlowWithReload):
    def __init__(self) -> None:
        self._mode = None

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "test_connection"],
        )

    async def async_step_settings(self, user_input=None):
        if user_input is not None:
            self._mode = user_input["mode"]
            return await (
                self.async_step_ssh()
                if self._mode == MODE_SSH
                else self.async_step_tunnel()
            )

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "mode",
                        default=current.get("mode", MODE_TUNNEL),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[MODE_TUNNEL, MODE_SSH],
                            translation_key="connection_mode",
                        )
                    ),
                }
            ),
        )

    async def async_step_tunnel(self, user_input=None):
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    "mode": MODE_TUNNEL,
                    "status_url": str(user_input["status_url"]),
                    "poll_interval": int(user_input["poll_interval"]),
                    "http_timeout": int(user_input["http_timeout"]),
                },
            )
        return self.async_show_form(
            step_id="tunnel",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "status_url",
                        default=str(
                            current.get("status_url", DEFAULT_STATUS_URL)
                        ),
                    ): str,
                    vol.Required(
                        "poll_interval",
                        default=int(
                            current.get("poll_interval", DEFAULT_POLL_INTERVAL)
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_POLL_INTERVAL,
                            max=MAX_POLL_INTERVAL,
                        ),
                    ),
                    vol.Required(
                        "http_timeout",
                        default=int(
                            current.get("http_timeout", DEFAULT_HTTP_TIMEOUT)
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=3, max=60),
                    ),
                }
            ),
        )

    async def async_step_ssh(self, user_input=None):
        current = {**self.config_entry.data, **self.config_entry.options}
        errors: dict[str, str] = {}

        if user_input is not None:
            values = {
                "host": str(user_input["host"]).strip(),
                "port": int(user_input["port"]),
                "username": str(user_input["username"]).strip(),
                "key_path": str(user_input["key_path"]).strip(),
                "poll_interval": int(user_input["poll_interval"]),
            }

            if not values["host"]:
                errors["host"] = "required"
            elif not values["username"]:
                errors["username"] = "required"
            elif not values["key_path"]:
                errors["key_path"] = "required"
            else:
                try:
                    await self._test_ssh(values)
                except SSHStatusError as err:
                    _LOGGER.error(
                        "Direct SSH test failed: host=%s port=%s username=%s "
                        "error=%s",
                        values["host"],
                        values["port"],
                        values["username"],
                        err,
                    )
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(
                        title="",
                        data=values,
                    )

            return self.async_show_form(
                step_id="ssh",
                data_schema=self._ssh_options_schema(values),
                errors=errors,
            )

        return self.async_show_form(
            step_id="ssh",
            data_schema=self._ssh_options_schema(current),
            errors=errors,
        )

    async def async_step_test_connection(self, user_input=None):
        if user_input is not None:
            return await self.async_step_init()

        current = {**self.config_entry.data, **self.config_entry.options}

        try:
            if current.get("mode", MODE_TUNNEL) == MODE_SSH:
                data = await self._test_ssh(current)
            else:
                data = await self._test_tunnel(current)
        except CannotConnect:
            return self.async_show_form(
                step_id="test_connection",
                data_schema=vol.Schema({}),
                errors={"base": "cannot_connect"},
            )
        except InvalidResponse:
            return self.async_show_form(
                step_id="test_connection",
                data_schema=vol.Schema({}),
                errors={"base": "invalid_response"},
            )

        server_ip = str(data.get("server", {}).get("ip", "")).strip()
        return self.async_show_form(
            step_id="test_connection",
            data_schema=vol.Schema({}),
            description_placeholders={
                "server_ip": server_ip or "unknown",
            },
        )

    async def _test_tunnel(self, user_input: dict) -> dict:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                str(user_input["status_url"]),
                timeout=int(user_input["http_timeout"]),
            ) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
        except Exception as err:
            raise CannotConnect from err

        if not isinstance(data, dict) or not isinstance(
            data.get("server"), dict
        ):
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
                str(user_input["username"]).strip(),
                str(key_path),
                int(user_input["port"]),
            )
        except SSHStatusResponseError as err:
            raise InvalidResponse from err
        except SSHStatusError as err:
            raise CannotConnect from err

    @staticmethod
    def _ssh_options_schema(current: dict) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(
                    "host",
                    default=str(current.get("host", DEFAULT_SSH_HOST)),
                ): str,
                vol.Required(
                    "port",
                    default=int(current.get("port", DEFAULT_SSH_PORT)),
                ): vol.Coerce(int),
                vol.Required(
                    "username",
                    default=str(
                        current.get("username", DEFAULT_SSH_USERNAME)
                    ),
                ): str,
                vol.Required(
                    "key_path",
                    default=str(
                        current.get("key_path", DEFAULT_SSH_KEY_PATH)
                    ),
                ): str,
                vol.Required(
                    "poll_interval",
                    default=int(
                        current.get("poll_interval", DEFAULT_POLL_INTERVAL)
                    ),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_POLL_INTERVAL,
                        max=MAX_POLL_INTERVAL,
                    ),
                ),
            }
        )
