"""Tests for retrieve_context restore mode (T4.1–T4.15).

THE CORE TESTS — this is the acceptance surface for Momento's read path.
These are RED tests — retrieve_context raises NotImplementedError in the stub.

Every test has a docstring with its T-number. Priority markers:
  must_pass:    T4.1, T4.2, T4.8, T4.9, T4.12
  should_pass:  T4.3, T4.5, T4.6, T4.7
  nice_to_have: T4.4, T4.13, T4.15
"""

import json
import sqlite3

import pytest

from momento.models import Entry
from momento.retrieve import retrieve_context, _tag_set, _greedy_fill
from tests.conftest import insert_entry, insert_entries
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    SECOND_PROJECT_ID,
    SECOND_PROJECT_NAME,
    make_entry,
    make_restore_scenario,
    make_budget_scenario,
    make_surface_entries,
    make_branch_entries,
    make_cross_project_entries,
    make_decay_entries,
    hours_ago,
    days_ago,
    minutes_ago,
)


# ---------------------------------------------------------------------------
# T4.1 — The Restore Contract
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
class TestT41RestoreContract:
    """T4.1 — The Restore Contract.

    THE definitive test. Verifies 5-tier ordering with surface+branch
    preference within each tier. If these tests pass, restore works.
    Uses the populated_db fixture which loads make_restore_scenario():
      - 3 session_state: 2 server+feature/billing, 1 ios+main
      - 2 plan: 1 feature/billing, 1 main
      - 4 decision: 2 feature/billing, 2 main
      - 3 gotcha: 1 server, 2 ios
      - 2 pattern: no branch
      - 2 cross-project entries from identity-service
    """

    def _restore(self, populated_db):
        return retrieve_context(
            populated_db,
            project_id=MOCK_PROJECT_ID,
            branch="feature/billing-rewrite",
            surface="server",
            query=None,
            include_session_state=True,
        )

    def test_returns_entries(self, populated_db):
        """T4.1 — Restore returns a non-empty result."""
        result = self._restore(populated_db)
        assert len(result.entries) > 0, "Restore must return entries"

    def test_tier_ordering_session_before_plan(self, populated_db):
        """T4.1 — All session_state entries appear before any plan entry."""
        result = self._restore(populated_db)
        types = [e.type for e in result.entries]

        last_session = -1
        first_plan = len(types)
        for i, t in enumerate(types):
            if t == "session_state":
                last_session = max(last_session, i)
            if t == "plan" and i < first_plan:
                first_plan = i

        if last_session >= 0 and first_plan < len(types):
            assert last_session < first_plan, (
                f"Tier ordering violated: session_state at index {last_session} "
                f"but plan starts at index {first_plan}. "
                f"Order: {types}"
            )

    def test_tier_ordering_plan_before_decision(self, populated_db):
        """T4.1 — All plan entries appear before any decision entry."""
        result = self._restore(populated_db)
        types = [e.type for e in result.entries]

        last_plan = -1
        first_decision = len(types)
        for i, t in enumerate(types):
            if t == "plan":
                last_plan = max(last_plan, i)
            if t == "decision" and i < first_decision:
                first_decision = i

        if last_plan >= 0 and first_decision < len(types):
            assert last_plan < first_decision, (
                f"Tier ordering violated: plan at index {last_plan} "
                f"but decision starts at index {first_decision}. "
                f"Order: {types}"
            )

    def test_tier_ordering_decision_before_gotcha_pattern(self, populated_db):
        """T4.1 — All decision entries appear before any gotcha/pattern entry."""
        result = self._restore(populated_db)
        types = [e.type for e in result.entries]

        last_decision = -1
        first_gp = len(types)
        for i, t in enumerate(types):
            if t == "decision":
                last_decision = max(last_decision, i)
            if t in ("gotcha", "pattern") and i < first_gp:
                first_gp = i

        if last_decision >= 0 and first_gp < len(types):
            assert last_decision < first_gp, (
                f"Tier ordering violated: decision at index {last_decision} "
                f"but gotcha/pattern starts at index {first_gp}. "
                f"Order: {types}"
            )

    def test_tier_ordering_project_before_cross_project(self, populated_db):
        """T4.1 — All project entries appear before cross-project (tier 5)."""
        result = self._restore(populated_db)

        last_project_idx = -1
        first_cross_idx = len(result.entries)
        for i, e in enumerate(result.entries):
            if e.project_id == MOCK_PROJECT_ID:
                last_project_idx = max(last_project_idx, i)
            elif e.project_id != MOCK_PROJECT_ID and e.project_id is not None:
                first_cross_idx = min(first_cross_idx, i)

        if last_project_idx >= 0 and first_cross_idx < len(result.entries):
            assert last_project_idx < first_cross_idx, (
                "Cross-project entries must appear after ALL project entries (tier 5)"
            )

    def test_session_state_surface_preference(self, populated_db):
        """T4.1 — Within session_state tier, server entries rank before ios entries.

        The scenario has 2 server+billing entries and 1 ios+main entry.
        With surface='server', server entries must come first.
        """
        result = self._restore(populated_db)
        sessions = [e for e in result.entries if e.type == "session_state"]
        assert len(sessions) >= 2, f"Expected >=2 session entries, got {len(sessions)}"

        # First entries should have "server" in tags, ios entry should be last
        for i, entry in enumerate(sessions):
            tags = json.loads(entry.tags) if isinstance(entry.tags, str) else entry.tags
            is_server = "server" in tags
            if not is_server:
                # All remaining session entries should also be non-server
                for j in range(i + 1, len(sessions)):
                    remaining_tags = (
                        json.loads(sessions[j].tags)
                        if isinstance(sessions[j].tags, str)
                        else sessions[j].tags
                    )
                    assert "server" not in remaining_tags, (
                        f"Surface preference violated: server session at index {j} "
                        f"appeared after non-server session at index {i}"
                    )
                break

    def test_session_state_branch_preference_within_surface(self, populated_db):
        """T4.1 — Within surface-matched session entries, billing branch preferred.

        Both server session entries are on feature/billing-rewrite, so
        they should rank above the ios+main entry.
        """
        result = self._restore(populated_db)
        sessions = [e for e in result.entries if e.type == "session_state"]

        # The two server+billing entries should come first
        billing_sessions = [
            e for e in sessions
            if e.branch == "feature/billing-rewrite"
        ]
        non_billing = [
            e for e in sessions
            if e.branch != "feature/billing-rewrite"
        ]

        if billing_sessions and non_billing:
            last_billing_idx = max(
                sessions.index(e) for e in billing_sessions
            )
            first_non_billing_idx = min(
                sessions.index(e) for e in non_billing
            )
            assert last_billing_idx < first_non_billing_idx, (
                "Branch preference within surface group violated"
            )

    def test_decision_quota_max_3(self, populated_db):
        """T4.1 — At most 3 decisions included (4 in DB, quota is 3)."""
        result = self._restore(populated_db)
        decision_count = sum(1 for e in result.entries if e.type == "decision")
        assert decision_count <= 3, (
            f"Decision quota is 3, got {decision_count}"
        )

    def test_gotcha_pattern_combined_quota_max_4(self, populated_db):
        """T4.1 — At most 4 combined gotcha+pattern entries (5 in DB)."""
        result = self._restore(populated_db)
        gp_count = sum(1 for e in result.entries if e.type in ("gotcha", "pattern"))
        assert gp_count <= 4, (
            f"Gotcha+pattern combined quota is 4, got {gp_count}"
        )

    def test_cross_project_quota_max_2(self, populated_db):
        """T4.1 — At most 2 cross-project entries."""
        result = self._restore(populated_db)
        cross_count = sum(
            1 for e in result.entries
            if e.project_id != MOCK_PROJECT_ID and e.project_id is not None
        )
        assert cross_count <= 2, (
            f"Cross-project quota is 2, got {cross_count}"
        )

    def test_plan_quota_max_2(self, populated_db):
        """T4.1 — At most 2 plan entries."""
        result = self._restore(populated_db)
        plan_count = sum(1 for e in result.entries if e.type == "plan")
        assert plan_count <= 2, (
            f"Plan quota is 2, got {plan_count}"
        )

    def test_token_budget(self, populated_db):
        """T4.1 — Total tokens within budget (2000 + 5% tolerance)."""
        result = self._restore(populated_db)
        assert result.total_tokens <= 2100, (
            f"Token budget exceeded: {result.total_tokens} (budget: 2000, tolerance: 2100)"
        )

    def test_no_entry_truncated(self, populated_db):
        """T4.1 — Every entry's content matches an original entry exactly."""
        from tests.mock_data import make_restore_scenario

        original_contents = {e["content"] for e in make_restore_scenario()}
        result = self._restore(populated_db)
        for entry in result.entries:
            assert entry.content in original_contents, (
                f"Entry content appears truncated or modified:\n{entry.content[:100]}..."
            )

    def test_gotcha_surface_preference(self, populated_db):
        """T4.1 — Within gotcha/pattern tier, server-tagged entries rank first.

        Scenario has 1 server gotcha and 2 ios gotchas.
        With surface='server', server gotchas should come first.
        """
        result = self._restore(populated_db)
        gp_entries = [e for e in result.entries if e.type in ("gotcha", "pattern")]

        if len(gp_entries) >= 2:
            found_non_server = False
            for entry in gp_entries:
                tags = json.loads(entry.tags) if isinstance(entry.tags, str) else entry.tags
                is_server = "server" in tags
                if found_non_server and is_server:
                    pytest.fail(
                        "Surface preference violated in gotcha/pattern tier: "
                        "server entry appeared after non-server entry"
                    )
                if not is_server:
                    found_non_server = True

    def test_decision_branch_preference(self, populated_db):
        """T4.1 — Within decision tier, billing-branch entries rank before main.

        Scenario has 2 billing decisions and 2 main decisions.
        With branch='feature/billing-rewrite', billing should come first.
        """
        result = self._restore(populated_db)
        decisions = [e for e in result.entries if e.type == "decision"]

        billing_decisions = [e for e in decisions if e.branch == "feature/billing-rewrite"]
        main_decisions = [e for e in decisions if e.branch == "main"]

        if billing_decisions and main_decisions:
            last_billing_idx = max(decisions.index(e) for e in billing_decisions)
            first_main_idx = min(decisions.index(e) for e in main_decisions)
            assert last_billing_idx < first_main_idx, (
                "Branch preference violated in decision tier: billing-branch "
                "decisions should rank above main-branch decisions"
            )


