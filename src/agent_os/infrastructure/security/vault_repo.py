"""Encrypted credential vault repository implementation."""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_os.domain.security import (
    CredentialType,
    PublicCredentialMetadata,
    StoredCredential,
)
from agent_os.infrastructure.security.cipher import decrypt_payload, encrypt_payload
from agent_os.infrastructure.security.vault_db import get_vault_connection, init_vault_db


class CredentialVaultRepository:
    """Manages encrypted credential storage, retrieval, and zero-context indexing."""

    def __init__(self, db_path: Path, master_key: bytes) -> None:
        self.db_path = db_path.resolve()
        self.master_key = master_key
        init_vault_db(self.db_path)

    def store_credential(
        self,
        alias: str,
        cred_type: CredentialType,
        secret_payload: dict[str, str],
        metadata: dict[str, Any] | None = None,
    ) -> PublicCredentialMetadata:
        """Validate alias, encrypt secret payload, and persist metadata in SQLite."""
        if (
            not alias.startswith("vault://")
            or len(alias) <= len("vault://")
            or not alias[len("vault://") :].strip()
        ):
            raise ValueError(f"Alias must follow 'vault://<name>' format: '{alias}'")

        encrypted_blob = encrypt_payload(secret_payload, self.master_key)
        credential_id = f"cred_{uuid.uuid4().hex}"
        now = datetime.now(UTC)
        now_str = now.isoformat()
        metadata_dict = metadata or {}
        metadata_json = json.dumps(metadata_dict)

        with get_vault_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO credentials (
                    credential_id, alias, cred_type, encrypted_payload,
                    metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    credential_id,
                    alias,
                    cred_type.value,
                    sqlite3.Binary(encrypted_blob),
                    metadata_json,
                    now_str,
                    now_str,
                ),
            )

        return PublicCredentialMetadata(
            credential_id=credential_id,
            alias=alias,
            cred_type=cred_type,
            metadata=metadata_dict,
            created_at=now,
            updated_at=now,
        )

    def get_secret(self, alias_or_id: str) -> StoredCredential:
        """Lookup credential by alias or ID and decrypt payload.

        Raises:
            KeyError: If credential is not found.
        """
        with get_vault_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT credential_id, alias, cred_type, encrypted_payload,
                       metadata_json, created_at, updated_at
                FROM credentials
                WHERE alias = ? OR credential_id = ?;
                """,
                (alias_or_id, alias_or_id),
            )
            row = cursor.fetchone()

        if row is None:
            raise KeyError(f"Credential not found: {alias_or_id}")

        encrypted_payload = bytes(row["encrypted_payload"])
        decrypted_payload = decrypt_payload(encrypted_payload, self.master_key)
        meta_dict = json.loads(row["metadata_json"]) if row["metadata_json"] else {}

        pub_meta = PublicCredentialMetadata(
            credential_id=row["credential_id"],
            alias=row["alias"],
            cred_type=CredentialType(row["cred_type"]),
            metadata=meta_dict,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
        return StoredCredential(metadata=pub_meta, payload=decrypted_payload)

    def list_metadata(self) -> list[PublicCredentialMetadata]:
        """Return all stored credential metadata records with secret payload omitted."""
        with get_vault_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT credential_id, alias, cred_type, metadata_json,
                       created_at, updated_at
                FROM credentials
                ORDER BY created_at ASC;
                """
            )
            rows = cursor.fetchall()

        results: list[PublicCredentialMetadata] = []
        for row in rows:
            meta_dict = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            results.append(
                PublicCredentialMetadata(
                    credential_id=row["credential_id"],
                    alias=row["alias"],
                    cred_type=CredentialType(row["cred_type"]),
                    metadata=meta_dict,
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
            )
        return results

    def delete_credential(self, alias_or_id: str) -> bool:
        """Delete credential by alias or ID from SQLite."""
        with get_vault_connection(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM credentials WHERE alias = ? OR credential_id = ?;",
                (alias_or_id, alias_or_id),
            )
            return cursor.rowcount > 0
