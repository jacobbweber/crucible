"""Cryptographic utilities: master key derivation and Fernet encryption wrapper."""

import base64
import json

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def derive_master_key(salt: bytes, passphrase: str) -> bytes:
    """Derive a URL-safe base64-encoded 32-byte Fernet key using PBKDF2HMAC.

    Raises:
        ValueError: If passphrase is empty or not provided.
    """
    if not passphrase or not passphrase.strip():
        raise ValueError("Passphrase must be a non-empty string for master key derivation")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
    )
    raw_key = kdf.derive(passphrase.encode("utf-8"))
    return base64.urlsafe_b64encode(raw_key)


def encrypt_payload(payload: dict[str, str], key: bytes) -> bytes:
    """Serialize payload dictionary to JSON bytes and encrypt with Fernet."""
    json_bytes = json.dumps(payload).encode("utf-8")
    fernet = Fernet(key)
    return fernet.encrypt(json_bytes)


def decrypt_payload(encrypted_blob: bytes, key: bytes) -> dict[str, str]:
    """Decrypt Fernet ciphertext and deserialize JSON back to dictionary."""
    fernet = Fernet(key)
    decrypted_bytes = fernet.decrypt(encrypted_blob)
    data = json.loads(decrypted_bytes.decode("utf-8"))
    return {str(k): str(v) for k, v in data.items()}
