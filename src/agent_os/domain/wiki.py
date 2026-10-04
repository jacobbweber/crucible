"""Domain models for the wiki vault subsystem."""

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class ProtectedFolder(StrEnum):
    """Protected root folder names in the wiki vault."""

    INBOX = "00_Inbox"
    NOTES = "01_Notes"
    RESOURCES = "02_Resources"
    ARCHIVE = "03_Archive"


class NoteFrontmatter(BaseModel):
    """Metadata schema stored in note YAML frontmatter."""

    title: str = Field(min_length=1)
    category: str = Field(min_length=1)
    tags: list[str] = Field(min_length=1)
    created: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated: datetime = Field(default_factory=lambda: datetime.now(UTC))


class NoteRecord(BaseModel):
    """Represents a loaded note record."""

    path: Path
    relative_path: str
    frontmatter: NoteFrontmatter
    body: str


class GraduationFailure(BaseModel):
    """Details about a note that failed graduation."""

    filename: str
    reasons: list[str]


class GraduationReport(BaseModel):
    """Summary report of an inbox graduation run."""

    graduated_count: int
    failed_count: int
    graduated_files: list[str]
    failures: list[GraduationFailure]
