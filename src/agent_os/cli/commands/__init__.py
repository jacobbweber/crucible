"""Command group registration."""

from agent_os.cli.commands import background, execution, memory, session
from agent_os.cli.registry import CommandRegistry


def build_registry() -> CommandRegistry:
    """Create a registry populated with every REPL command group."""
    registry = CommandRegistry()
    for module in (session, memory, execution, background):
        module.register(registry)
    return registry
