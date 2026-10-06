"""Unit tests for TaskBriefAssembler 5-beat assembly, context isolation, and runbooks."""

import pytest

from agent_os.domain.gateway import estimate_tokens
from agent_os.domain.runbook import RunbookDefinition, TaskBrief
from agent_os.kernel.brief_assembler import TaskBriefAssembler


def test_compile_packet_5_beat_structure() -> None:
    """Provide TaskBrief; assert generated system prompt contains all 5 beats clearly tagged."""
    brief = TaskBrief(
        role_anchor="Senior Infrastructure Engineer",
        core_directive="Automate Redis cluster provisioning",
        scope_invariants=["Do not modify production VPC", "Use IaC templates"],
        capability_strategy="Direct Terraform deployment",
        completion_standard="Cluster status healthy and accepting connections",
    )
    packet = TaskBriefAssembler.compile_packet(brief)

    assert "<role_anchor>Senior Infrastructure Engineer</role_anchor>" in packet.system_prompt
    assert (
        "<core_directive>Automate Redis cluster provisioning</core_directive>"
        in packet.system_prompt
    )
    assert "<scope_invariants>" in packet.system_prompt
    assert "- Do not modify production VPC" in packet.system_prompt
    assert "- Use IaC templates" in packet.system_prompt
    assert (
        "<capability_strategy>Direct Terraform deployment</capability_strategy>"
        in packet.system_prompt
    )
    assert (
        "<completion_standard>"
        "Cluster status healthy and accepting connections"
        "</completion_standard>"
    ) in packet.system_prompt
    assert packet.token_estimate == estimate_tokens(packet.system_prompt)
    assert packet.target_tools == []


def test_compile_packet_context_isolation() -> None:
    """Verify generated prompt contains zero <human_profile> tags or personal user context."""
    brief = TaskBrief(
        role_anchor="Code Auditor",
        core_directive="Audit security configurations",
        scope_invariants=["No network requests"],
        capability_strategy="Static analysis",
        completion_standard="Report emitted",
    )
    packet = TaskBriefAssembler.compile_packet(brief)

    assert "<human_profile>" not in packet.system_prompt
    assert "</human_profile>" not in packet.system_prompt

    # Attempting to compile brief with human_profile context triggers isolation violation
    leaky_brief = TaskBrief(
        role_anchor="Auditor",
        core_directive="Analyze <human_profile>Alice preferences</human_profile>",
        scope_invariants=["Invariant 1"],
        capability_strategy="Strategy",
        completion_standard="Done",
    )
    with pytest.raises(ValueError, match="Context isolation violation"):
        TaskBriefAssembler.compile_packet(leaky_brief)


def test_compile_packet_with_runbook() -> None:
    """Provide brief and runbook; verify steps and criteria are appended and tools populated."""
    brief = TaskBrief(
        role_anchor="Release Orchestrator",
        core_directive="Deploy payment gateway",
        scope_invariants=["Zero downtime deployment"],
        capability_strategy="Blue/green switch",
        completion_standard="Traffic routed to new cluster",
    )
    runbook = RunbookDefinition(
        name="deploy-payment-service",
        description="Deploys payment microservice safely",
        required_tools=["k8s_apply", "curl_probe"],
        tags=["deployment", "payments"],
        what_it_does="Rolls out payment microservice pods",
        when_to_reach_for_it="When releasing new payment versions",
        prerequisites=["Cluster access granted"],
        procedural_steps=["Deploy green pods", "Execute smoke tests"],
        verification_criteria=["Smoke test suite passes", "Error rate below 0.01%"],
    )

    packet = TaskBriefAssembler.compile_packet(brief, runbook)

    assert '<runbook name="deploy-payment-service">' in packet.system_prompt
    assert (
        "<what_it_does>Rolls out payment microservice pods</what_it_does>" in packet.system_prompt
    )
    assert "<procedural_steps>" in packet.system_prompt
    assert "- Deploy green pods" in packet.system_prompt
    assert "- Execute smoke tests" in packet.system_prompt
    assert "<verification_criteria>" in packet.system_prompt
    assert "- Smoke test suite passes" in packet.system_prompt
    assert "- Error rate below 0.01%" in packet.system_prompt
    assert packet.target_tools == ["k8s_apply", "curl_probe"]
    assert packet.token_estimate == estimate_tokens(packet.system_prompt)
