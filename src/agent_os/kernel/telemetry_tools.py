"""Telemetry and observability tool implementations for health audit and RCA staging."""

import json
from pathlib import Path
from typing import Any

from agent_os.domain.policy import ActionTier
from agent_os.domain.tools import (
    ToolDefinition,
    ToolExecutionResult,
    ToolParameterSchema,
)
from agent_os.infrastructure.storage.telemetry_repo import TelemetryRepository
from agent_os.kernel.rca_stager import RcaProposalStager
from agent_os.kernel.signaling import CompletionSignaler
from agent_os.kernel.telemetry_collector import TelemetryCollector


class TelemetryToolSuite:
    """Tool suite providing agent access to local observability vitals and RCA staging."""

    def __init__(
        self,
        telemetry_repo: TelemetryRepository,
        rca_stager: RcaProposalStager,
        collector: TelemetryCollector | None = None,
        db_paths: list[Path] | None = None,
        signaler: CompletionSignaler | None = None,
    ) -> None:
        self.repo = telemetry_repo
        self.stager = rca_stager
        self.collector = collector or TelemetryCollector(telemetry_repo)
        self.db_paths = db_paths or []
        self.signaler = signaler

    def get_definitions(self) -> list[ToolDefinition]:
        """Return tool definitions and schemas for observability tools."""
        return [
            ToolDefinition(
                name="telemetry_get_health_summary",
                description="Query operational health vitals, error rates, and findings.",
                action_tier=ActionTier.READ,
                parameters=[
                    ToolParameterSchema(
                        name="hours",
                        type_name="integer",
                        description="Rolling window in hours for health stats (default 24).",
                        required=False,
                        default=24,
                    )
                ],
            ),
            ToolDefinition(
                name="telemetry_audit_errors",
                description="Retrieve recent error traces and events with root cause details.",
                action_tier=ActionTier.READ,
                parameters=[
                    ToolParameterSchema(
                        name="limit",
                        type_name="integer",
                        description="Maximum number of error records to inspect (default 10).",
                        required=False,
                        default=10,
                    )
                ],
            ),
            ToolDefinition(
                name="telemetry_stage_rca",
                description="Stage an RCA postmortem and remediation proposal into 00_Inbox.",
                action_tier=ActionTier.STATE_CHANGE,
                parameters=[
                    ToolParameterSchema(
                        name="title",
                        type_name="string",
                        description="Short, descriptive title of the issue.",
                        required=True,
                    ),
                    ToolParameterSchema(
                        name="issue_summary",
                        type_name="string",
                        description="Executive summary of the problem and its operational impact.",
                        required=True,
                    ),
                    ToolParameterSchema(
                        name="root_cause",
                        type_name="string",
                        description="Technical explanation of why the failure occurred.",
                        required=True,
                    ),
                    ToolParameterSchema(
                        name="suggested_fix",
                        type_name="string",
                        description="Concrete proposed remediation for human review.",
                        required=True,
                    ),
                    ToolParameterSchema(
                        name="severity",
                        type_name="string",
                        description="Severity level: low, medium, warning, high, critical.",
                        required=False,
                        default="warning",
                    ),
                ],
            ),
            ToolDefinition(
                name="telemetry_prune_old_records",
                description="Prune telemetry metrics, events, and spans older than retention_days.",
                action_tier=ActionTier.DESTRUCTIVE,
                parameters=[
                    ToolParameterSchema(
                        name="retention_days",
                        type_name="integer",
                        description="Days of history to retain (default 30).",
                        required=False,
                        default=30,
                    )
                ],
            ),
        ]

    def telemetry_get_health_summary(self, hours: int = 24) -> ToolExecutionResult:
        """Query operational health vitals and diagnostic findings."""
        report = self.collector.compile_health_report(db_paths=self.db_paths, hours=hours)
        payload = {
            "health_score": report.health_score,
            "error_rate_percent": report.error_rate_percent,
            "avg_latency_ms": report.avg_latency_ms,
            "total_turns_24h": report.total_turns_24h,
            "tool_reliability": report.tool_reliability,
            "database_sizes_mb": report.database_sizes_mb,
            "findings": report.findings,
        }
        return ToolExecutionResult(
            tool_name="telemetry_get_health_summary",
            success=True,
            output=json.dumps(payload, indent=2),
        )

    def telemetry_audit_errors(self, limit: int = 10) -> ToolExecutionResult:
        """Query recent error spans and operational events."""
        error_spans = self.repo.get_recent_spans(status="error", limit=limit)
        error_events = self.repo.get_recent_events(severity="error", limit=limit)

        records: list[dict[str, Any]] = []
        for s in error_spans:
            records.append(
                {
                    "type": "span",
                    "subsystem": s.subsystem,
                    "name": s.name,
                    "duration_ms": s.duration_ms,
                    "error": s.error,
                    "started_at": s.started_at.isoformat(),
                }
            )
        for e in error_events:
            records.append(
                {
                    "type": "event",
                    "event_type": e.event_type,
                    "message": e.message,
                    "recorded_at": e.recorded_at.isoformat(),
                }
            )

        return ToolExecutionResult(
            tool_name="telemetry_audit_errors",
            success=True,
            output=json.dumps(records, indent=2),
        )

    def telemetry_stage_rca(
        self,
        title: str,
        issue_summary: str,
        root_cause: str,
        suggested_fix: str,
        severity: str = "warning",
    ) -> ToolExecutionResult:
        """Draft and stage an RCA proposal to 00_Inbox."""
        try:
            dest_path = self.stager.stage_issue(
                title=title,
                issue_summary=issue_summary,
                root_cause=root_cause,
                suggested_remediation=suggested_fix,
                severity=severity,
            )
            if self.signaler is not None:
                self.signaler.signal_discovery(
                    session_id="",
                    message=f"I staged an RCA postmortem proposal in 00_Inbox: {title}",
                    pattern_id="rca_proposal",
                )
            return ToolExecutionResult(
                tool_name="telemetry_stage_rca",
                success=True,
                output=f"Successfully staged RCA proposal to: {dest_path.name}",
            )
        except Exception as exc:
            return ToolExecutionResult(
                tool_name="telemetry_stage_rca",
                success=False,
                output="",
                error=f"Failed to stage RCA proposal: {exc}",
            )

    def telemetry_prune_old_records(self, retention_days: int = 30) -> ToolExecutionResult:
        """Prune telemetry metrics, events, and spans older than retention_days."""
        try:
            count = self.repo.prune_old_telemetry(retention_days=retention_days)
            return ToolExecutionResult(
                tool_name="telemetry_prune_old_records",
                success=True,
                output=f"Successfully pruned {count} records older than {retention_days} days.",
            )
        except Exception as exc:
            return ToolExecutionResult(
                tool_name="telemetry_prune_old_records",
                success=False,
                output="",
                error=f"Failed to prune telemetry: {exc}",
            )
