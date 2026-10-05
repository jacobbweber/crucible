"""Unit tests for PromptAssembler prompt compilation and context isolation."""

import pytest
from pydantic import ValidationError

from agent_os.domain.companion import CompanionConfig, HumanProfile, TonePreset
from agent_os.kernel.prompt_assembler import PromptAssembler
from agent_os.kernel.tone import get_tone_instructions


def test_assemble_system_prompt_includes_name_and_tone() -> None:
    """Verify companion name and selected tone directive are rendered in system prompt."""
    config = CompanionConfig(
        name="Astra",
        tone=TonePreset.CONCISE,
    )
    assembler = PromptAssembler(config)
    result = assembler.assemble_system_prompt(recalled_facts_block="User works on agent-os.")

    assert "Astra" in result.rendered_prompt
    assert get_tone_instructions(TonePreset.CONCISE) in result.rendered_prompt
    assert "<recalled_facts>\nUser works on agent-os.\n</recalled_facts>" in result.rendered_prompt
    assert result.token_estimate == len(result.rendered_prompt) // 4
    assert not result.has_human_profile

    # Verify EMPTY tone leaves out tone directive
    empty_tone_config = CompanionConfig(name="CoreAgent", tone=TonePreset.EMPTY)
    empty_result = PromptAssembler(empty_tone_config).assemble_system_prompt()
    assert "CoreAgent" in empty_result.rendered_prompt
    assert "<recalled_facts>" not in empty_result.rendered_prompt


def test_human_profile_isolation_tags() -> None:
    """Verify human profile context is scoped within <human_profile> tags."""
    profile = HumanProfile(
        summary="Experienced distributed systems engineer.",
        preferences=["Dark mode", "Async-first execution"],
    )
    config = CompanionConfig(name="Astra", human_profile=profile)
    assembler = PromptAssembler(config)

    result = assembler.assemble_system_prompt()
    assert result.has_human_profile
    assert "<human_profile>" in result.rendered_prompt
    assert "</human_profile>" in result.rendered_prompt
    assert "Experienced distributed systems engineer." in result.rendered_prompt
    assert "- Dark mode" in result.rendered_prompt
    assert "- Async-first execution" in result.rendered_prompt


def test_human_profile_character_clamp() -> None:
    """Verify human profile exceeding character length limits is rejected by validation."""
    valid_profile = HumanProfile(summary="x" * 2500)
    assert len(valid_profile.summary) == 2500

    with pytest.raises(ValidationError):
        HumanProfile(summary="x" * 2501)


def test_worker_scratchpad_omits_human_profile() -> None:
    """Verify export_for_worker_scratchpad strictly excludes human profile and user identity."""
    profile = HumanProfile(
        summary="Confidential user bio: Alice works at Acme Corp.",
        preferences=["Prefers TypeScript", "Timezone UTC-8"],
    )
    config = CompanionConfig(
        name="WorkerCompanion",
        tone=TonePreset.ANALYTICAL,
        human_profile=profile,
    )
    assembler = PromptAssembler(config)

    worker_prompt = assembler.export_for_worker_scratchpad()

    assert "WorkerCompanion" in worker_prompt
    assert get_tone_instructions(TonePreset.ANALYTICAL) in worker_prompt
    assert "<human_profile>" not in worker_prompt
    assert "</human_profile>" not in worker_prompt
    assert "Confidential user bio" not in worker_prompt
    assert "Alice" not in worker_prompt
    assert "Acme Corp" not in worker_prompt
    assert "TypeScript" not in worker_prompt
    assert "UTC-8" not in worker_prompt
