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
