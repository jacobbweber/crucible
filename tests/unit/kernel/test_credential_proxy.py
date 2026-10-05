"""Unit tests for CredentialProxyGate JIT parameter resolution and log scrubbing."""

from pathlib import Path

import pytest

from agent_os.domain.security import CredentialType
from agent_os.infrastructure.security.cipher import derive_master_key
from agent_os.infrastructure.security.vault_repo import CredentialVaultRepository
from agent_os.kernel.credential_proxy import CredentialProxyGate


def _create_proxy(tmp_path: Path) -> tuple[CredentialProxyGate, CredentialVaultRepository]:
    """Helper to initialize a hermetic vault repository and credential proxy gate."""
    key = derive_master_key(salt=b"test_salt_123456", passphrase="test_passphrase")
    vault = CredentialVaultRepository(db_path=tmp_path / "vault.db", master_key=key)
    return CredentialProxyGate(vault), vault


def test_resolve_parameters_replaces_vault_alias(tmp_path: Path) -> None:
    """Verify vault:// alias is resolved to unmasked secret string in parameters."""
    proxy, vault = _create_proxy(tmp_path)
    vault.store_credential(
        alias="vault://github-token",
        cred_type=CredentialType.API_KEY,
        secret_payload={"token": "ghp_secret123"},
    )

    result = proxy.resolve_parameters({"token": "vault://github-token"})
    assert result.resolved_params["token"] == "ghp_secret123"


def test_resolve_parameters_tracks_secrets_for_scrubbing(tmp_path: Path) -> None:
    """Verify secrets_to_scrub and resolved_aliases correctly record resolved secrets."""
    proxy, vault = _create_proxy(tmp_path)
    vault.store_credential(
        alias="vault://github-token",
        cred_type=CredentialType.API_KEY,
        secret_payload={"token": "ghp_secret123"},
    )

    result = proxy.resolve_parameters({"auth": "vault://github-token"})
    assert result.secrets_to_scrub == ["ghp_secret123"]
    assert result.resolved_aliases == ["vault://github-token"]


def test_scrub_text_redacts_sensitive_substrings(tmp_path: Path) -> None:
    """Verify scrub_text replaces raw secret substrings with [REDACTED_SECRET]."""
    proxy, _ = _create_proxy(tmp_path)
    log_text = "Error 401 using ghp_secret123"
    scrubbed = proxy.scrub_text(log_text, secrets_to_scrub=["ghp_secret123"])

    assert scrubbed.sanitized_text == "Error 401 using [REDACTED_SECRET]"
    assert scrubbed.redaction_count == 1


def test_resolve_unknown_alias_raises(tmp_path: Path) -> None:
    """Verify querying an unconfigured vault:// alias raises KeyError cleanly."""
    proxy, _ = _create_proxy(tmp_path)
    with pytest.raises(KeyError):
        proxy.resolve_parameters({"token": "vault://unknown"})


def test_pass_through_non_vault_parameters(tmp_path: Path) -> None:
    """Verify primitives and standard strings pass through unmodified without tracking."""
    proxy, _ = _create_proxy(tmp_path)
    raw_params: dict[str, str | int | float | bool | None] = {
        "count": 42,
        "enabled": True,
        "path": "/tmp/test.txt",
        "ratio": 3.14,
        "missing": None,
    }

    result = proxy.resolve_parameters(raw_params)
    assert result.resolved_params == raw_params
    assert result.resolved_aliases == []
    assert result.secrets_to_scrub == []
