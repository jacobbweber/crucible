"""Controlled vocabulary for capability signatures, verbs, scopes, and resources."""

import re
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, Field

from agent_os.domain.policy import ActionTier


class Verb(StrEnum):
    """Closed vocabulary of operations an ingredient or intent can perform."""

    READ = "read"
    LIST = "list"
    SEARCH = "search"
    WRITE = "write"
    UPDATE = "update"
    DELETE = "delete"
    EXECUTE = "execute"
    AUDIT = "audit"
    REVIEW = "review"
    CAPTURE = "capture"
    STATUS = "status"


VERB_DESCRIPTIONS: dict[Verb, str] = {
    Verb.READ: "Inspect or retrieve data from a target without mutating it",
    Verb.LIST: "Enumerate items, children, or members of a collection or location",
    Verb.SEARCH: "Query or filter records by criteria, topics, or keywords",
    Verb.WRITE: "Create or replace an item or content",
    Verb.UPDATE: "Modify part of an existing item or configuration",
    Verb.DELETE: "Remove, purge, or nuke an item or collection",
    Verb.EXECUTE: "Run a script, process, or sandboxed command",
    Verb.AUDIT: "Examine health, status, diagnostics, or error rates across components",
    Verb.REVIEW: "Interactive learning, recall, or assessment session",
    Verb.CAPTURE: "Record a note, summary, or fact into memory or vault",
    Verb.STATUS: "Report current operating state or configuration",
}


class Scope(StrEnum):
    """Boundaries within which an operation executes or resources reside."""

    HOST = "host"
    WORKSPACE = "workspace"
    VAULT = "vault"
    NETWORK = "network"
    RUNTIME = "runtime"
    SESSION = "session"


SCOPE_DESCRIPTIONS: dict[Scope, str] = {
    Scope.HOST: "The host operating system outside the sandbox boundary",
    Scope.WORKSPACE: "The isolated workspace directory and project files",
    Scope.VAULT: "The encrypted personal knowledge vault",
    Scope.NETWORK: "Network services and remote endpoints",
    Scope.RUNTIME: "Agent OS runtime internals, containers, and services",
    Scope.SESSION: "Conversation, memory, and session state",
}


class Effect(StrEnum):
    """Impact tier of executing an operation."""

    READ_ONLY = "read_only"
    STATE_CHANGE = "state_change"
    DESTRUCTIVE = "destructive"

    def to_action_tier(self) -> ActionTier:
        """Map ingredient Effect to domain ActionTier."""
        mapping = {
            Effect.READ_ONLY: ActionTier.READ,
            Effect.STATE_CHANGE: ActionTier.STATE_CHANGE,
            Effect.DESTRUCTIVE: ActionTier.DESTRUCTIVE,
        }
        return mapping[self]

    @classmethod
    def from_action_tier(cls, tier: ActionTier) -> "Effect":
        """Map domain ActionTier to ingredient Effect."""
        mapping = {
            ActionTier.READ: cls.READ_ONLY,
            ActionTier.STATE_CHANGE: cls.STATE_CHANGE,
            ActionTier.DESTRUCTIVE: cls.DESTRUCTIVE,
        }
        return mapping[tier]


EFFECT_DESCRIPTIONS: dict[Effect, str] = {
    Effect.READ_ONLY: "Side-effect-free observation or retrieval",
    Effect.STATE_CHANGE: "Mutates state but is reversible or non-destructive",
    Effect.DESTRUCTIVE: "Permanent deletion, overwrite, or irreversible change",
}

_RESOURCE_NAME_PATTERN = re.compile(r"^[a-z_]+(\.[a-z_]+)*$")


class ResourceEntry(BaseModel):
    """A registered resource type within the controlled vocabulary."""

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    parent: str | None = None


class ResourceVocabularyRegistry:
    """Registry maintaining known resource types and their descriptions."""

    _DEFAULT_RESOURCES: ClassVar[dict[str, str]] = {
        "filesystem.file": "A single file on the filesystem",
        "filesystem.directory": "A directory or folder on the filesystem",
        "filesystem.disk": "Storage capacity, partitions, and drive volumes",
        "vault.note": "A personal knowledge note or document in the encrypted vault",
        "session.history": "Past conversation turns and session messages",
        "runtime.container": "Docker or containerized services",
        "runtime.health": "System health diagnostics, error rates, and telemetry",
        "git.repository": "A Git repository, working tree, and commit history",
        "study.flashcard": "Spaced-repetition flashcards and study decks",
        "agent.recipe": "Reusable recipes and workflow automation templates",
        "agent.tool": "Capabilities and tool plugins",
        "workspace.file": "A file within the isolated workspace boundary",
        "workspace.directory": "A directory within the isolated workspace boundary",
        "workspace.command": "A sandboxed process or command invocation",
    }

    def __init__(self, seed_defaults: bool = True) -> None:
        self._resources: dict[str, ResourceEntry] = {}
        if seed_defaults:
            for name, desc in self._DEFAULT_RESOURCES.items():
                self.register(name, desc)

    def register(self, name: str, description: str, parent: str | None = None) -> ResourceEntry:
        """Register a new resource type in the vocabulary."""
        if not _RESOURCE_NAME_PATTERN.match(name):
            raise ValueError(f"Resource name '{name}' must match pattern '^[a-z_]+(\\.[a-z_]+)*$'.")
        clean_desc = description.strip()
        if not clean_desc:
            raise ValueError(f"Resource '{name}' must have a non-empty description.")
        entry = ResourceEntry(name=name, description=clean_desc, parent=parent)
        self._resources[name] = entry
        return entry

    def get(self, name: str) -> ResourceEntry | None:
        """Lookup a registered resource entry."""
        return self._resources.get(name)

    def is_valid(self, name: str) -> bool:
        """Check whether a resource is registered."""
        return name in self._resources

    def list_resources(self) -> list[ResourceEntry]:
        """Return all registered resources sorted by name."""
        return sorted(self._resources.values(), key=lambda r: r.name)

    def get_descriptions(self) -> dict[str, str]:
        """Return a mapping of resource name to description."""
        return {r.name: r.description for r in self.list_resources()}

    @classmethod
    def default_registry(cls) -> "ResourceVocabularyRegistry":
        """Factory returning a registry seeded with standard resource types."""
        return cls(seed_defaults=True)
