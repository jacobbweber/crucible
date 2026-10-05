"""Kernel package for agent-os."""

from agent_os.kernel.brief_assembler import TaskBriefAssembler
from agent_os.kernel.chat_loop import CompanionChatLoop
from agent_os.kernel.credential_proxy import CredentialProxyGate
from agent_os.kernel.dispatcher import ZeroCatalogDispatcher
from agent_os.kernel.education_tools import EducationToolSuite
from agent_os.kernel.fact_prefetcher import FactPrefetcher
from agent_os.kernel.graduation import GraduationService
from agent_os.kernel.master_kernel import AgentOSKernel
from agent_os.kernel.pedagogical import PedagogicalOrchestrator
from agent_os.kernel.pipeline import JobAssemblyPipeline
from agent_os.kernel.policy_gate import ToolPolicyGate
from agent_os.kernel.prompt_assembler import PromptAssembler
from agent_os.kernel.recipe_chamber import RecipeChamber
from agent_os.kernel.return_marshaller import SubJobMarshaller
from agent_os.kernel.runbook_parser import PocockRunbookParser
from agent_os.kernel.runner import NativeRunner
from agent_os.kernel.scheduler import EmbeddedSchedulerDaemon
from agent_os.kernel.signaling import CompletionSignaler
from agent_os.kernel.srs_engine import SRSEngine
from agent_os.kernel.tone import get_tone_instructions
from agent_os.kernel.wiki_tools import WikiToolSuite

__all__ = [
    "AgentOSKernel",
    "CompanionChatLoop",
    "CompletionSignaler",
    "CredentialProxyGate",
    "EducationToolSuite",
    "EmbeddedSchedulerDaemon",
    "FactPrefetcher",
    "GraduationService",
    "JobAssemblyPipeline",
    "NativeRunner",
    "PedagogicalOrchestrator",
    "PocockRunbookParser",
    "PromptAssembler",
    "RecipeChamber",
    "SRSEngine",
    "SubJobMarshaller",
    "TaskBriefAssembler",
    "ToolPolicyGate",
    "WikiToolSuite",
    "ZeroCatalogDispatcher",
    "get_tone_instructions",
]
