"""Unit tests for infrastructure config resolver."""

from pathlib import Path

import pytest

from agent_os.infrastructure.config import resolve_data_dir


def test_cli_argument_takes_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify CLI argument overrides environment variables and home default."""
    env_dir = tmp_path / "env_data"
    home_dir = tmp_path / "fake_home"
    cli_dir = tmp_path / "cli_data"

    monkeypatch.setenv("AGENT_OS_DATA_DIR", str(env_dir))
    monkeypatch.setattr(Path, "home", lambda: home_dir)

    resolved = resolve_data_dir(cli_dir=cli_dir)

    assert resolved == cli_dir.resolve()
    assert resolved.is_dir()
    assert not env_dir.exists()
    assert not (home_dir / ".local-agent-os").exists()


def test_env_var_takes_precedence_over_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify AGENT_OS_DATA_DIR overrides the home default."""
    env_dir = tmp_path / "env_data"
    home_dir = tmp_path / "fake_home"

    monkeypatch.setenv("AGENT_OS_DATA_DIR", str(env_dir))
    monkeypatch.setattr(Path, "home", lambda: home_dir)

    resolved = resolve_data_dir()

    assert resolved == env_dir.resolve()
    assert resolved.is_dir()
    assert not (home_dir / ".local-agent-os").exists()


def test_default_fallback_resolves_to_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify clean environment resolves to mocked HOME / .local-agent-os."""
    home_dir = tmp_path / "fake_home"

    monkeypatch.delenv("AGENT_OS_DATA_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: home_dir)

    resolved = resolve_data_dir()

    expected = (home_dir / ".local-agent-os").resolve()
    assert resolved == expected
    assert resolved.is_dir()


def test_directory_creation_idempotency(tmp_path: Path) -> None:
    """Verify repeated invocations do not fail if directory already exists."""
    target_dir = tmp_path / "idempotent_dir"

    first_call = resolve_data_dir(cli_dir=target_dir)
    assert first_call == target_dir.resolve()
    assert target_dir.is_dir()

    second_call = resolve_data_dir(cli_dir=target_dir)
    assert second_call == target_dir.resolve()
    assert target_dir.is_dir()
