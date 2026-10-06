"""Domain models for security, credential types, and encrypted vault storage."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

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


class ResolvedParameters(BaseModel):
    """Parameters with vault aliases resolved to raw secrets, tracking aliases and secrets."""

    resolved_params: dict[str, Any]
    resolved_aliases: list[str] = Field(default_factory=list)
    secrets_to_scrub: list[str] = Field(default_factory=list)


class ScrubbedOutput(BaseModel):
    """Sanitized text output with redaction statistics."""

    sanitized_text: str
    redaction_count: int = 0
