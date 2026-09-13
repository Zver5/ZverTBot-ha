from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .const import (
    DEFAULT_SSH_PORT,
    DEFAULT_SSH_USERNAME,
)
from .normalize import normalize_status


_LOGGER = logging.getLogger(__name__)


class SSHStatusError(Exception):
    """Unable to connect to or execute a command on the VPS over SSH."""


class SSHStatusResponseError(Exception):
    """VPS returned an invalid status response."""


class SSHStatusClient:
    """System OpenSSH client for VPS status."""

    def __init__(
        self,
        host: str,
        username: str,
        key_path: str,
        port: int = DEFAULT_SSH_PORT,
    ) -> None:
        self.host = host
        self.username = username or DEFAULT_SSH_USERNAME
        self.key_path = str(Path(key_path).expanduser())
        self.port = port
        self._lock = threading.Lock()

    def _ssh_command(self) -> list[str]:
        return [
            "/usr/bin/ssh",
            "-i",
            self.key_path,
            "-p",
            str(self.port),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "StrictHostKeyChecking=accept-new",
            f"{self.username}@{self.host}",
            (
                "curl --fail --silent --show-error --max-time 15 "
                "http://127.0.0.1:8080/vps-status.json"
            ),
        ]

    def close(self) -> None:
        """No persistent SSH process to close."""

    def read(self) -> dict[str, Any]:
        with self._lock:
            key = Path(self.key_path)
            if not key.is_file():
                raise SSHStatusError(f"SSH key not found: {key}")

            command = self._ssh_command()
            started = time.monotonic()
            _LOGGER.debug(
                "Starting VPS SSH status request to %s@%s:%s",
                self.username,
                self.host,
                self.port,
            )
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
            except subprocess.TimeoutExpired as err:
                elapsed = time.monotonic() - started
                _LOGGER.warning(
                    "VPS SSH status request timed out after %.2fs "
                    "(subprocess timeout=%ss)",
                    elapsed,
                    err.timeout,
                )
                raise SSHStatusError(
                    f"TimeoutExpired: {err!r}"
                ) from err
            except Exception as err:
                elapsed = time.monotonic() - started
                _LOGGER.warning(
                    "VPS SSH status request failed after %.2fs: %s",
                    elapsed,
                    err,
                )
                raise SSHStatusError(
                    f"{type(err).__name__}: {err!r}"
                ) from err

            elapsed = time.monotonic() - started
            _LOGGER.debug(
                "VPS SSH status request finished in %.2fs with exit code %s",
                elapsed,
                result.returncode,
            )

        if result.returncode != 0:
            error = (result.stderr or result.stdout).strip()
            raise SSHStatusError(
                error or f"ssh exited with code {result.returncode}"
            )

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as err:
            raise SSHStatusResponseError(
                f"VPS returned invalid JSON: {err}"
            ) from err

        if not isinstance(data, dict) or not isinstance(data.get("server"), dict):
            raise SSHStatusResponseError("VPS returned an invalid status response")

        return normalize_status(data)


def read_vps_status(
    host: str,
    username: str,
    key_path: str,
    port: int = DEFAULT_SSH_PORT,
) -> dict[str, Any]:
    client = SSHStatusClient(
        host,
        username,
        key_path,
        port,
    )
    try:
        return client.read()
    finally:
        client.close()