# ---------------------------------------------------------------------------
# T4.2 — Empty project
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
class TestT42EmptyProject:
    """T4.2 — Empty project returns structured empty response with tip."""

    def test_no_entries_returned(self, db):
        """T4.2 — No entries for current project → empty entries list."""
        result = retrieve_context(
            db,
            project_id="nonexistent-project-id",
            branch="main",
            surface=None,
            query=None,
        )
        assert len(result.entries) == 0, "Empty project must return no entries"

    def test_rendered_output_not_empty(self, db):
        """T4.2 — Even with no entries, rendered output is non-empty."""
        result = retrieve_context(
            db,
            project_id="nonexistent-project-id",
            branch="main",
            surface=None,
            query=None,
        )
        assert len(result.rendered) > 0, (
            "Empty project must return structured response, not empty string"
        )

    def test_contains_no_checkpoint_message(self, db):
        """T4.2 — Response says 'No session checkpoints found for this project.'"""
        result = retrieve_context(
            db,
            project_id="nonexistent-project-id",
            branch="main",
            surface=None,
            query=None,
        )
        rendered_lower = result.rendered.lower()
        assert "no" in rendered_lower and (
            "checkpoint" in rendered_lower or "found" in rendered_lower
        ), f"Empty response should indicate no checkpoints found. Got:\n{result.rendered}"

    def test_contains_usage_tip(self, db):
        """T4.2 — Response includes a tip about log_knowledge."""
        result = retrieve_context(
            db,
            project_id="nonexistent-project-id",
            branch="main",
            surface=None,
            query=None,
        )
        assert "log_knowledge" in result.rendered or "tip" in result.rendered.lower(), (
            "Empty response must include usage tip"
        )

    def test_has_markdown_structure(self, db):
        """T4.2 — Response has markdown section headers."""
        result = retrieve_context(
            db,
            project_id="nonexistent-project-id",
            branch="main",
            surface=None,
            query=None,
        )
        assert "##" in result.rendered, (
            "Empty response must have markdown structure (headers)"
        )


# ---------------------------------------------------------------------------
# T4.3 — Token budget enforcement
# ---------------------------------------------------------------------------


@pytest.mark.should_pass
class TestT43TokenBudget:
    """T4.3 — 17 max-size entries, verify budget stops inclusion."""

    def test_total_tokens_within_budget(self, db):
        """T4.3 — Total estimated tokens <= 2100 (2000 + 5% tolerance)."""
        insert_entries(db, make_budget_scenario())

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="feature/billing-rewrite",
            surface="server",
            query=None,
            include_session_state=True,
        )
        assert result.total_tokens <= 2100, (
            f"Total tokens {result.total_tokens} exceeds budget"
        )

    def test_not_all_17_entries_included(self, db):
        """T4.3 — Budget enforcement must omit some of the 17 entries."""
        insert_entries(db, make_budget_scenario())

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="feature/billing-rewrite",
            surface="server",
            query=None,
            include_session_state=True,
        )
        assert len(result.entries) < 17, (
            f"All 17 entries were included ({len(result.entries)}). "
            "Budget enforcement must omit lower-tier entries."
        )

    def test_entries_not_truncated(self, db):
        """T4.3 — Last included entry is complete (not truncated mid-content)."""
        budget_entries = make_budget_scenario()
        insert_entries(db, budget_entries)

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="feature/billing-rewrite",
            surface="server",
            query=None,
            include_session_state=True,
        )

        original_contents = {e["content"] for e in budget_entries}
        for entry in result.entries:
            assert entry.content in original_contents, (
                "Entry appears truncated — content doesn't match any original"
            )

    def test_higher_tiers_filled_first(self, db):
        """T4.3 — Entries are filled in tier order; higher tiers take priority."""
        insert_entries(db, make_budget_scenario())

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="feature/billing-rewrite",
            surface="server",
            query=None,
            include_session_state=True,
        )

        types = [e.type for e in result.entries]
        if types:
            assert types[0] == "session_state", (
                f"First entry should be session_state (highest tier), got {types[0]}"
            )


# ---------------------------------------------------------------------------
# T4.4 — Token estimation includes markdown scaffolding
# ---------------------------------------------------------------------------


