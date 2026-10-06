"""Unit tests for dual-channel background completion signaling and prompt injection."""

from agent_os.domain.ipc import SubJobReturnEnvelope
from agent_os.domain.signaling import AmbientNudge
from agent_os.kernel.signaling import CompletionSignaler


def test_signal_completion_populates_both_channels() -> None:
    """Signal completion of a sub-job; verify AmbientNudge in queue and deferred buffer."""
    signaler = CompletionSignaler()
    envelope = SubJobReturnEnvelope(
        journey_id="j_abc12345678",
        status="completed",
        summary="Analysis completed successfully.",
        token_estimate=150,
    )

    nudge = signaler.signal_completion(session_id="session_42", envelope=envelope)

    assert isinstance(nudge, AmbientNudge)
    assert nudge.journey_id == "j_abc12345678"
    assert nudge.status == "completed"
    assert nudge.short_notice == "Sub-job j_abc123 finished: COMPLETED"
    assert len(signaler._nudge_queue) == 1
    assert signaler._nudge_queue[0] == nudge
    assert signaler._deferred_buffers["session_42"] == [envelope]


def test_poll_ambient_nudges_drains_queue() -> None:
    """Call poll_ambient_nudges(); verify drained nudges returned and queue is empty."""
    signaler = CompletionSignaler()
    env1 = SubJobReturnEnvelope(
        journey_id="j_task1_1234",
        status="completed",
        summary="Task 1 finished.",
        token_estimate=100,
    )
    env2 = SubJobReturnEnvelope(
        journey_id="j_task2_5678",
        status="failed",
        summary="Task 2 failed.",
        token_estimate=80,
    )

    nudge1 = signaler.signal_completion("sess_1", env1)
    nudge2 = signaler.signal_completion("sess_1", env2)

    polled = signaler.poll_ambient_nudges(limit=10)
    assert polled == [nudge1, nudge2]
    assert len(signaler._nudge_queue) == 0

    subsequent = signaler.poll_ambient_nudges()
    assert subsequent == []


def test_format_deferred_prompt_block_renders_and_drains() -> None:
    """Signal 2 completions; format prompt block; verify XML tag wraps summaries; verify drains."""
    signaler = CompletionSignaler()
    env1 = SubJobReturnEnvelope(
        journey_id="j_alpha_123456",
        status="completed",
        summary="Refactored database queries.",
        token_estimate=120,
    )
    env2 = SubJobReturnEnvelope(
        journey_id="j_beta_6543210",
        status="failed",
        summary="Connection timed out while querying cache.",
        token_estimate=95,
    )

    signaler.signal_completion("sess_main", env1)
    signaler.signal_completion("sess_main", env2)

    prompt_block = signaler.format_deferred_prompt_block("sess_main")

    assert prompt_block.startswith("<background_completions>")
    assert prompt_block.endswith("</background_completions>")
    expected_line1 = "- [Status: COMPLETED] Journey j_alpha_123456: Refactored database queries."
    expected_line2 = (
        "- [Status: FAILED] Journey j_beta_6543210: Connection timed out while querying cache."
    )
    assert expected_line1 in prompt_block
    assert expected_line2 in prompt_block

    subsequent_block = signaler.format_deferred_prompt_block("sess_main")
    assert subsequent_block == ""


def test_format_deferred_prompt_block_empty_when_no_signals() -> None:
    """Verify empty string returned when no completions are pending."""
    signaler = CompletionSignaler()
    assert signaler.format_deferred_prompt_block("non_existent_session") == ""


def test_poll_ambient_nudges_limit_and_edge_cases() -> None:
    """Verify limit pagination and non-positive limit handling for poll_ambient_nudges."""
    signaler = CompletionSignaler()
    for i in range(3):
        env = SubJobReturnEnvelope(
            journey_id=f"j_worker_{i:04d}",
            status="completed",
            summary=f"Worker {i} finished",
            token_estimate=50,
        )
        signaler.signal_completion("sess_x", env)

    assert signaler.poll_ambient_nudges(limit=0) == []
    assert len(signaler._nudge_queue) == 3

    page1 = signaler.poll_ambient_nudges(limit=2)
    assert len(page1) == 2
    assert len(signaler._nudge_queue) == 1

    page2 = signaler.poll_ambient_nudges(limit=2)
    assert len(page2) == 1
    assert len(signaler._nudge_queue) == 0


def test_drain_deferred_completions_direct() -> None:
    """Verify direct draining of deferred completions buffer."""
    signaler = CompletionSignaler()
    env = SubJobReturnEnvelope(
        journey_id="j_drain_test",
        status="aborted",
        summary="Job aborted by user.",
        token_estimate=30,
    )
    signaler.signal_completion("sess_drain", env)

    buf = signaler.get_deferred_buffer("sess_drain")
    assert len(buf.pending_envelopes) == 1

    drained = signaler.drain_deferred_completions("sess_drain")
    assert drained == [env]
    assert signaler.drain_deferred_completions("sess_drain") == []


def test_poll_ambient_nudges_session_isolation() -> None:
    """Signal completions across distinct sessions; verify polling is isolated per session (H5)."""
    signaler = CompletionSignaler()

    env_a = SubJobReturnEnvelope(
        journey_id="j_sess_a",
        status="completed",
        summary="Session A job finished.",
        token_estimate=50,
    )
    env_b = SubJobReturnEnvelope(
        journey_id="j_sess_b",
        status="completed",
        summary="Session B job finished.",
        token_estimate=50,
    )
    env_sys = SubJobReturnEnvelope(
        journey_id="j_sys_routine",
        status="completed",
        summary="System scheduled routine finished.",
        token_estimate=40,
    )

    nudge_a = signaler.signal_completion("session_alpha", env_a)
    nudge_b = signaler.signal_completion("session_beta", env_b)
    nudge_sys = signaler.signal_completion("system_scheduler", env_sys)

    assert nudge_a.session_id == "session_alpha"
    assert nudge_b.session_id == "session_beta"
    assert nudge_sys.session_id == "system_scheduler"

    # Polling for session_alpha receives its own nudge and system broadcasts, but NOT session_beta
    polled_a = signaler.poll_ambient_nudges(session_id="session_alpha")
    assert nudge_a in polled_a
    assert nudge_sys in polled_a
    assert nudge_b not in polled_a

    # Session beta's nudge remains in the queue
    assert len(signaler._nudge_queue) == 1
    assert signaler._nudge_queue[0] == nudge_b

    # Polling for session_beta retrieves its nudge
    polled_b = signaler.poll_ambient_nudges(session_id="session_beta")
    assert polled_b == [nudge_b]
    assert len(signaler._nudge_queue) == 0

