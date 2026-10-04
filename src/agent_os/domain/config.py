"""Domain configuration models."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Application configuration schema."""

    data_dir: Path | None = None
    vllm_base_url: str = "http://127.0.0.1:8000/v1"
    vllm_model_name: str = "Qwen/Qwen2.5-32B-Instruct"
    vllm_api_key: str = "EMPTY"
    vllm_context_window: int = 65536
    vllm_request_timeout: float = 120.0

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