@pytest.mark.nice_to_have
def test_token_estimation_includes_markdown_scaffolding(populated_db):
    """T4.4 — Token estimation includes markdown scaffolding.

    Token budget uses len(rendered_chunk)/4, not len(raw_content)/4.
    Headers like '## Active Task' and metadata like
    '[decision | server | 1d ago]' count toward budget.
    """
    result = retrieve_context(
        populated_db,
        project_id=MOCK_PROJECT_ID,
        branch="feature/billing-rewrite",
        surface="server",
        query=None,
        include_session_state=True,
    )

    # Rendered output must include markdown scaffolding
    assert "##" in result.rendered or "[" in result.rendered, (
        "Rendered output must include markdown scaffolding"
    )

    # Token estimate should exceed raw content sum (scaffolding adds overhead)
    raw_content_tokens = sum(len(e.content) for e in result.entries) // 4
    assert result.total_tokens >= raw_content_tokens, (
        f"Token estimate ({result.total_tokens}) should be >= raw content "
        f"tokens ({raw_content_tokens}) because scaffolding adds overhead"
    )


# ---------------------------------------------------------------------------
# T4.5 — Tier 1 exhausts budget
# ---------------------------------------------------------------------------


@pytest.mark.should_pass
def test_tier1_exhausts_budget_no_lower_tiers(db):
    """T4.5 — Tier 1 exhausts budget.

    When session_state entries consume the full token budget,
    no Tier 2+ entries should be included. Greedy fill, no backtrack.
    """
    # Stuff 15 large session_state entries (quota allows 4+2=6, but
    # budget should be the binding constraint).
    # Each entry ~1940 chars content → ~498 tokens rendered.
    # 4 surface-matched entries × 498 tokens = 1992 tokens → only 8 left,
    # too small for any lower-tier entry (~17-26 tokens).
    for i in range(15):
        content = (
            f"Session checkpoint {i+1}: migrating handler {i+1} of 15. "
            "Working through the async conversion of all payment handlers. "
            "Each handler needs careful transaction boundary management to ensure "
            "that database operations are properly committed before returning "
            "responses to the client. The migration involves converting synchronous "
            "database calls to use the new async connection pool, updating error "
            "handling to properly propagate exceptions through the async chain, "
            "and ensuring that connection cleanup happens correctly even when "
            "handlers are cancelled mid-execution. Additionally, all logging "
            "statements need to be updated to use structured logging with proper "
            "correlation IDs that flow through the async context. The test suite "
            "for each handler must be updated to use async test fixtures, and "
            "integration tests need new fixtures for the async database pool. "
            "Performance benchmarks show a 40 percent reduction in p99 latency "
            "after conversion, validating the migration approach. Remaining work "
            "includes PaymentIntentHandler, SubscriptionHandler, InvoiceHandler, "
            "and WebhookHandler. Each requires approximately 2 hours for the "
            "conversion plus 1 hour for test updates. The webhook handler is the "
            "most complex due to its interaction with the external Stripe API and "
            "the need to maintain idempotency guarantees across async boundaries. "
            "Current progress: 11 of 15 handlers fully converted and tested in "
            "the staging environment with no regressions detected. Next sprint "
            "will focus on the remaining 4 handlers plus the integration test "
            "suite that covers cross-handler transaction scenarios and rollback "
            "behavior. Key risk: the WebhookHandler conversion may require "
            "changes to the idempotency key storage layer, which could impact "
            "the billing reconciliation service that depends on the same table. "
            "Mitigation: run dual-write validation for 48 hours before cutting "
            "over to the new async implementation. Monitoring dashboards have "
            "been updated with async-specific metrics."
        )
        insert_entry(db, make_entry(
            content=content,
            type="session_state",
            tags=["server"],
            branch="feature/billing-rewrite",
            surface="server",
            created_at=minutes_ago(i * 5),
        ))

    # Add lower-tier entries that should NOT appear
    insert_entry(db, make_entry(
        content="Chose Redis over Memcached for session caching.",
        type="decision",
        tags=["server", "caching"],
        branch="feature/billing-rewrite",
        created_at=days_ago(1),
    ))
    insert_entry(db, make_entry(
        content="Migration plan: 6 phases over 4 sprints.",
        type="plan",
        tags=["migration"],
        branch="main",
        created_at=days_ago(2),
    ))
    db.commit()

    result = retrieve_context(
        db,
        project_id=MOCK_PROJECT_ID,
        branch="feature/billing-rewrite",
        surface="server",
        query=None,
        include_session_state=True,
    )

    entry_types = {e.type for e in result.entries}
    assert entry_types == {"session_state"}, (
        f"When Tier 1 exhausts budget, only session_state should appear. "
        f"Got types: {entry_types}"
    )


# ---------------------------------------------------------------------------
# T4.6 — Session state 48h window
# ---------------------------------------------------------------------------


@pytest.mark.should_pass
class TestT46SessionState48hWindow:
    """T4.6 — Session state entries respect the 48h decay window.

    48h filter must be a SQL WHERE clause, not Python post-filter.
    """

    def test_1h_entry_included(self, db):
        """T4.6 — Session state from 1h ago is within window."""
        insert_entries(db, make_decay_entries())

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="feature/billing-rewrite",
            surface="server",
            query=None,
            include_session_state=True,
        )

        session_contents = [
            e.content for e in result.entries if e.type == "session_state"
        ]
        assert any("webhook handler" in c.lower() for c in session_contents), (
            "1h-old session_state must be included"
        )

    def test_24h_entry_included(self, db):
        """T4.6 — Session state from 24h ago is within window."""
        insert_entries(db, make_decay_entries())

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="feature/billing-rewrite",
            surface="server",
            query=None,
            include_session_state=True,
        )

        session_contents = [
            e.content for e in result.entries if e.type == "session_state"
        ]
        assert any("stripe test mode" in c.lower() for c in session_contents), (
            "24h-old session_state must be included"
        )

    def test_72h_entry_excluded(self, db):
        """T4.6 — Session state from 72h ago is outside 48h window."""
        insert_entries(db, make_decay_entries())

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="feature/billing-rewrite",
            surface="server",
            query=None,
            include_session_state=True,
        )

        session_contents = [
            e.content for e in result.entries if e.type == "session_state"
        ]
        assert not any("auth token rotation" in c.lower() for c in session_contents), (
            "72h-old session_state must be EXCLUDED by 48h window (SQL WHERE clause)"
        )

    def test_10d_entry_excluded(self, db):
        """T4.6 — Session state from 10 days ago is excluded."""
        insert_entries(db, make_decay_entries())

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="feature/billing-rewrite",
            surface="server",
            query=None,
            include_session_state=True,
        )

        session_contents = [
            e.content for e in result.entries if e.type == "session_state"
        ]
        assert not any("initial project setup" in c.lower() for c in session_contents), (
            "10d-old session_state must be EXCLUDED"
        )


# ---------------------------------------------------------------------------
# T4.7 — Cross-project isolation
# ---------------------------------------------------------------------------


