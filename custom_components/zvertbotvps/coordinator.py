from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_HTTP_TIMEOUT,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SSH_BACKOFF,
    DEFAULT_SSH_KEY_PATH,
    DEFAULT_SSH_PORT,
    DEFAULT_SSH_USERNAME,
    DEFAULT_STATUS_URL,
    DOMAIN,
    MODE_SSH,
)
from .normalize import normalize_status
from .ssh import SSHStatusClient, SSHStatusError, SSHStatusResponseError

_LOGGER = logging.getLogger(__name__)


class ZverTBotCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.settings = {**entry.data, **entry.options}
        self.mode = self.settings.get("mode", "tunnel")
        self.status_url = self.settings.get("status_url", DEFAULT_STATUS_URL)
        self.poll_interval = max(
            30,
            int(self.settings.get("poll_interval", DEFAULT_POLL_INTERVAL)),
        )
        self.http_timeout = max(
            3,
            int(self.settings.get("http_timeout", DEFAULT_HTTP_TIMEOUT)),
        )
        self.session = async_get_clientsession(hass)
        self._ssh_blocked_until = 0.0
        self._ssh_client: SSHStatusClient | None = None
        if self.mode == MODE_SSH:
            self._ssh_client = SSHStatusClient(
                str(self.settings["host"]),
                str(self.settings.get("username", DEFAULT_SSH_USERNAME)),
                str(self.settings.get("key_path", DEFAULT_SSH_KEY_PATH)),
                int(self.settings.get("port", DEFAULT_SSH_PORT)),
            )
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=self.poll_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        if self.mode == MODE_SSH:
            return await self._async_update_ssh()
        return await self._async_update_tunnel()

    async def _async_update_tunnel(self) -> dict[str, Any]:
        try:
            async with self.session.get(
                self.status_url, timeout=self.http_timeout
            ) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
        except (ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed(f"Unable to read VPS status: {err}") from err
        return self._validate(data)

    async def _async_update_ssh(self) -> dict[str, Any]:
        now = asyncio.get_running_loop().time()
        if now < self._ssh_blocked_until:
            remaining = int(self._ssh_blocked_until - now)
            raise UpdateFailed(f"SSH reconnect paused for {remaining}s after failure")
        if self._ssh_client is None:
            raise UpdateFailed("SSH client is not configured")
        try:
            data = await asyncio.to_thread(self._ssh_client.read)
        except SSHStatusResponseError as err:
            self._ssh_blocked_until = now + DEFAULT_SSH_BACKOFF
            _LOGGER.warning(
                "VPS SSH returned an invalid status response: %s", err
            )
            raise UpdateFailed(
                f"VPS returned an invalid status response over SSH: {err}"
            ) from err
        except SSHStatusError as err:
            self._ssh_client.close()
            self._ssh_blocked_until = now + DEFAULT_SSH_BACKOFF
            _LOGGER.warning(
                "VPS SSH connection failed; backoff enabled: %s", err
            )
            raise UpdateFailed(
                f"Unable to read VPS status over SSH: {err}"
            ) from err
        self._ssh_blocked_until = 0.0
        return self._validate(data)

    @staticmethod
    def _validate(data: Any) -> dict[str, Any]:
        if not isinstance(data, dict) or not isinstance(data.get("server"), dict):
            raise UpdateFailed("VPS status response is invalid")
        return normalize_status(data)

    async def async_shutdown(self) -> None:
        if self._ssh_client is not None:
            await asyncio.to_thread(self._ssh_client.close)
        await super().async_shutdown()

    @property
    def server_ip(self) -> str:
        return str(self.data.get("server", {}).get("ip", ""))

    def service(self, name: str) -> dict[str, Any]:
        value = self.data.get("services", {}).get(name, {})
        return value if isinstance(value, dict) else {}

    def clients(self, kind: str) -> list[dict[str, Any]]:
        value = self.data.get(kind, {}).get("clients", [])
        return value if isinstance(value, list) else []
