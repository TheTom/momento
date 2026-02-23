# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""TS3.* — Markdown rendering tests for snippets."""

import pytest

from momento.snippet import (
    generate_snippet,
    render_markdown,
    group_entries,
    resolve_range,
    query_entries,
    SnippetMeta,
    SnippetSections,
)
from momento.models import Entry
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    make_snippet_day,
    make_snippet_durable_only,
    make_entry,
    hours_ago,
)
from tests.conftest import insert_entries


def _entry_to_model(d: dict) -> Entry:
    return Entry(
        id=d["id"], content=d["content"], content_hash=d["content_hash"],
        type=d["type"], tags=d["tags"], project_id=d["project_id"],
        project_name=d["project_name"], branch=d["branch"],
        source_type=d["source_type"], confidence=d["confidence"],
        created_at=d["created_at"], updated_at=d["updated_at"],
    )


# ---------------------------------------------------------------------------
# TS3.1 — Full daily markdown
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestFullDailyMarkdown:
    """TS3.1: full daily markdown has all expected sections."""

    def test_daily_markdown_structure(self, db):
        # Insert only project-A entries (exclude cross-project)
        entries = [e for e in make_snippet_day() if e["project_id"] == MOCK_PROJECT_ID]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )

        assert "snippet —" in output
        assert MOCK_PROJECT_NAME in output
        assert "### Accomplished" in output
        assert "### Decisions Made" in output
        assert "### Discovered" in output
        assert "### Still In Progress" in output
        assert "### Conventions Established" in output
        # Each entry rendered as list item
        assert "- " in output


# ---------------------------------------------------------------------------
# TS3.2 — Empty sections not rendered
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestEmptySectionsNotRendered:
    """TS3.2: sections with no entries are omitted."""

    def test_only_decisions_rendered(self, db):
        entries = [e for e in make_snippet_durable_only() if e["type"] == "decision"]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )

        assert "### Decisions Made" in output
        assert "### Accomplished" not in output
        assert "### Discovered" not in output
        assert "### Still In Progress" not in output
        assert "### Conventions Established" not in output


# ---------------------------------------------------------------------------
# TS3.3 — Empty range markdown
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestEmptyRangeMarkdown:
    """TS3.3: empty range shows helpful message."""

    def test_empty_range(self, db):
        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )

        assert "No entries found for this time range." in output
        assert "momento save" in output or "log_knowledge" in output


# ---------------------------------------------------------------------------
# TS3.4 — Branch shown in header
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestBranchInHeader:
    """TS3.4: branch name appears in markdown header."""

    def test_branch_in_subheader(self, db):
        entries = [make_entry(
            content="Some decision.", type="decision", tags=["server"],
            branch="feature/billing-rewrite", created_at=hours_ago(1),
        )]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", branch="feature/billing-rewrite",
            project_name=MOCK_PROJECT_NAME,
        )

        assert f"{MOCK_PROJECT_NAME} \u00b7 feature/billing-rewrite" in output


# ---------------------------------------------------------------------------
# TS3.5 — Markdown is deterministic
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestMarkdownDeterministic:
    """TS3.5: same input produces identical output."""

    def test_deterministic(self, db):
        entries = [e for e in make_snippet_day() if e["project_id"] == MOCK_PROJECT_ID]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output1 = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )
        output2 = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )

        assert output1 == output2, "Markdown output should be byte-identical on repeat"