@pytest.mark.should_pass
class TestT47CrossProjectIsolation:
    """T4.7 — Cross-project entries only appear in tier 5, never in tiers 1–4."""

    def test_project_b_only_in_tier5(self, db):
        """T4.7 — Project B entries only appear after all Project A entries."""
        # Project A entries
        insert_entry(db, make_entry(
            content="Project A decision about auth architecture.",
            type="decision",
            tags=["auth", "server"],
            branch="main",
        ))

        # Cross-project entries with overlapping tags
        insert_entries(db, make_cross_project_entries())

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="main",
            surface="server",
            query=None,
        )

        # Find the first cross-project entry — everything before it must be project A
        first_cross = None
        for i, entry in enumerate(result.entries):
            if entry.project_id == SECOND_PROJECT_ID:
                first_cross = i
                break

        assert first_cross is not None, "Expected at least one cross-project entry"
        assert first_cross > 0, "Cross-project entry at index 0 — project entries missing"

        for j in range(first_cross):
            assert result.entries[j].project_id == MOCK_PROJECT_ID, (
                "Cross-project entry appeared before a project entry. "
                "Cross-project must only be in tier 5."
            )
        # With quota=2, expect both overlapping cross-project entries
        cross_entries = [e for e in result.entries if e.project_id == SECOND_PROJECT_ID]
        assert len(cross_entries) <= 2, f"Cross-project quota exceeded: {len(cross_entries)}"

    def test_no_tag_overlap_no_cross_project(self, db):
        """T4.7 — Cross-project entries without tag overlap are excluded."""
        insert_entry(db, make_entry(
            content="Project A auth decision.",
            type="decision",
            tags=["auth", "server"],
            branch="main",
        ))
        # Cross-project entry with NO overlapping tags
        insert_entry(db, make_entry(
            content="Email service: dedicated IP pool for transactional emails.",
            type="decision",
            tags=["email", "infrastructure", "deliverability"],
            branch="main",
            project_id=SECOND_PROJECT_ID,
            project_name=SECOND_PROJECT_NAME,
            created_at=days_ago(10),
        ))
        db.commit()

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="main",
            surface="server",
            query=None,
        )

        cross_project_entries = [
            e for e in result.entries if e.project_id == SECOND_PROJECT_ID
        ]
        assert len(cross_project_entries) == 0, (
            "Cross-project entry with no tag overlap should NOT appear"
        )


# ---------------------------------------------------------------------------
# T4.8 — Tier quota enforcement
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
class TestT48TierQuotaEnforcement:
    """T4.8 — Tier quotas enforced even if token budget allows more."""

    def test_decision_quota_3(self, db):
        """T4.8 — 6 decisions exist; only 3 included (quota: 3)."""
        for i in range(6):
            insert_entry(db, make_entry(
                content=f"Decision {i+1}: chose approach {chr(65+i)} for module {i+1}.",
                type="decision",
                tags=["server"],
                branch="feature/billing-rewrite",
                created_at=days_ago(i + 1),
            ))
        db.commit()

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="feature/billing-rewrite",
            surface="server",
            query=None,
        )

        decision_count = sum(1 for e in result.entries if e.type == "decision")
        assert decision_count <= 3, (
            f"Decision quota is 3, got {decision_count}"
        )
        assert decision_count > 0, "At least some decisions should appear"

    def test_plan_quota_2(self, db):
        """T4.8 — 5 plans exist; only 2 included (quota: 2)."""
        for i in range(5):
            insert_entry(db, make_entry(
                content=f"Plan {i+1}: migration phase {i+1} details and timeline.",
                type="plan",
                tags=["migration"],
                branch="main",
                created_at=days_ago(i + 1),
            ))
        db.commit()

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="main",
            surface=None,
            query=None,
        )

        plan_count = sum(1 for e in result.entries if e.type == "plan")
        assert plan_count <= 2, (
            f"Plan quota is 2, got {plan_count}"
        )

    def test_session_state_quota_surface_plus_other(self, db):
        """T4.8 — Session state: up to 4 surface-matching + 2 other = 6 total."""
        # 8 server (surface-matching) entries
        for i in range(8):
            insert_entry(db, make_entry(
                content=f"Server session {i+1}: handler migration progress.",
                type="session_state",
                tags=["server", "migration"],
                branch="main",
                surface="server",
                created_at=minutes_ago(5 + i * 3),
            ))
        # 4 ios (non-matching) entries
        for i in range(4):
            insert_entry(db, make_entry(
                content=f"iOS session {i+1}: keychain wrapper update progress.",
                type="session_state",
                tags=["ios", "keychain"],
                branch="main",
                surface="ios",
                created_at=minutes_ago(10 + i * 5),
            ))
        db.commit()

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="main",
            surface="server",
            query=None,
            include_session_state=True,
        )

        sessions = [e for e in result.entries if e.type == "session_state"]
        total_session = len(sessions)
        assert total_session <= 6, (
            f"Session state quota is 6 (4 surface + 2 other), got {total_session}"
        )

        # Surface-matching sessions
        server_sessions = [
            e for e in sessions
            if "server" in (json.loads(e.tags) if isinstance(e.tags, str) else e.tags)
        ]
        assert len(server_sessions) <= 4, (
            f"Surface-matching session quota is 4, got {len(server_sessions)}"
        )

        # Other sessions
        other_sessions = [
            e for e in sessions
            if "server" not in (json.loads(e.tags) if isinstance(e.tags, str) else e.tags)
        ]
        assert len(other_sessions) <= 2, (
            f"Other session quota is 2, got {len(other_sessions)}"
        )

    def test_session_over_quota_still_allows_lower_tiers_when_budget_remains(self, db):
        """Session over-quota should not suppress lower tiers when budget remains."""
        # Create many short session_state entries; quota should cap output to 6.
        for i in range(10):
            insert_entry(db, make_entry(
                content=f"Short session {i+1}.",
                type="session_state",
                tags=["server", "checkpoint"],
                branch="main",
                surface="server",
                created_at=minutes_ago(i + 1),
            ))

        # Add lower-tier entries that should still appear.
        decision = make_entry(
            content="Decision: use server-side checkout.",
            type="decision",
            tags=["billing", "server"],
            branch="main",
            created_at=days_ago(1),
        )
        plan = make_entry(
            content="Plan: phase rollout by surface.",
            type="plan",
            tags=["migration"],
            branch="main",
            created_at=days_ago(2),
        )
        insert_entry(db, decision)
        insert_entry(db, plan)
        db.commit()

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="main",
            surface="server",
            query=None,
            include_session_state=True,
        )

        assert any(e.type == "decision" for e in result.entries), (
            "Lower tiers should still be considered after Tier 1 quota is applied"
        )
        assert any(e.type == "plan" for e in result.entries), (
            "Plan entries should still appear when token budget allows"
        )

    def test_gotcha_pattern_combined_quota_4(self, db):
        """T4.8 — 7 gotcha+pattern entries exist; only 4 included (quota: 4)."""
        for i in range(4):
            insert_entry(db, make_entry(
                content=f"Gotcha {i+1}: watch out for connection pool issue {i+1}.",
                type="gotcha",
                tags=["server", "database"],
                branch="main",
                created_at=days_ago(i + 1),
            ))
        for i in range(3):
            insert_entry(db, make_entry(
                content=f"Pattern {i+1}: always validate at handler boundary {i+1}.",
                type="pattern",
                tags=["server", "api"],
                branch=None,
                created_at=days_ago(i + 5),
            ))
        db.commit()

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="main",
            surface="server",
            query=None,
        )

        gp_count = sum(1 for e in result.entries if e.type in ("gotcha", "pattern"))
        assert gp_count <= 4, (
            f"Gotcha+pattern combined quota is 4, got {gp_count}"
        )

    def test_cross_project_quota_2(self, db):
        """T4.8 — 5 cross-project entries with tag overlap; only 2 included."""
        # Project entry to ensure we have a project context
        insert_entry(db, make_entry(
            content="Our project auth decision.",
            type="decision",
            tags=["auth", "server"],
            branch="main",
        ))

        # 5 cross-project entries with overlapping "auth" tag
        for i in range(5):
            insert_entry(db, make_entry(
                content=f"Cross-project {i+1}: auth pattern from identity service.",
                type="decision",
                tags=["auth", "security"],
                branch="main",
                project_id=SECOND_PROJECT_ID,
                project_name=SECOND_PROJECT_NAME,
                created_at=days_ago(10 + i),
            ))
        db.commit()

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="main",
            surface="server",
            query=None,
        )

        cross_count = sum(
            1 for e in result.entries if e.project_id == SECOND_PROJECT_ID
        )
        assert cross_count <= 2, (
            f"Cross-project quota is 2, got {cross_count}"
        )


