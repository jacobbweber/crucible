"""Unit tests for cipher key derivation and payload encryption."""

import pytest
from cryptography.fernet import InvalidToken

from agent_os.infrastructure.security.cipher import (
    decrypt_payload,
    derive_master_key,
    encrypt_payload,
)


def test_encrypt_decrypt_round_trip() -> None:
    """Encrypt payload dict; decrypt with identical key; assert dictionary matches."""
    salt = b"1234567812345678"
    key = derive_master_key(salt, "secure-passphrase")
    payload = {"api_key": "sk-1234567890abcdef", "client_id": "agent-user"}

    encrypted = encrypt_payload(payload, key)
    assert encrypted != b""
    assert b"sk-1234567890abcdef" not in encrypted

    decrypted = decrypt_payload(encrypted, key)
    assert decrypted == payload


def test_decrypt_with_wrong_key_fails() -> None:
    """Verify decrypting payload with a different key raises InvalidToken."""
    salt = b"1234567812345678"
    key1 = derive_master_key(salt, "passphrase-one")
    key2 = derive_master_key(salt, "passphrase-two")
    payload = {"secret": "confidential_data"}

    encrypted = encrypt_payload(payload, key1)

    with pytest.raises(InvalidToken):
        decrypt_payload(encrypted, key2)


def test_derive_master_key_empty_passphrase_raises() -> None:
    """Verify derive_master_key rejects empty or whitespace-only passphrases."""
    salt = b"1234567812345678"
    with pytest.raises(ValueError, match="Passphrase must be a non-empty string"):
        derive_master_key(salt, "")

    with pytest.raises(ValueError, match="Passphrase must be a non-empty string"):
        derive_master_key(salt, "   ")
