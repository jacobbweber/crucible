"""Tone preset repository and styling directive resolver."""

from agent_os.domain.companion import TonePreset


def get_tone_instructions(tone: TonePreset) -> str:
    """Return styling directive instructions for a given tone preset."""
    match tone:
        case TonePreset.CONCISE:
            return (
                "Respond tersely. Favor factual bullets, omit conversational filler and preambles."
            )
        case TonePreset.FRIENDLY:
            return "Maintain a supportive, helpful tone while remaining technically accurate."
        case TonePreset.ANALYTICAL:
            return (
                "Examine trade-offs explicitly, structure responses systematically, "
                "and state technical assumptions."
            )
        case TonePreset.EMPTY:
            return ""
