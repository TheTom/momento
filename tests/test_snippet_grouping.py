# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""TS2.* — Section mapping + split logic tests for snippets."""

import pytest

from momento.snippet import (
    group_entries,
    split_session_states,
    is_completed,
    extract_surface,
)
from momento.models import Entry
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    make_entry,
    hours_ago,
    make_snippet_session_split,
    make_snippet_durable_only,
)
from tests.conftest import insert_entries


def _entry_to_model(d: dict) -> Entry:
    """Convert mock_data dict to Entry model."""
    return Entry(
        id=d["id"], content=d["content"], content_hash=d["content_hash"],
        type=d["type"], tags=d["tags"], project_id=d["project_id"],
        project_name=d["project_name"], branch=d["branch"],
        source_type=d["source_type"], confidence=d["confidence"],
        created_at=d["created_at"], updated_at=d["updated_at"],
    )


# ---------------------------------------------------------------------------
# TS2.1 — Type-to-section mapping
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestTypeSectionMapping:
    """TS2.1: each entry type maps to the correct section."""

    def test_type_mapping(self):
        entries = [
            _entry_to_model(make_entry(
                content="session checkpoint", type="session_state",
                tags=["server"], branch="main", surface="server",
                created_at=hours_ago(1),
            )),
            _entry_to_model(make_entry(
                content="a decision", type="decision",
                tags=["server"], branch="main", created_at=hours_ago(2),
            )),
            _entry_to_model(make_entry(
                content="a gotcha", type="gotcha",
                tags=["server"], branch="main", created_at=hours_ago(3),
            )),
            _entry_to_model(make_entry(
                content="a pattern", type="pattern",
                tags=["api"], branch=None, created_at=hours_ago(4),
            )),
            _entry_to_model(make_entry(
                content="a plan", type="plan",
                tags=["billing"], branch="main", created_at=hours_ago(5),
            )),
        ]

        sections = group_entries(entries)
        assert len(sections.decisions) == 1
        assert sections.decisions[0].content == "a decision"
        assert len(sections.discovered) == 1
        assert sections.discovered[0].content == "a gotcha"
        assert len(sections.patterns) == 1
        assert sections.patterns[0].content == "a pattern"
        # plan goes to in_progress
        assert any(e.content == "a plan" for e in sections.in_progress)


# ---------------------------------------------------------------------------
# TS2.2 — Session state split: accomplished vs in-progress
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestSessionStateSplit:
    """TS2.2: most recent per surface+branch key is in-progress."""

    def test_recency_split(self):
        entries = [
            _entry_to_model(make_entry(
                content="entry A 9am", type="session_state",
                tags=["server", "billing"], branch="feature/billing",
                surface="server", created_at="2026-02-23T09:00:00Z",
            )),
            _entry_to_model(make_entry(
                content="entry B 11am", type="session_state",
                tags=["server", "billing"], branch="feature/billing",
                surface="server", created_at="2026-02-23T11:00:00Z",
            )),
            _entry_to_model(make_entry(
                content="entry C 2pm", type="session_state",
                tags=["server", "billing"], branch="feature/billing",
                surface="server", created_at="2026-02-23T14:00:00Z",
            )),
        ]

        accomplished, in_progress = split_session_states(entries)
        assert len(accomplished) == 2
        assert len(in_progress) == 1
        assert in_progress[0].content == "entry C 2pm"
        accomplished_contents = [e.content for e in accomplished]
        assert "entry A 9am" in accomplished_contents
        assert "entry B 11am" in accomplished_contents


# ---------------------------------------------------------------------------
# TS2.3 — Session state split: multiple surfaces
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestSessionStateSplitMultipleSurfaces:
    """TS2.3: independent split per surface+branch key."""

    def test_multiple_surface_split(self):
        entries = [e for e in [_entry_to_model(d) for d in make_snippet_session_split()]
                   if not is_completed(e.content)]
        # Filter out the "completed" keyword one for this specific test
        server_billing = [e for e in entries if "billing" in (e.tags if isinstance(e.tags, str) else "")]
        # Use the full set from factory minus the keyword override one
        raw = make_snippet_session_split()
        all_entries = [_entry_to_model(d) for d in raw[:4]]  # First 4: 2 server/billing + 2 ios/main

        accomplished, in_progress = split_session_states(all_entries)
        assert len(accomplished) == 2, f"Expected 2 accomplished, got {len(accomplished)}"
        assert len(in_progress) == 2, f"Expected 2 in-progress, got {len(in_progress)}"


# ---------------------------------------------------------------------------
# TS2.4 — Keyword completion override
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestKeywordCompletionOverride:
    """TS2.4: 'done' keyword overrides recency."""

    def test_done_keyword_forces_accomplished(self):
        entries = [
            _entry_to_model(make_entry(
                content="Old checkpoint. Still working.",
                type="session_state", tags=["server", "auth"],
                branch="main", surface="server",
                created_at=hours_ago(5),
            )),
            _entry_to_model(make_entry(
                content="Auth migration done. All handlers updated.",
                type="session_state", tags=["server", "auth"],
                branch="main", surface="server",
                created_at=hours_ago(1),  # Most recent
            )),
        ]

        accomplished, in_progress = split_session_states(entries)
        # The "done" entry is most recent but should be accomplished
        assert len(in_progress) == 0, "No in-progress: keyword override applies"
        assert len(accomplished) == 2, "Both should be accomplished"


# ---------------------------------------------------------------------------
# TS2.5 — Keyword word boundary
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestKeywordWordBoundary:
    """TS2.5: 'unfinished' does not match 'finished'."""

    def test_word_boundary(self):
        assert is_completed("This is unfinished work.") is False
        assert is_completed("This is finished work.") is True


# ---------------------------------------------------------------------------
# TS2.6 — All completion keywords
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestAllCompletionKeywords:
    """TS2.6: all 6 keywords are recognized."""

    def test_all_keywords(self):
        keywords = ["done", "completed", "finished", "shipped", "merged", "resolved"]
        for kw in keywords:
            assert is_completed(f"Task is {kw}.") is True, f"Keyword '{kw}' should match"


# ---------------------------------------------------------------------------
# TS2.7 — Empty sections omitted
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestEmptySectionsOmitted:
    """TS2.7: only populated sections have entries."""

    def test_decisions_only(self):
        entries = [_entry_to_model(d) for d in make_snippet_durable_only()
                   if d["type"] == "decision"]
        sections = group_entries(entries)
        assert len(sections.decisions) > 0
        assert len(sections.accomplished) == 0
        assert len(sections.discovered) == 0
        assert len(sections.in_progress) == 0
        assert len(sections.patterns) == 0


# ---------------------------------------------------------------------------
# TS2.8 — Plans always in-progress
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestPlansAlwaysInProgress:
    """TS2.8: plan entries always go to in_progress section."""

    def test_plans_in_progress(self):
        entries = [
            _entry_to_model(make_entry(
                content="Plan A: billing rewrite phases",
                type="plan", tags=["billing"],
                branch="main", created_at=hours_ago(3),
            )),
            _entry_to_model(make_entry(
                content="Plan B: auth migration phases",
                type="plan", tags=["auth"],
                branch="main", created_at=hours_ago(5),
            )),
        ]

        sections = group_entries(entries)
        assert len(sections.in_progress) == 2
        assert len(sections.accomplished) == 0
        plan_contents = [e.content for e in sections.in_progress]
        assert "Plan A: billing rewrite phases" in plan_contents
        assert "Plan B: auth migration phases" in plan_contents
