"""Security infrastructure layer."""

from agent_os.infrastructure.security.cipher import (
    decrypt_payload,
    derive_master_key,
    encrypt_payload,
)
from agent_os.infrastructure.security.vault_db import get_vault_connection, init_vault_db
from agent_os.infrastructure.security.vault_repo import CredentialVaultRepository

__all__ = [
    "CredentialVaultRepository",
    "decrypt_payload",
    "derive_master_key",
    "encrypt_payload",
    "get_vault_connection",
    "init_vault_db",
]
