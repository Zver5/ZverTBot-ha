from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
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
        self._ssh_retry_at: datetime | None = None
        self._ssh_client: SSHStatusClient | None = None
        self._connection_state = "unknown"
        self._last_success: str | None = None
        self._last_error: str | None = None
        self._consecutive_failures = 0
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
            self._mark_connection_failure(str(err))
            raise UpdateFailed(f"Unable to read VPS status: {err}") from err
        try:
            result = self._validate(data)
        except UpdateFailed as err:
            self._mark_connection_failure(str(err))
            raise
        self._mark_connection_success()
        return result

    async def _async_update_ssh(self) -> dict[str, Any]:
        now = asyncio.get_running_loop().time()
        if now < self._ssh_blocked_until:
            remaining = int(self._ssh_blocked_until - now)
            self._connection_state = "paused"
            raise UpdateFailed(f"SSH reconnect paused for {remaining}s after failure")
        if self._ssh_client is None:
            self._mark_connection_failure("SSH client is not configured")
            raise UpdateFailed("SSH client is not configured")
        try:
            data = await asyncio.to_thread(self._ssh_client.read)
        except SSHStatusResponseError as err:
            self._ssh_blocked_until = now + DEFAULT_SSH_BACKOFF
            self._ssh_retry_at = datetime.now(timezone.utc) + timedelta(
                seconds=DEFAULT_SSH_BACKOFF
            )
            self._mark_connection_failure(str(err))
            _LOGGER.warning(
                "VPS SSH returned an invalid status response: %s", err
            )
            raise UpdateFailed(
                f"VPS returned an invalid status response over SSH: {err}"
            ) from err
        except SSHStatusError as err:
            self._ssh_client.close()
            self._ssh_blocked_until = now + DEFAULT_SSH_BACKOFF
            self._ssh_retry_at = datetime.now(timezone.utc) + timedelta(
                seconds=DEFAULT_SSH_BACKOFF
            )
            self._mark_connection_failure(str(err))
            _LOGGER.warning(
                "VPS SSH connection failed; backoff enabled: %s", err
            )
            raise UpdateFailed(
                f"Unable to read VPS status over SSH: {err}"
            ) from err
        self._ssh_blocked_until = 0.0
        self._ssh_retry_at = None
        try:
            result = self._validate(data)
        except UpdateFailed as err:
            self._mark_connection_failure(str(err))
            raise
        self._mark_connection_success()
        return result

    def _mark_connection_success(self) -> None:
        self._connection_state = "connected"
        self._last_success = datetime.now(timezone.utc).isoformat()
        self._last_error = None
        self._consecutive_failures = 0

    def _mark_connection_failure(self, error: str) -> None:
        self._connection_state = "failed"
        self._last_error = error
        self._consecutive_failures += 1

    @property
    def connection_state(self) -> str:
        if self.mode == MODE_SSH and self._ssh_retry_at is not None:
            if self._ssh_retry_at > datetime.now(timezone.utc):
                return "paused"
        return self._connection_state

    @property
    def last_success(self) -> str | None:
        return self._last_success

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def next_retry(self) -> str | None:
        if self.mode != MODE_SSH or self._ssh_retry_at is None:
            return None
        if self._ssh_retry_at <= datetime.now(timezone.utc):
            return None
        return self._ssh_retry_at.replace(microsecond=0).isoformat()

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