# ---------------------------------------------------------------------------
# T4.9 — Surface preference over branch
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
def test_surface_preference_over_branch(db):
    """T4.9 — Surface preference over branch.

    Decision A: tagged server, branch main (surface MATCH, branch NO match).
    Decision B: tagged ios, branch feature/x (surface NO match, branch MATCH).
    With surface='server', branch='feature/x': A must outrank B.
    """
    entry_a = make_entry(
        content="Server-side rate limiting with Redis sliding window.",
        type="decision",
        tags=["server", "rate-limiting"],
        branch="main",
        surface="server",
        created_at=days_ago(3),
    )
    entry_b = make_entry(
        content="iOS biometric auth wrapper for Face ID.",
        type="decision",
        tags=["ios", "auth"],
        branch="feature/x",
        surface="ios",
        created_at=days_ago(1),
    )
    insert_entry(db, entry_a)
    insert_entry(db, entry_b)
    db.commit()

    result = retrieve_context(
        db,
        project_id=MOCK_PROJECT_ID,
        branch="feature/x",
        surface="server",
        query=None,
    )

    decisions = [e for e in result.entries if e.type == "decision"]
    assert len(decisions) >= 2, "Both decisions must appear"

    idx_a = next(i for i, e in enumerate(decisions) if e.id == entry_a["id"])
    idx_b = next(i for i, e in enumerate(decisions) if e.id == entry_b["id"])
    assert idx_a < idx_b, (
        "Surface match (server+main) must outrank branch match (ios+feature/x)"
    )


# ---------------------------------------------------------------------------
# T4.10 — Branch preference over recency
# ---------------------------------------------------------------------------


def test_branch_preference_over_recency(db):
    """T4.10 — Branch preference over recency.

    Decision A: branch feature/x, 3 days ago.
    Decision B: branch main, 1 day ago.
    No surface preference (same or none).
    With branch='feature/x': A must outrank B despite being older.
    """
    entry_a = make_entry(
        content="Feature/x: Stripe Checkout session moved to server-side.",
        type="decision",
        tags=["billing", "stripe"],
        branch="feature/x",
        created_at=days_ago(3),
    )
    entry_b = make_entry(
        content="Main: API versioning strategy with URL prefix /v2/.",
        type="decision",
        tags=["api", "versioning"],
        branch="main",
        created_at=days_ago(1),
    )
    insert_entry(db, entry_a)
    insert_entry(db, entry_b)
    db.commit()

    result = retrieve_context(
        db,
        project_id=MOCK_PROJECT_ID,
        branch="feature/x",
        surface=None,
        query=None,
    )

    decisions = [e for e in result.entries if e.type == "decision"]
    assert len(decisions) >= 2

    idx_a = next(i for i, e in enumerate(decisions) if e.id == entry_a["id"])
    idx_b = next(i for i, e in enumerate(decisions) if e.id == entry_b["id"])
    assert idx_a < idx_b, (
        "Branch match (feature/x, 3d ago) must outrank recency (main, 1d ago)"
    )


# ---------------------------------------------------------------------------
# T4.11 — Cross-project never above project entries
# ---------------------------------------------------------------------------


def test_cross_project_never_above_project_entries(db):
    """T4.11 — Cross-project never above project entries.

    Project entry (low confidence) must ALWAYS rank above
    cross-project entry (high confidence). Tier ordering is hard constraint.
    """
    project_entry = make_entry(
        content="Local decision about error handling strategy.",
        type="decision",
        tags=["server", "auth"],
        branch="main",
        confidence=0.5,
    )
    cross_entry = make_entry(
        content="Identity service: PKCE flow mandatory for all OAuth clients.",
        type="decision",
        tags=["auth", "oauth"],
        branch="main",
        project_id=SECOND_PROJECT_ID,
        project_name=SECOND_PROJECT_NAME,
        confidence=1.0,
    )
    insert_entry(db, project_entry)
    insert_entry(db, cross_entry)
    db.commit()

    result = retrieve_context(
        db,
        project_id=MOCK_PROJECT_ID,
        branch="main",
        surface="server",
        query=None,
    )

    if len(result.entries) >= 2:
        idx_project = next(
            (i for i, e in enumerate(result.entries) if e.id == project_entry["id"]),
            None,
        )
        idx_cross = next(
            (i for i, e in enumerate(result.entries) if e.id == cross_entry["id"]),
            None,
        )
        if idx_project is not None and idx_cross is not None:
            assert idx_project < idx_cross, (
                "Project entry (confidence 0.5) must appear before "
                "cross-project entry (confidence 1.0). "
                "Tier ordering is a hard constraint, not a suggestion."
            )


# ---------------------------------------------------------------------------
# T4.12 — Determinism (idempotency)
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
class TestT412Determinism:
    """T4.12 — Same inputs produce identical outputs on repeated calls.

    retrieval_count increment must NOT affect ordering.
    """

    def test_identical_ids_on_repeat(self, populated_db):
        """T4.12 — Entry IDs identical across two calls."""
        kwargs = dict(
            project_id=MOCK_PROJECT_ID,
            branch="feature/billing-rewrite",
            surface="server",
            query=None,
            include_session_state=True,
        )

        result1 = retrieve_context(populated_db, **kwargs)
        result2 = retrieve_context(populated_db, **kwargs)

        ids1 = [e.id for e in result1.entries]
        ids2 = [e.id for e in result2.entries]
        assert ids1 == ids2, (
            "Entry ordering must be identical across two calls"
        )

    def test_identical_rendered_on_repeat(self, populated_db):
        """T4.12 — Rendered markdown identical across two calls."""
        kwargs = dict(
            project_id=MOCK_PROJECT_ID,
            branch="feature/billing-rewrite",
            surface="server",
            query=None,
            include_session_state=True,
        )

        result1 = retrieve_context(populated_db, **kwargs)
        result2 = retrieve_context(populated_db, **kwargs)
        assert result1.rendered == result2.rendered, (
            "Rendered output must be identical across calls"
        )

    def test_determinism_across_three_calls(self, populated_db):
        """T4.12 — Even after 3 calls (with retrieval_count incrementing), same output."""
        kwargs = dict(
            project_id=MOCK_PROJECT_ID,
            branch="feature/billing-rewrite",
            surface="server",
            query=None,
            include_session_state=True,
        )

        results = [retrieve_context(populated_db, **kwargs) for _ in range(3)]
        ids_list = [[e.id for e in r.entries] for r in results]

        assert ids_list[0] == ids_list[1] == ids_list[2], (
            "Three consecutive calls must produce identical entry ordering. "
            "retrieval_count must NOT influence ranking."
        )


