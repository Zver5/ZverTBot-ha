from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess


class SSHKeyGenerationError(Exception):
    """SSH key generation failed."""


def generate_ssh_key_pair(private_key_path: str | Path) -> str:
    """Generate an Ed25519 key pair and return the public key."""
    private_path = Path(private_key_path).expanduser()
    public_path = Path(f"{private_path}.pub")

    if private_path.exists() or public_path.exists():
        raise SSHKeyGenerationError(
            f"SSH key already exists: {private_path}"
        )

    ssh_keygen = shutil.which("ssh-keygen")
    if not ssh_keygen:
        raise SSHKeyGenerationError("ssh-keygen is not available")

    try:
        private_path.parent.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            [
                ssh_keygen,
                "-q",
                "-t",
                "ed25519",
                "-f",
                str(private_path),
                "-N",
                "",
                "-C",
                "ZverTBot",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as err:
        raise SSHKeyGenerationError(
            f"Unable to start ssh-keygen: {err}"
        ) from err

    if result.returncode != 0:
        private_path.unlink(missing_ok=True)
        public_path.unlink(missing_ok=True)
        raise SSHKeyGenerationError(
            result.stderr.strip() or "ssh-keygen failed"
        )

    try:
        os.chmod(private_path, 0o600)
        os.chmod(public_path, 0o644)
        public_key = public_path.read_text(encoding="utf-8").strip()
    except OSError as err:
        private_path.unlink(missing_ok=True)
        public_path.unlink(missing_ok=True)
        raise SSHKeyGenerationError(
            f"Unable to read generated SSH key: {err}"
        ) from err

    if not public_key.startswith("ssh-ed25519 "):
        private_path.unlink(missing_ok=True)
        public_path.unlink(missing_ok=True)
        raise SSHKeyGenerationError("Generated public key has an invalid format")

    return public_key
