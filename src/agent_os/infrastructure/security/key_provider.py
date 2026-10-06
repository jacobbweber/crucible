"""Vault master key provisioning: passphrase-derived (with persisted salt) or random keyfile."""

import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

from agent_os.infrastructure.security.cipher import derive_master_key

KEYFILE_NAME = "vault.key"
SALTFILE_NAME = "vault.salt"


def _write_private(path: Path, data: bytes) -> None:
    """Write bytes to a new file with owner-only permissions where supported."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def load_or_create_master_key(data_dir: Path, passphrase: str | None = None) -> bytes:
    """Return a Fernet key for the vault, creating key material on first use.

    With a passphrase, a random salt is persisted and PBKDF2 derives the key.
    Without one, a random Fernet key is generated once and stored in a keyfile.
    """
    if passphrase:
        salt_path = data_dir / SALTFILE_NAME
        if not salt_path.exists():
            _write_private(salt_path, secrets.token_bytes(16))
        return derive_master_key(salt=salt_path.read_bytes(), passphrase=passphrase)

    key_path = data_dir / KEYFILE_NAME
    if not key_path.exists():
        _write_private(key_path, Fernet.generate_key())
    return key_path.read_bytes().strip()