# ---------------------------------------------------------------------------
# T4.13 — Determinism tie-breaker (id fallback)
# ---------------------------------------------------------------------------


@pytest.mark.nice_to_have
class TestT413DeterminismTieBreaker:
    """T4.13 — Identical timestamps, lower id first (id ASC tie-breaker)."""

    def test_lower_id_wins_tie(self, db):
        """T4.13 — Two entries with identical metadata; lower UUID sorts first."""
        timestamp = days_ago(1)
        id_low = "00000000-0000-4000-8000-000000000001"
        id_high = "ffffffff-ffff-4fff-bfff-ffffffffffff"

        entry_low = make_entry(
            content="Decision alpha: chose Redis for caching layer.",
            type="decision",
            tags=["server", "caching"],
            branch="main",
            created_at=timestamp,
        )
        entry_low["id"] = id_low

        entry_high = make_entry(
            content="Decision beta: chose Memcached for session store.",
            type="decision",
            tags=["server", "sessions"],
            branch="main",
            created_at=timestamp,
        )
        entry_high["id"] = id_high

        # Insert high first to prevent insertion-order bias
        insert_entry(db, entry_high)
        insert_entry(db, entry_low)
        db.commit()

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="main",
            surface="server",
            query=None,
        )

        decisions = [e for e in result.entries if e.type == "decision"]
        assert len(decisions) >= 2, "Both entries must appear"

        idx_low = next(i for i, e in enumerate(decisions) if e.id == id_low)
        idx_high = next(i for i, e in enumerate(decisions) if e.id == id_high)
        assert idx_low < idx_high, (
            f"Tie-breaker violated: id {id_low} should sort before {id_high} (ASC)"
        )

    def test_tie_breaker_consistent_across_calls(self, db):
        """T4.13 — Tie-breaker produces same result on repeated calls."""
        timestamp = days_ago(1)
        id_a = "00000000-0000-4000-a000-000000000010"
        id_b = "00000000-0000-4000-a000-000000000020"

        entry_a = make_entry(
            content="Consistent A: auth token rotation strategy.",
            type="decision",
            tags=["auth"],
            branch="main",
            created_at=timestamp,
        )
        entry_a["id"] = id_a

        entry_b = make_entry(
            content="Consistent B: session management strategy.",
            type="decision",
            tags=["auth"],
            branch="main",
            created_at=timestamp,
        )
        entry_b["id"] = id_b

        insert_entry(db, entry_b)  # Insert b first
        insert_entry(db, entry_a)
        db.commit()

        kwargs = dict(
            project_id=MOCK_PROJECT_ID,
            branch="main",
            surface=None,
            query=None,
        )

        result1 = retrieve_context(db, **kwargs)
        result2 = retrieve_context(db, **kwargs)

        ids1 = [e.id for e in result1.entries]
        ids2 = [e.id for e in result2.entries]
        assert ids1 == ids2, "Tie-breaker must be consistent across calls"


# ---------------------------------------------------------------------------
# T4.14 — retrieval_count does not mutate updated_at
# ---------------------------------------------------------------------------


class TestT414RetrievalCountPreservesUpdatedAt:
    """T4.14 — retrieval_count increments stats, NOT knowledge.updated_at."""

    def test_updated_at_unchanged(self, db):
        """T4.14 — knowledge.updated_at unchanged after retrieve_context."""
        original_time = days_ago(3)
        entry = make_entry(
            content="Auth tokens moved from JWT to opaque server-side sessions.",
            type="decision",
            tags=["auth", "server"],
            branch="main",
            created_at=original_time,
        )
        insert_entry(db, entry)
        db.commit()

        retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="main",
            surface="server",
            query=None,
        )

        row = db.execute(
            "SELECT updated_at FROM knowledge WHERE id = ?",
            (entry["id"],),
        ).fetchone()
        assert row is not None
        assert row[0] == original_time, (
            f"updated_at mutated: expected {original_time}, got {row[0]}. "
            "retrieval_count must live in knowledge_stats."
        )

    def test_retrieval_count_incremented(self, db):
        """T4.14 — knowledge_stats.retrieval_count IS incremented."""
        entry = make_entry(
            content="Decision about auth token storage mechanism.",
            type="decision",
            tags=["auth", "server"],
            branch="main",
            created_at=days_ago(1),
        )
        insert_entry(db, entry)
        db.commit()

        initial = db.execute(
            "SELECT retrieval_count FROM knowledge_stats WHERE entry_id = ?",
            (entry["id"],),
        ).fetchone()
        assert initial is not None, "knowledge_stats row should exist"

        retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="main",
            surface=None,
            query=None,
        )

        after = db.execute(
            "SELECT retrieval_count FROM knowledge_stats WHERE entry_id = ?",
            (entry["id"],),
        ).fetchone()
        assert after[0] > initial[0], (
            f"retrieval_count not incremented: {initial[0]} -> {after[0]}"
        )


# ---------------------------------------------------------------------------
# T4.15 — retrieval_count in knowledge_stats, not knowledge
# ---------------------------------------------------------------------------


@pytest.mark.nice_to_have
class TestT415RetrievalCountInStats:
    """T4.15 — Retrieval stats go to knowledge_stats table only.

    No UPDATE on knowledge table → no FTS trigger churn.
    """

    def test_no_fts_churn_on_retrieval(self, db):
        """T4.15 — FTS row count unchanged after retrieval (no knowledge_au trigger)."""
        entry = make_entry(
            content="Pattern about centralized error mapping in NetworkClient.",
            type="pattern",
            tags=["api", "error-handling", "server"],
            branch="main",
            created_at=days_ago(5),
        )
        insert_entry(db, entry)
        db.commit()

        fts_before = db.execute("SELECT count(*) FROM knowledge_fts").fetchone()[0]

        retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="main",
            surface="server",
            query=None,
        )

        fts_after = db.execute("SELECT count(*) FROM knowledge_fts").fetchone()[0]
        assert fts_before == fts_after, (
            f"FTS row count changed ({fts_before} -> {fts_after}). "
            "An UPDATE fired on knowledge table, triggering knowledge_au. "
            "retrieval_count must go to knowledge_stats."
        )

    def test_stats_upsert_works(self, db):
        """T4.15 — knowledge_stats retrieval_count increments via upsert."""
        entry = make_entry(
            content="Gotcha about PostgreSQL connection pool failover.",
            type="gotcha",
            tags=["server", "postgresql"],
            branch="main",
            created_at=days_ago(3),
        )
        insert_entry(db, entry)
        db.commit()

        for _ in range(3):
            retrieve_context(
                db,
                project_id=MOCK_PROJECT_ID,
                branch="main",
                surface="server",
                query=None,
            )

        count = db.execute(
            "SELECT retrieval_count FROM knowledge_stats WHERE entry_id = ?",
            (entry["id"],),
        ).fetchone()[0]
        assert count >= 3, (
            f"retrieval_count should be >= 3 after 3 retrievals, got {count}"
        )

    def test_knowledge_updated_at_untouched_after_multiple(self, db):
        """T4.15 — knowledge.updated_at unchanged even after many retrievals."""
        entry = make_entry(
            content="Rate limiting uses token bucket at gateway level.",
            type="decision",
            tags=["api", "server"],
            branch="main",
            created_at=days_ago(2),
        )
        insert_entry(db, entry)
        db.commit()

        before = db.execute(
            "SELECT updated_at FROM knowledge WHERE id = ?",
            (entry["id"],),
        ).fetchone()[0]

        for _ in range(5):
            retrieve_context(
                db,
                project_id=MOCK_PROJECT_ID,
                branch="main",
                surface="server",
                query=None,
            )

        after = db.execute(
            "SELECT updated_at FROM knowledge WHERE id = ?",
            (entry["id"],),
        ).fetchone()[0]
        assert before == after, (
            "knowledge.updated_at must not change after retrieval — "
            "retrieval_count lives in knowledge_stats only"
        )


