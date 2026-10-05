"""Unit tests for tone preset resolution."""

from agent_os.domain.companion import TonePreset
from agent_os.kernel.tone import get_tone_instructions


def test_tone_preset_resolutions() -> None:
    """Verify each tone enum returns expected directives and EMPTY returns an empty string."""
    assert (
        get_tone_instructions(TonePreset.CONCISE)
        == "Respond tersely. Favor factual bullets, omit conversational filler and preambles."
    )
    assert (
        get_tone_instructions(TonePreset.FRIENDLY)
        == "Maintain a supportive, helpful tone while remaining technically accurate."
    )
    assert get_tone_instructions(TonePreset.ANALYTICAL) == (
        "Examine trade-offs explicitly, structure responses systematically, "
        "and state technical assumptions."
    )
    assert get_tone_instructions(TonePreset.EMPTY) == ""
