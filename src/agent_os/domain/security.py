"""Domain models for security, credential types, and encrypted vault storage."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class CredentialType(StrEnum):
    """Supported credential categories."""

    API_KEY = "api_key"
    BASIC_AUTH = "basic_auth"
    OAUTH2 = "oauth2"
    SSH_KEY = "ssh_key"
    TLS_CERT = "tls_cert"


class PublicCredentialMetadata(BaseModel):
    """Public credential metadata without secret payload."""

    credential_id: str
    alias: str
    cred_type: CredentialType
    metadata: dict[str, str | int | float | None] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StoredCredential(BaseModel):
    """Complete credential with decrypted secret payload."""

    metadata: PublicCredentialMetadata
    payload: dict[str, str]
