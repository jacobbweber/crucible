"""Pytest configuration and root fixtures."""

from collections.abc import Iterator

import pytest

from agent_os.domain.config import AppConfig


@pytest.fixture(autouse=True)
def _hermetic_app_config(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Prevent tests from reading a developer's local .env file."""
    monkeypatch.setitem(AppConfig.model_config, "env_file", None)
    yield