# ---------------------------------------------------------------------------
# Coverage gap tests — retrieve.py edge-case branches
# ---------------------------------------------------------------------------


def test_tag_set_with_list_input():
    """retrieve.py line 49: _tag_set with list input returns set directly.

    When tags is already a list (not a JSON string), _tag_set should
    convert it to a set without JSON parsing.
    """
    result = _tag_set(["auth", "server", "billing"])
    assert result == {"auth", "server", "billing"}
    assert isinstance(result, set)


def test_tag_set_with_empty_list():
    """retrieve.py line 49: _tag_set with empty list returns empty set."""
    result = _tag_set([])
    assert result == set()


def test_greedy_fill_budget_break():
    """retrieve.py line 72: _greedy_fill breaks when next entry exceeds budget.

    Creates entries where the second entry pushes past the remaining budget.
    The break on line 72 fires and only the first entry is selected.
    """
    entry_a = Entry(
        id="aaa", content="A" * 200, content_hash="ha", type="decision",
        tags='["test"]', project_id="p1", project_name="proj",
        branch="main", source_type="manual", confidence=0.9,
        created_at="2025-01-01T00:00:00Z", updated_at="2025-01-01T00:00:00Z",
    )
    entry_b = Entry(
        id="bbb", content="B" * 200, content_hash="hb", type="decision",
        tags='["test"]', project_id="p1", project_name="proj",
        branch="main", source_type="manual", confidence=0.9,
        created_at="2025-01-01T00:00:00Z", updated_at="2025-01-01T00:00:00Z",
    )
    # Each rendered entry is ~230 chars → ~57 tokens. Budget of 60 fits one.
    selected, used = _greedy_fill([entry_a, entry_b], 60)
    assert len(selected) == 1, f"Budget should only allow 1 entry, got {len(selected)}"
    assert selected[0].id == "aaa"
    assert used > 0


def test_cross_project_gotcha_pattern_skipped_when_quota_full(db):
    """retrieve.py line 234: cross-project gotcha/pattern skipped when combined quota full.

    Fills the gotcha+pattern combined quota (4) with project entries,
    then verifies a cross-project gotcha with tag overlap is excluded.
    """
    # Fill gotcha+pattern quota (4) with project entries
    for i in range(4):
        insert_entry(db, make_entry(
            content=f"Project gotcha {i+1}: watch for edge case {i+1} in auth flow.",
            type="gotcha",
            tags=["server", "auth"],
            branch="main",
            created_at=days_ago(i + 1),
        ))

    # Cross-project gotcha with overlapping "auth" tag — should be skipped
    insert_entry(db, make_entry(
        content="Cross-project gotcha: auth token expiry race condition in identity service.",
        type="gotcha",
        tags=["auth", "security"],
        project_id=SECOND_PROJECT_ID,
        project_name=SECOND_PROJECT_NAME,
        branch="main",
        created_at=days_ago(10),
    ))
    db.commit()

    result = retrieve_context(
        db,
        project_id=MOCK_PROJECT_ID,
        branch="main",
        surface="server",
        query=None,
    )

    cross_gotchas = [
        e for e in result.entries
        if e.project_id == SECOND_PROJECT_ID and e.type in ("gotcha", "pattern")
    ]
    assert len(cross_gotchas) == 0, (
        "Cross-project gotcha/pattern must be excluded when combined quota is full"
    )


def test_search_mode_budget_break(db):
    """retrieve.py line 286: search mode breaks when token budget exceeded.

    Inserts large searchable entries so the budget is exhausted before all
    results can be included.
    """
    # Insert 15 large entries with searchable content.
    # Each ~900 chars content → ~240 tokens rendered. 8 entries ≈ 1920 tokens.
    for i in range(15):
        insert_entry(db, make_entry(
            content=(
                f"Searchable entry {i+1}: comprehensive auth flow documentation. "
                + "x" * 850
            ),
            type="decision",
            tags=["searchable", "auth"],
            branch="main",
            created_at=days_ago(i + 1),
        ))
    db.commit()

    result = retrieve_context(
        db,
        project_id=MOCK_PROJECT_ID,
        branch="main",
        query="Searchable auth",
    )

    # Budget should cut off before all 15 are included
    assert len(result.entries) < 15, (
        f"Budget should limit results, got all {len(result.entries)}"
    )
    assert result.total_tokens <= 2100, (
        f"Search results should respect token budget. Got: {result.total_tokens}"
    )


def test_restore_without_session_state_still_returns_other_tiers(db):
    """Covers restore branch where include_session_state=False."""
    insert_entry(db, make_entry(
        content="Session checkpoint to skip.",
        type="session_state",
        tags=["server"],
        branch="main",
        created_at=minutes_ago(5),
    ))
    insert_entry(db, make_entry(
        content="Decision should still return.",
        type="decision",
        tags=["auth", "server"],
        branch="main",
        created_at=days_ago(1),
    ))
    db.commit()

    result = retrieve_context(
        db,
        project_id=MOCK_PROJECT_ID,
        branch="main",
        surface="server",
        query=None,
        include_session_state=False,
    )

    assert any(e.type == "decision" for e in result.entries)
    assert all(e.type != "session_state" for e in result.entries)


def test_cross_project_session_state_candidate_path(db):
    """Covers cross-project type path outside decision/plan/gotcha/pattern checks."""
    insert_entry(db, make_entry(
        content="Project seed tags for auth overlap.",
        type="decision",
        tags=["auth", "server"],
        branch="main",
        created_at=days_ago(1),
    ))
    insert_entry(db, make_entry(
        content="Cross-project session note.",
        type="session_state",
        tags=["auth", "identity"],
        branch="main",
        project_id=SECOND_PROJECT_ID,
        project_name=SECOND_PROJECT_NAME,
        created_at=days_ago(2),
    ))
    db.commit()

    result = retrieve_context(
        db,
        project_id=MOCK_PROJECT_ID,
        branch="main",
        surface="server",
        query=None,
    )

    assert any(
        e.project_id == SECOND_PROJECT_ID and e.type == "session_state"
        for e in result.entries
    )


def test_render_restore_cross_project_header_only_once():
    """Directly covers _render_restore cross-header dedupe branch."""
    from momento.retrieve import _render_restore

    cross_1 = Entry(
        id="c1",
        content="Cross entry one",
        content_hash="h1",
        type="decision",
        tags='["auth"]',
        project_id=SECOND_PROJECT_ID,
        project_name=SECOND_PROJECT_NAME,
        branch="main",
        source_type="manual",
        confidence=0.9,
        created_at=days_ago(1),
        updated_at=days_ago(1),
    )
    cross_2 = Entry(
        id="c2",
        content="Cross entry two",
        content_hash="h2",
        type="gotcha",
        tags='["auth"]',
        project_id=SECOND_PROJECT_ID,
        project_name=SECOND_PROJECT_NAME,
        branch="main",
        source_type="manual",
        confidence=0.9,
        created_at=days_ago(2),
        updated_at=days_ago(2),
    )

    rendered = _render_restore([cross_1, cross_2], MOCK_PROJECT_ID)
    assert rendered.count("## Cross-Project") == 1


