# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Data models for Momento entries."""

from dataclasses import dataclass, field


ENTRY_TYPES = ("gotcha", "decision", "pattern", "plan", "session_state")
SOURCE_TYPES = ("manual", "compaction", "error_pair")

# Hard character limits per type, enforced at MCP layer
SIZE_LIMITS = {
    "session_state": 500,
    "decision": 800,
    "plan": 800,
    "gotcha": 400,
    "pattern": 400,
}

# Per-type hints for rejection messages
SIZE_HINTS = {
    "session_state": "Focus on: current task, what changed, and next step.",
    "decision": "Include: what was decided, why, what was rejected.",
    "plan": "Include: phases, current status, key rationale.",
    "gotcha": "One pitfall, one fix. Be specific.",
    "pattern": "One convention, one example.",
}


@dataclass
class Entry:
    """A single knowledge entry."""

    id: str
    content: str
    content_hash: str
    type: str
    tags: list[str]
    project_id: str | None
    project_name: str | None
    branch: str | None
    source_type: str
    confidence: float
    created_at: str
    updated_at: str


@dataclass
class RestoreResult:
    """Result of a restore-mode retrieval."""

    entries: list[Entry] = field(default_factory=list)
    total_tokens: int = 0
    rendered: str = ""


@dataclass
class ThresholdReport:
    """Maturity threshold check results for audit."""

    total_entries: int
    durable_entries: int
    distinct_types: int
    days_active: int
    passed: bool


@dataclass
class AdapterCheck:
    """Single adapter check result."""

    name: str
    found: bool
    critical: bool


@dataclass
class AuditResult:
    """Full audit comparison result."""

    project_name: str
    threshold_passed: bool
    threshold_report: ThresholdReport | None
    missing_entries: list[Entry] = field(default_factory=list)
    stale_references: list[str] = field(default_factory=list)
    adapter_checks: list[AdapterCheck] = field(default_factory=list)
    coverage_pct: int = 0
    durable_total: int = 0


@dataclass
class FixResult:
    """Result of --fix mode CLAUDE.md patching."""

    entries_added: int = 0
    entries_skipped: int = 0
    sections_created: int = 0
    backup_path: str = ""
    lines_before: int = 0
    lines_after: int = 0