"""Unit tests for SessionRepository persistence, turns, and journey scratchpad."""

from pathlib import Path

from agent_os.infrastructure.storage.session_repo import SessionRepository


def test_session_creation_and_retrieval(tmp_path: Path) -> None:
    """Verify creating a session persists and retrieves identical title and timestamps."""
    db_file = tmp_path / "sessions.db"
    repo = SessionRepository(db_file)

    created = repo.create_session("Architecture Planning")
    assert created.title == "Architecture Planning"
    assert not created.is_archived

    retrieved = repo.get_session(created.session_id)
    assert retrieved is not None
    assert retrieved.session_id == created.session_id
    assert retrieved.title == created.title
    assert retrieved.created_at == created.created_at
    assert retrieved.updated_at == created.updated_at
    assert not retrieved.is_archived

    # Non-existent session
    assert repo.get_session("non_existent_id") is None


def test_ensure_session_idempotent(tmp_path: Path) -> None:
    """Verify ensure_session creates missing session and returns existing session (M2)."""
    db_file = tmp_path / "sessions.db"
    repo = SessionRepository(db_file)

    # First call provisions new session
    session1 = repo.ensure_session("sess_auto_1", title="Auto Title")
    assert session1.session_id == "sess_auto_1"
    assert session1.title == "Auto Title"
    assert not session1.is_archived

    # Second call returns existing session without error
    session2 = repo.ensure_session("sess_auto_1", title="Different Title")
    assert session2.session_id == session1.session_id
    assert session2.title == "Auto Title"


def test_append_turn_sequence_order(tmp_path: Path) -> None:
    """Verify multiple turns increment turn_index monotonically and retrieve chronologically."""
    db_file = tmp_path / "sessions.db"
    repo = SessionRepository(db_file)
    session = repo.create_session("Turn Ordering")

    turn0 = repo.append_turn(session.session_id, role="user", content="Turn 0")
    turn1 = repo.append_turn(session.session_id, role="assistant", content="Turn 1")
    turn2 = repo.append_turn(session.session_id, role="user", content="Turn 2")

    assert turn0.turn_index == 0
    assert turn1.turn_index == 1
    assert turn2.turn_index == 2

    turns = repo.get_recent_turns(session.session_id, limit=10)
    assert len(turns) == 3
    assert [t.turn_index for t in turns] == [0, 1, 2]
    assert [t.content for t in turns] == ["Turn 0", "Turn 1", "Turn 2"]


def test_get_recent_turns_limit(tmp_path: Path) -> None:
    """Append 20 turns, request limit 10; verify only the most recent 10 turns are returned."""
    db_file = tmp_path / "sessions.db"
    repo = SessionRepository(db_file)
    session = repo.create_session("Limit Test")

    for i in range(20):
        repo.append_turn(
            session.session_id,
            role="user" if i % 2 == 0 else "assistant",
            content=f"Message {i}",
            token_count=10,
        )

    recent = repo.get_recent_turns(session.session_id, limit=10)
    assert len(recent) == 10
    # Must be turns 10 to 19 in chronological order
    assert [t.turn_index for t in recent] == list(range(10, 20))
    assert recent[0].content == "Message 10"
    assert recent[-1].content == "Message 19"


def test_journey_lifecycle_persistence(tmp_path: Path) -> None:
    """Verify journey creation in running status, step appending, and transition to completed."""
    db_file = tmp_path / "sessions.db"
    repo = SessionRepository(db_file)
    session = repo.create_session("Journey Test")

    journey = repo.record_journey_start(session.session_id, "Code refactor task")
    assert journey.status == "running"
    assert journey.summary is None
    assert journey.completed_at is None

    repo.record_journey_step(
        journey.journey_id,
        node_name="analyzer",
        input_payload={"files": ["main.py"]},
        output_payload={"issues": 2},
        duration_ms=120,
    )

    repo.record_journey_step(
        journey.journey_id,
        node_name="patcher",
        input_payload={"action": "fix_lints"},
        output_payload={"fixed": True},
        duration_ms=250,
    )

    completed = repo.complete_journey(
        journey_id=journey.journey_id,
        status="completed",
        summary="Refactored 1 file successfully",
        artifacts=["diff.patch"],
        state_mutations=["modified main.py"],
        metrics={"duration_ms": 370, "token_usage": 450},
    )

    assert completed.status == "completed"
    assert completed.summary == "Refactored 1 file successfully"
    assert completed.artifacts == ["diff.patch"]
    assert completed.state_mutations == ["modified main.py"]
    assert completed.metrics == {"duration_ms": 370, "token_usage": 450}
    assert completed.completed_at is not None

    # Retrieve from fresh query
    fetched = repo.get_journey(journey.journey_id)
    assert fetched is not None
    assert fetched.status == "completed"
    assert fetched.artifacts == ["diff.patch"]
    assert fetched.metrics["token_usage"] == 450


def test_scratchpad_retrieval_isolation(tmp_path: Path) -> None:
    """Verify get_journey_scratchpad yields complete step telemetry in isolation."""
    db_file = tmp_path / "sessions.db"
    repo = SessionRepository(db_file)
    session = repo.create_session("Isolation Test")

    repo.append_turn(session.session_id, role="user", content="Perform task")

    journey = repo.record_journey_start(session.session_id, "Background task")
    repo.record_journey_step(
        journey.journey_id,
        node_name="tool_1",
        input_payload={"param": 1},
        output_payload={"result": "ok"},
        duration_ms=45,
    )
    repo.record_journey_step(
        journey.journey_id,
        node_name="tool_2",
        input_payload={"param": 2},
        output_payload={"result": "done"},
        duration_ms=80,
    )

    repo.complete_journey(
        journey_id=journey.journey_id,
        status="completed",
        summary="Done",
        artifacts=[],
        state_mutations=[],
        metrics={},
    )

    scratchpad = repo.get_journey_scratchpad(journey.journey_id)
    assert len(scratchpad) == 2
    assert scratchpad[0]["node_name"] == "tool_1"
    assert scratchpad[0]["input_payload"] == {"param": 1}
    assert scratchpad[1]["node_name"] == "tool_2"
    assert scratchpad[1]["duration_ms"] == 80

    # Ensure parent session turns are NOT polluted by background worker steps
    turns = repo.get_recent_turns(session.session_id)
    assert len(turns) == 1
    assert turns[0].content == "Perform task"
