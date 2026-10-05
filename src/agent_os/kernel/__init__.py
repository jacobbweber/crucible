"""Kernel package for agent-os."""

from agent_os.kernel.chat_loop import CompanionChatLoop
from agent_os.kernel.prompt_assembler import PromptAssembler
from agent_os.kernel.tone import get_tone_instructions

__all__ = [
    "CompanionChatLoop",
    "PromptAssembler",
    "get_tone_instructions",
]
