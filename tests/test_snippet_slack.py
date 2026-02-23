# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""TS5.* — Slack rendering tests for snippets."""

import pytest

from momento.snippet import generate_snippet, resolve_range
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    make_snippet_day,
    make_entry,
    hours_ago,
)
from tests.conftest import insert_entries


# ---------------------------------------------------------------------------
# TS5.1 — Basic slack
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestBasicSlack:
    """TS5.1: slack format uses correct emoji prefixes."""

    def test_slack_emojis(self, db):
        entries = [e for e in make_snippet_day() if e["project_id"] == MOCK_PROJECT_ID]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="slack", project_name=MOCK_PROJECT_NAME,
        )

        assert "\U0001f4cb" in output  # header emoji
        assert "\u2705" in output  # accomplished
        assert "\U0001f4cc" in output  # decision
        assert "\u26a0\ufe0f" in output  # gotcha
        assert "\U0001f504" in output  # in-progress


# ---------------------------------------------------------------------------
# TS5.2 — One line per item
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestOneLinePerItem:
    """TS5.2: multi-line content collapses to single line."""

    def test_no_embedded_newlines(self, db):
        entries = [
            make_entry(content="Line one.\nLine two.\nLine three.",
                       type="decision", tags=["server"], branch="main",
                       created_at=hours_ago(1)),
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="slack", project_name=MOCK_PROJECT_NAME,
        )

        # Each content line should be a single line (no \n within entry)
        lines = output.strip().split("\n")
        content_lines = [l for l in lines[1:] if l]  # Skip header + blank lines
        for line in content_lines:
            # The content should have been flattened
            assert "Line one." in line or line.startswith("(")


# ---------------------------------------------------------------------------
# TS5.3 — Max 15 lines
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestMaxSlackLines:
    """TS5.3: slack output is capped at 15 content lines + header."""

    def test_truncation(self, db):
        # Create entries across multiple types to exceed 15 content lines
        entries = []
        for i in range(6):
            entries.append(make_entry(
                content=f"Decision {i}", type="decision",
                tags=["server"], branch="main", created_at=hours_ago(i + 1)))
        for i in range(6):
            entries.append(make_entry(
                content=f"Gotcha {i}", type="gotcha",
                tags=["server"], branch="main", created_at=hours_ago(i + 1)))
        for i in range(6):
            entries.append(make_entry(
                content=f"Pattern {i}", type="pattern",
                tags=["api"], branch=None, created_at=hours_ago(i + 1)))
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="slack", project_name=MOCK_PROJECT_NAME,
        )

        lines = [l for l in output.strip().split("\n") if l]  # non-empty lines
        # Header + max 15 content lines + "(+N more)" line
        assert len(lines) <= 17, f"Expected max 17 lines, got {len(lines)}"
        assert "(+" in output and "more)" in output


# ---------------------------------------------------------------------------
# TS5.4 — Empty slack
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestEmptySlack:
    """TS5.4: empty range shows header + empty message."""

    def test_empty_slack(self, db):
        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="slack", project_name=MOCK_PROJECT_NAME,
        )

        assert "\U0001f4cb" in output
        assert "(no entries for this period)" in output


# ---------------------------------------------------------------------------
# TS5.5 — Pattern emoji
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestPatternEmoji:
    """TS5.5: pattern entries get the ruler emoji."""

    def test_pattern_emoji(self, db):
        entries = [
            make_entry(content="All endpoints follow validate-authorize-execute-respond.",
                       type="pattern", tags=["api"], branch=None,
                       created_at=hours_ago(1)),
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="slack", project_name=MOCK_PROJECT_NAME,
        )

        assert "\U0001f4d0" in output  # ruler emoji for patterns
