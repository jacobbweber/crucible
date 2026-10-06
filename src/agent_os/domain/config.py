"""Domain configuration models."""

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Application configuration schema."""

    data_dir: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("AGENT_OS_DATA_DIR", "DATA_DIR", "data_dir"),
    )
    vllm_base_url: str = "http://127.0.0.1:8000/v1"
    vllm_model_name: str = "Qwen/Qwen2.5-32B-Instruct"
    vllm_api_key: str = "EMPTY"
    vllm_context_window: int = 65536
    vllm_request_timeout: float = 120.0
    # None = server default; False/True sends chat_template_kwargs.enable_thinking.
    vllm_enable_thinking: bool | None = None
    # Optional passphrase for vault key derivation; a random keyfile is used when unset.
    vault_passphrase: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    @classmethod
    def from_env_file(cls, env_file: str | Path) -> "AppConfig":
        """Load configuration from a specific profile file instead of the default `.env`."""
        return cls(_env_file=env_file)  # pyright: ignore[reportCallIssue]
