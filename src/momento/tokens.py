# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Token estimation and formatting utilities."""

from datetime import datetime, timezone


def estimate_tokens(text: str) -> int:
    """Estimate token count for rendered markdown text.

    Uses len(text) / 4 approximation. Includes headers, metadata
    brackets, markdown scaffolding, and blank lines.

    The 2000-token cap is a budget, not a precision target.
    """
    return len(text) // 4


def format_age(iso_timestamp: str) -> str:
    """Format an ISO timestamp as a short relative age string.

    Examples: '3d ago', '2h ago', '15m ago'.
    """
    dt = datetime.strptime(iso_timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    delta = datetime.now(timezone.utc) - dt
    if delta.days > 0:
        return f"{delta.days}d ago"
    hours = delta.seconds // 3600
    if hours > 0:
        return f"{hours}h ago"
    minutes = delta.seconds // 60
    return f"{minutes}m ago"