"""Domain models for scheduled routines, catch-up policies, and execution logs."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

CatchUpPolicy = Literal[
    "run_once_immediately", "skip_to_next", "queue_all", "respectful", "notify_and_skip"
]


class ScheduledRoutine(BaseModel):
    """Declarative specification for an automated recurring background routine."""

    routine_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    cron_expression: str = Field(min_length=1)
    task_payload: str = Field(min_length=1)
    catch_up_policy: CatchUpPolicy = "run_once_immediately"
    is_active: bool = True
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None


class RoutineExecutionLog(BaseModel):
    """Audit log recording the outcome of a single routine execution attempt."""

    execution_id: str = Field(default_factory=lambda: f"exec_{uuid.uuid4().hex[:12]}")
    routine_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    status: Literal["success", "failed", "skipped_concurrency", "skipped_policy"]
    error_message: str | None = None
