# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""TS10.* — Weekly mode tests for snippets."""

import pytest

from momento.snippet import generate_snippet, resolve_range
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    make_snippet_week,
    make_entry,
    days_ago,
    hours_ago,
)
from tests.conftest import insert_entries


# ---------------------------------------------------------------------------
# TS10.1 — Weekly markdown has Key Moments
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestWeeklyKeyMoments:
    """TS10.1: weekly markdown contains Key Moments section."""

    def test_key_moments_section(self, db):
        entries = [e for e in make_snippet_week() if e["project_id"] == MOCK_PROJECT_ID]
        insert_entries(db, entries)

        start, end, _ = resolve_range(week=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )

        assert "### Key Moments" in output
        # Key moments should have bold day labels
        assert "**" in output


# ---------------------------------------------------------------------------
# TS10.2 — Weekly Progress section
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestWeeklyProgress:
    """TS10.2: weekly markdown contains Progress section with recent session states."""

    def test_progress_section(self, db):
        entries = [e for e in make_snippet_week() if e["project_id"] == MOCK_PROJECT_ID]
        insert_entries(db, entries)

        start, end, _ = resolve_range(week=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )

        assert "### Progress" in output


# ---------------------------------------------------------------------------
# TS10.3 — Gap day handling
# ---------------------------------------------------------------------------

@pytest.mark.nice_to_have
class TestGapDayHandling:
    """TS10.3: gap day (no entries) simply doesn't appear."""

    def test_gap_day_absent(self, db):
        # make_snippet_week has no entries on day 4
        entries = [e for e in make_snippet_week() if e["project_id"] == MOCK_PROJECT_ID]
        insert_entries(db, entries)

        start, end, _ = resolve_range(week=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )

        # The gap day should not appear as a label in Key Moments
        # We just verify the output is valid and doesn't have empty day annotations
        assert "### Key Moments" in output
        assert "(no entries)" not in output


# ---------------------------------------------------------------------------
# TS10.4 — Weekly standup
# ---------------------------------------------------------------------------

@pytest.mark.nice_to_have
class TestWeeklyStandup:
    """TS10.4: weekly standup uses 'This week' / 'Next week'."""

    def test_weekly_standup_labels(self, db):
        entries = [e for e in make_snippet_week() if e["project_id"] == MOCK_PROJECT_ID]
        insert_entries(db, entries)

        start, end, _ = resolve_range(week=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="standup", project_name=MOCK_PROJECT_NAME,
        )

        assert "*This week:*" in output
        assert "*Next week:*" in output


# ---------------------------------------------------------------------------
# TS10.5 — Decisions with dates in weekly
# ---------------------------------------------------------------------------

@pytest.mark.nice_to_have
class TestDecisionsWithDates:
    """TS10.5: weekly decisions include date annotations."""

    def test_decisions_have_dates(self, db):
        entries = [e for e in make_snippet_week() if e["project_id"] == MOCK_PROJECT_ID]
        insert_entries(db, entries)

        start, end, _ = resolve_range(week=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )

        # Weekly decisions should have count and date annotations
        assert "### Decisions Made (" in output
        assert "Feb" in output or "Jan" in output  # Date annotations present
