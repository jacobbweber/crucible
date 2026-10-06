"""Zero-context credential proxy gate for JIT parameter resolution and log scrubbing."""

from typing import Any

from agent_os.domain.security import ResolvedParameters, ScrubbedOutput
from agent_os.infrastructure.security.vault_repo import CredentialVaultRepository


class CredentialProxyGate:
    """Manages JIT credential secret injection and output redaction for tools."""

    def __init__(self, vault_repo: CredentialVaultRepository) -> None:
        self.vault = vault_repo
        self.vault_repo = vault_repo

    def resolve_parameters(
        self,
        parameters: dict[str, Any],
    ) -> ResolvedParameters:
        """Resolve vault:// aliases to raw credentials and track secret strings for scrubbing."""
        resolved_params: dict[str, Any] = {}
        resolved_aliases: list[str] = []
        secrets_to_scrub: list[str] = []

        for key, val in parameters.items():
            if isinstance(val, str) and val.startswith("vault://"):
                stored_cred = self.vault.get_secret(val)
                secret_str = stored_cred.payload.get("token")
                if secret_str is None:
                    secret_str = (
                        next(iter(stored_cred.payload.values())) if stored_cred.payload else ""
                    )
                resolved_params[key] = secret_str
                resolved_aliases.append(val)
                if secret_str:
                    secrets_to_scrub.append(secret_str)
            else:
                resolved_params[key] = val

        return ResolvedParameters(
            resolved_params=resolved_params,
            resolved_aliases=resolved_aliases,
            secrets_to_scrub=secrets_to_scrub,
        )

    def scrub_text(
        self,
        text: str,
        secrets_to_scrub: list[str],
        replacement: str = "[REDACTED_SECRET]",
    ) -> ScrubbedOutput:
        """Scrub sensitive secret substrings from text and calculate total redactions."""
        if not text or not secrets_to_scrub:
            return ScrubbedOutput(sanitized_text=text, redaction_count=0)

        valid_secrets = [s for s in dict.fromkeys(secrets_to_scrub) if s]
        if not valid_secrets:
            return ScrubbedOutput(sanitized_text=text, redaction_count=0)

        sanitized = text
        total_redactions = 0
        for secret in valid_secrets:
            count = sanitized.count(secret)
            if count > 0:
                total_redactions += count
                sanitized = sanitized.replace(secret, replacement)

        return ScrubbedOutput(
            sanitized_text=sanitized,
            redaction_count=total_redactions,
        )
