"""Unit tests for hot/cold session tiering and archival."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_os.infrastructure.storage.session_repo import SessionRepository


def test_archive_old_sessions_migrates_to_cold_db(tmp_path: Path) -> None:
    """Verify sessions older than retention_days are moved to sessions_archive.db."""
    db_path = tmp_path / "sessions.db"
    archive_path = tmp_path / "sessions_archive.db"
    repo = SessionRepository(db_path, archive_db_path=archive_path)

    # 1. Create a recent session
    recent = repo.create_session(title="Recent Active Session")
    repo.append_turn(recent.session_id, role="user", content="Recent hello")

    # 2. Create an old session (> 90 days old)
    old = repo.create_session(title="Old Archived Session")
    repo.append_turn(old.session_id, role="user", content="Old hello")

    # Backdate the old session in SQLite
    old_time = (datetime.now(UTC) - timedelta(days=100)).isoformat()
    with repo.db_path.open():
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?;",
            (old_time, old.session_id),
        )
        conn.commit()
        conn.close()

    # 3. Trigger archival
    archived_count = repo.archive_old_sessions(retention_days=90)
    assert archived_count == 1

    # 4. Verify old session is gone from hot storage
    assert repo.get_session(old.session_id) is None
    # Recent session is still in hot storage
    assert repo.get_session(recent.session_id) is not None

    # 5. Verify old session is present in cold archive
    archived_record = repo.get_archived_session(old.session_id)
    assert archived_record is not None
    assert archived_record.session_id == old.session_id
    assert archived_record.title == "Old Archived Session"
    assert archived_record.is_archived is True
