"""Unit tests for CredentialVaultRepository persistence, encryption, and uniqueness."""

import sqlite3
from pathlib import Path

import pytest

from agent_os.domain.security import CredentialType
from agent_os.infrastructure.security.cipher import derive_master_key
from agent_os.infrastructure.security.vault_repo import CredentialVaultRepository


def test_store_and_retrieve_api_key(tmp_path: Path) -> None:
    """Store API key payload under vault://test-token; verify retrieval returns unmasked secret."""
    db_file = tmp_path / "credentials.db"
    key = derive_master_key(salt=b"test-salt-123456", passphrase="test-password")
    repo = CredentialVaultRepository(db_file, master_key=key)

    payload = {"api_key": "sk-live-secret-token-value"}
    meta = repo.store_credential(
        alias="vault://test-token",
        cred_type=CredentialType.API_KEY,
        secret_payload=payload,
        metadata={"provider": "openai", "env": "prod"},
    )

    assert meta.alias == "vault://test-token"
    assert meta.cred_type == CredentialType.API_KEY
    assert meta.metadata == {"provider": "openai", "env": "prod"}

    # Retrieve by alias
    stored_by_alias = repo.get_secret("vault://test-token")
    assert stored_by_alias.metadata.credential_id == meta.credential_id
    assert stored_by_alias.payload == payload

    # Retrieve by ID
    stored_by_id = repo.get_secret(meta.credential_id)
    assert stored_by_id.metadata.alias == "vault://test-token"
    assert stored_by_id.payload == payload

    # Nonexistent credential raises KeyError
    with pytest.raises(KeyError):
        repo.get_secret("vault://nonexistent")


def test_raw_payload_not_stored_as_plaintext(tmp_path: Path) -> None:
    """Inspect raw SQLite file bytes; assert plaintext secret string does not appear."""
    db_file = tmp_path / "credentials.db"
    key = derive_master_key(salt=b"test-salt-123456", passphrase="test-password")
    repo = CredentialVaultRepository(db_file, master_key=key)

    secret_value = "super-confidential-secret-key-999"
    repo.store_credential(
        alias="vault://unexposed-token",
        cred_type=CredentialType.API_KEY,
        secret_payload={"token": secret_value},
    )

    raw_bytes = db_file.read_bytes()
    assert secret_value.encode("utf-8") not in raw_bytes


def test_list_metadata_omits_secrets(tmp_path: Path) -> None:
    """Verify list_metadata returns objects containing alias and type without secret payload."""
    db_file = tmp_path / "credentials.db"
    key = derive_master_key(salt=b"test-salt-123456", passphrase="test-password")
    repo = CredentialVaultRepository(db_file, master_key=key)

    repo.store_credential(
        alias="vault://github-pat",
        cred_type=CredentialType.API_KEY,
        secret_payload={"pat": "ghp_123456789"},
    )
    repo.store_credential(
        alias="vault://prod-ssh",
        cred_type=CredentialType.SSH_KEY,
        secret_payload={"private_key": "-----BEGIN RSA PRIVATE KEY-----..."},
    )

    metadata_list = repo.list_metadata()
    assert len(metadata_list) == 2

    aliases = {m.alias for m in metadata_list}
    assert aliases == {"vault://github-pat", "vault://prod-ssh"}

    for item in metadata_list:
        assert hasattr(item, "alias")
        assert hasattr(item, "cred_type")
        assert not hasattr(item, "payload")
        assert not hasattr(item, "secret_payload")


def test_alias_uniqueness_enforced(tmp_path: Path) -> None:
    """Attempting to insert duplicate alias raises exception."""
    db_file = tmp_path / "credentials.db"
    key = derive_master_key(salt=b"test-salt-123456", passphrase="test-password")
    repo = CredentialVaultRepository(db_file, master_key=key)

    repo.store_credential(
        alias="vault://unique-alias",
        cred_type=CredentialType.API_KEY,
        secret_payload={"token": "first"},
    )

    with pytest.raises(sqlite3.IntegrityError):
        repo.store_credential(
            alias="vault://unique-alias",
            cred_type=CredentialType.API_KEY,
            secret_payload={"token": "second"},
        )
