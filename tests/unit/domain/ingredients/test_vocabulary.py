"""Unit tests for ingredients vocabulary, resource registry, and capability signatures."""

import pytest

from agent_os.domain.ingredients.signature import CapabilitySignature
from agent_os.domain.ingredients.vocabulary import (
    EFFECT_DESCRIPTIONS,
    SCOPE_DESCRIPTIONS,
    VERB_DESCRIPTIONS,
    Effect,
    ResourceVocabularyRegistry,
    Scope,
    Verb,
)
from agent_os.domain.policy import ActionTier


def test_verbs_and_scopes_have_descriptions() -> None:
    """Every verb and scope must carry a non-empty human/model description."""
    for verb in Verb:
        assert verb in VERB_DESCRIPTIONS
        assert len(VERB_DESCRIPTIONS[verb]) > 5
    for scope in Scope:
        assert scope in SCOPE_DESCRIPTIONS
        assert len(SCOPE_DESCRIPTIONS[scope]) > 5
    for effect in Effect:
        assert effect in EFFECT_DESCRIPTIONS
        assert len(EFFECT_DESCRIPTIONS[effect]) > 5


def test_effect_action_tier_mapping() -> None:
    """Effect must map bidirectionally to ActionTier."""
    assert Effect.READ_ONLY.to_action_tier() == ActionTier.READ
    assert Effect.STATE_CHANGE.to_action_tier() == ActionTier.STATE_CHANGE
    assert Effect.DESTRUCTIVE.to_action_tier() == ActionTier.DESTRUCTIVE

    assert Effect.from_action_tier(ActionTier.READ) == Effect.READ_ONLY
    assert Effect.from_action_tier(ActionTier.STATE_CHANGE) == Effect.STATE_CHANGE
    assert Effect.from_action_tier(ActionTier.DESTRUCTIVE) == Effect.DESTRUCTIVE


def test_resource_vocabulary_registry() -> None:
    """Registry validates resource naming patterns and manages entries."""
    reg = ResourceVocabularyRegistry(seed_defaults=True)
    assert reg.is_valid("filesystem.file")
    assert reg.is_valid("vault.note")
    assert not reg.is_valid("unknown_resource")

    # Dynamic registration
    entry = reg.register("docker.volume", "A Docker named storage volume")
    assert entry.name == "docker.volume"
    assert reg.is_valid("docker.volume")

    # Invalid names rejected
    with pytest.raises(ValueError, match="pattern"):
        reg.register("Invalid-Resource!", "description")

    with pytest.raises(ValueError, match="non-empty"):
        reg.register("valid.resource", "   ")


def test_capability_signature_formatting_and_parsing() -> None:
    """CapabilitySignature round-trips canonical string representation."""
    sig = CapabilitySignature(
        verb=Verb.READ,
        resource="filesystem.file",
        scope=Scope.HOST,
        effect=Effect.READ_ONLY,
    )
    canonical = sig.canonical_str()
    assert canonical == "read:filesystem.file@host[read_only]"
    assert str(sig) == canonical

    parsed = CapabilitySignature.from_string(canonical)
    assert parsed.verb == Verb.READ
    assert parsed.resource == "filesystem.file"
    assert parsed.scope == Scope.HOST
    assert parsed.effect == Effect.READ_ONLY
    assert sig.matches(parsed)


def test_capability_signature_malformed_string_rejected() -> None:
    """Malformed signature strings raise ValueError."""
    with pytest.raises(ValueError, match="Invalid capability signature format"):
        CapabilitySignature.from_string("not_a_valid_signature")
