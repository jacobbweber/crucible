"""Kernel package for agent-os."""

from agent_os.kernel.chat_loop import CompanionChatLoop
from agent_os.kernel.credential_proxy import CredentialProxyGate
from agent_os.kernel.fact_prefetcher import FactPrefetcher
from agent_os.kernel.graduation import GraduationService
from agent_os.kernel.policy_gate import ToolPolicyGate
from agent_os.kernel.prompt_assembler import PromptAssembler
from agent_os.kernel.runner import NativeRunner
from agent_os.kernel.tone import get_tone_instructions
from agent_os.kernel.wiki_tools import WikiToolSuite

__all__ = [
    "CompanionChatLoop",
    "CredentialProxyGate",
    "FactPrefetcher",
    "GraduationService",
    "NativeRunner",
    "PromptAssembler",
    "ToolPolicyGate",
    "WikiToolSuite",
    "get_tone_instructions",
]
