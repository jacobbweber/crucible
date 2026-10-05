"""Unit tests for SubJobMarshaller summary compression and envelope bounds."""

from agent_os.kernel.return_marshaller import SubJobMarshaller


def test_marshaller_summary_clamping() -> None:
    """Pass a 2,000-char string; verify summary clamped <= 800 chars and token_estimate <= 200."""
    raw_2000 = "A" * 2000
    envelope = SubJobMarshaller.marshal_envelope(
        journey_id="jrn_test_1",
        status="completed",
        raw_output=raw_2000,
    )

    assert len(envelope.summary) <= 800
    assert envelope.summary.endswith("...")
    assert len(envelope.summary) == 800
    assert envelope.token_estimate <= 200
    assert envelope.token_estimate == len(envelope.summary) // 4


def test_marshal_envelope_fields() -> None:
    """Verify envelope correctly bundles journey_id, status, artifact_paths, and duration_ms."""
    artifacts = ["artifacts/report.md", "artifacts/diff.patch"]
    mutations = ["updated config.json", "created temp.db"]

    envelope = SubJobMarshaller.marshal_envelope(
        journey_id="jrn_test_42",
        status="completed",
        raw_output="All operations executed cleanly.",
        artifact_paths=artifacts,
        state_mutations=mutations,
        duration_ms=450,
    )

    assert envelope.journey_id == "jrn_test_42"
    assert envelope.status == "completed"
    assert envelope.summary == "All operations executed cleanly."
    assert envelope.artifact_paths == artifacts
    assert envelope.state_mutations == mutations
    assert envelope.duration_ms == 450
    assert envelope.token_estimate == len(envelope.summary) // 4
