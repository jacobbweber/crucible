"""Deterministic inbox graduation coordinator service."""

from agent_os.domain.wiki import GraduationReport
from agent_os.infrastructure.wiki.store import WikiStore


class GraduationService:
    """Coordinates validation and promotion of staged notes from 00_Inbox to 01_Notes."""

    def __init__(self, wiki_store: WikiStore) -> None:
        self.store = wiki_store
        self.wiki_store = wiki_store

    def execute_graduation(self, collision_resolution: str = "rename") -> GraduationReport:
        """Scan 00_Inbox and graduate compliant notes into structured category folders."""
        return self.store.graduate_inbox(collision_resolution=collision_resolution)