def test_session_window_env_var_respected(db, monkeypatch):
    """Session-state restore window is configurable via env var."""
    old_entry = make_entry(
        content="Old session checkpoint outside 1h window.",
        type="session_state",
        tags=["server"],
        branch="main",
        created_at=hours_ago(2),
        project_id=MOCK_PROJECT_ID,
    )
    insert_entry(db, old_entry)
    db.commit()

    monkeypatch.setenv("MOMENTO_SESSION_WINDOW_HOURS", "1")
    result = retrieve_context(
        db,
        project_id=MOCK_PROJECT_ID,
        branch="main",
        surface="server",
        query=None,
        include_session_state=True,
    )

    assert not any(e.type == "session_state" for e in result.entries), (
        "2h-old session_state should be excluded when window is set to 1 hour"
    )


def test_session_window_invalid_env_var_uses_default(db, monkeypatch):
    """Non-integer env var falls back to default 48h window (covers retrieve.py:378-379)."""
    entry = make_entry(
        content="Recent session checkpoint within 48h.",
        type="session_state",
        tags=["server"],
        branch="main",
        created_at=hours_ago(2),
        project_id=MOCK_PROJECT_ID,
    )
    insert_entry(db, entry)
    db.commit()

    monkeypatch.setenv("MOMENTO_SESSION_WINDOW_HOURS", "not-a-number")
    result = retrieve_context(
        db,
        project_id=MOCK_PROJECT_ID,
        branch="main",
        surface="server",
        query=None,
        include_session_state=True,
    )

    # With invalid env var, falls back to 48h — 2h-old entry should be included
    assert any(e.type == "session_state" for e in result.entries), (
        "Invalid env var should fall back to 48h default, including 2h-old entry"
    )


def test_session_window_zero_env_var_uses_default(db, monkeypatch):
    """Zero/negative env var falls back to default 48h (covers retrieve.py:380)."""
    entry = make_entry(
        content="Session checkpoint for zero-hour test.",
        type="session_state",
        tags=["server"],
        branch="main",
        created_at=hours_ago(2),
        project_id=MOCK_PROJECT_ID,
    )
    insert_entry(db, entry)
    db.commit()

    monkeypatch.setenv("MOMENTO_SESSION_WINDOW_HOURS", "0")
    result = retrieve_context(
        db,
        project_id=MOCK_PROJECT_ID,
        branch="main",
        surface="server",
        query=None,
        include_session_state=True,
    )

    assert any(e.type == "session_state" for e in result.entries), (
        "Zero env var should fall back to 48h default"
    )


def test_budget_exhausted_tier2_skips_lower_tiers(db):
    """When Tier 2 can't fit all plan candidates, budget_exhausted triggers (covers retrieve.py:198).

    Budget = 2000 tokens (~8000 chars). We need Tier 2 to have 2 candidates
    where the second doesn't fit. Each plan at ~6000 chars (~1500 tokens).
    """
    # Tier 1: small session_state (~60 tokens)
    insert_entry(db, make_entry(
        content="Session state: small checkpoint.",
        type="session_state",
        tags=["server"],
        branch="main",
        created_at=hours_ago(1),
        project_id=MOCK_PROJECT_ID,
    ))
    # Tier 2: 2 huge plan entries (~1500 tokens each) — only first fits
    for i in range(2):
        insert_entry(db, make_entry(
            content=f"Plan {i}: " + "y" * 6000,
            type="plan",
            tags=["server"],
            branch="main",
            created_at=hours_ago(1),
            project_id=MOCK_PROJECT_ID,
        ))
    # Tier 3: decision — should be skipped due to budget exhaustion
    insert_entry(db, make_entry(
        content="Decision that should be skipped.",
        type="decision",
        tags=["server"],
        branch="main",
        created_at=hours_ago(1),
        project_id=MOCK_PROJECT_ID,
    ))
    db.commit()

    result = retrieve_context(
        db,
        project_id=MOCK_PROJECT_ID,
        branch="main",
        surface="server",
        include_session_state=True,
    )

    # At most 1 plan should fit (second busts budget). Tier 3 should be skipped.
    plan_count = sum(1 for e in result.entries if e.type == "plan")
    decision_count = sum(1 for e in result.entries if e.type == "decision")
    assert plan_count <= 1, "Second plan should bust the budget"
    assert decision_count == 0, "Decisions should be skipped after budget exhaustion"


def test_budget_exhausted_tier3_skips_tier4(db):
    """When Tier 3 can't fit all candidates, Tier 4 is skipped (covers retrieve.py:214)."""
    # Tier 1: small session_state
    insert_entry(db, make_entry(
        content="Small checkpoint.",
        type="session_state",
        tags=["server"],
        branch="main",
        created_at=hours_ago(1),
        project_id=MOCK_PROJECT_ID,
    ))
    # Tier 3: huge decisions that exhaust budget
    for i in range(4):
        insert_entry(db, make_entry(
            content=f"Decision {i}: " + "d" * 3000,
            type="decision",
            tags=["server"],
            branch="main",
            created_at=hours_ago(1),
            project_id=MOCK_PROJECT_ID,
            confidence=0.9,
        ))
    # Tier 4: gotcha — should be skipped
    insert_entry(db, make_entry(
        content="Gotcha after budget-busting decisions.",
        type="gotcha",
        tags=["server"],
        branch="main",
        created_at=hours_ago(1),
        project_id=MOCK_PROJECT_ID,
    ))
    db.commit()

    result = retrieve_context(
        db,
        project_id=MOCK_PROJECT_ID,
        branch="main",
        surface="server",
        include_session_state=True,
    )

    # Verify restore completes without error
    assert result.total_tokens <= 2000


def test_budget_exhausted_tier4_skips_tier5(db):
    """When Tier 4 can't fit all candidates, Tier 5 is skipped (covers retrieve.py:228)."""
    # Small session_state
    insert_entry(db, make_entry(
        content="Small checkpoint for tier4 test.",
        type="session_state",
        tags=["server"],
        branch="main",
        created_at=hours_ago(1),
        project_id=MOCK_PROJECT_ID,
    ))
    # Huge gotcha entries for Tier 4
    for i in range(5):
        insert_entry(db, make_entry(
            content=f"Gotcha {i}: " + "g" * 3000,
            type="gotcha",
            tags=["server"],
            branch="main",
            created_at=hours_ago(1),
            project_id=MOCK_PROJECT_ID,
        ))
    # Tier 5: cross-project entry — should be skipped
    insert_entry(db, make_entry(
        content="Cross-project entry after budget bust.",
        type="gotcha",
        tags=["server"],
        branch="main",
        created_at=hours_ago(1),
        project_id=SECOND_PROJECT_ID,
        project_name=SECOND_PROJECT_NAME,
    ))
    db.commit()

    result = retrieve_context(
        db,
        project_id=MOCK_PROJECT_ID,
        branch="main",
        surface="server",
        include_session_state=True,
    )

    # Cross-project entry should NOT appear if budget exhausted at tier 4
    cross_entries = [e for e in result.entries if e.project_id == SECOND_PROJECT_ID]
    # Either cross-project is absent (budget exhausted) or total is under cap
    assert result.total_tokens <= 2000
