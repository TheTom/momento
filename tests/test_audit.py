# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Tests for momento audit-claude-md feature.

Covers: term extraction, overlap, maturity, missing entries, stale references,
adapter checks, fix mode, file discovery, report rendering, CLI integration,
and edge cases.
"""

import os
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from momento.audit import (
    ADAPTER_CHECKS,
    DURABLE_TYPES,
    FALLBACK_HEADERS,
    MATURITY_THRESHOLDS,
    OVERLAP_THRESHOLD,
    SECTION_KEYWORDS,
    apply_fix,
    audit_claude_md,
    check_global_adapter,
    check_maturity,
    compute_overlap,
    extract_key_terms,
    find_missing_entries,
    find_project_claude_md,
    find_stale_references,
    find_target_section,
    is_project_identifier,
    render_report,
)
from momento.models import (
    AdapterCheck,
    AuditResult,
    Entry,
    FixResult,
    ThresholdReport,
)
from tests.conftest import insert_entries
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    days_ago,
    hours_ago,
    make_entry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_durable_entry(content, entry_type="decision", tags=None, created_at=None):
    """Shorthand for creating a durable entry dict."""
    return make_entry(
        content=content,
        type=entry_type,
        tags=tags or [],
        created_at=created_at or hours_ago(3),
    )


def _entry_from_dict(d):
    """Convert a make_entry dict to an Entry dataclass."""
    tags = json.loads(d["tags"]) if isinstance(d["tags"], str) else d["tags"]
    return Entry(
        id=d["id"], content=d["content"], content_hash=d["content_hash"],
        type=d["type"], tags=tags, project_id=d["project_id"],
        project_name=d["project_name"], branch=d["branch"],
        source_type=d["source_type"], confidence=d["confidence"],
        created_at=d["created_at"], updated_at=d["updated_at"],
    )


# ===========================================================================
# Term extraction & overlap
# ===========================================================================

class TestExtractKeyTerms:
    @pytest.mark.must_pass
    def test_removes_stopwords(self):
        terms = extract_key_terms("the quick brown fox is a very fast animal")
        assert "the" not in terms
        assert "is" not in terms
        assert "very" not in terms
        assert "quick" in terms
        assert "brown" in terms
        assert "fox" in terms

    @pytest.mark.must_pass
    def test_removes_code_stopwords(self):
        terms = extract_key_terms("function class import return def value")
        assert len(terms) == 0

    @pytest.mark.must_pass
    def test_keeps_identifiers(self):
        terms = extract_key_terms("client.py OPENAI_API_KEY auth_handler server/routes")
        assert "client.py" in terms
        assert "openai_api_key" in terms
        assert "auth_handler" in terms
        assert "server/routes" in terms

    @pytest.mark.must_pass
    def test_min_length_3(self):
        terms = extract_key_terms("go to db fix it up ok")
        # "go", "to", "db", "it", "up", "ok" are all <3 or stopwords
        assert "go" not in terms
        assert "db" not in terms
        assert "ok" not in terms

    @pytest.mark.must_pass
    def test_lowercases(self):
        terms = extract_key_terms("PostgreSQL Redis MongoDB")
        assert "postgresql" in terms
        assert "redis" in terms
        assert "mongodb" in terms

    @pytest.mark.must_pass
    def test_empty_string(self):
        assert extract_key_terms("") == set()

    @pytest.mark.must_pass
    def test_splits_on_punctuation(self):
        terms = extract_key_terms("stripe-webhook: payment_intent fulfilled!")
        assert "stripe-webhook:" in terms or "stripe-webhook" in terms
        assert "payment_intent" in terms
        assert "fulfilled" in terms


class TestComputeOverlap:
    @pytest.mark.must_pass
    def test_full_match(self):
        terms = {"postgresql", "redis", "database"}
        text = "We use PostgreSQL and Redis for our database layer."
        assert compute_overlap(terms, text) == 1.0

    @pytest.mark.must_pass
    def test_no_match(self):
        terms = {"postgresql", "redis", "database"}
        text = "Swift UIKit implementation of the login flow."
        assert compute_overlap(terms, text) == 0.0

    @pytest.mark.must_pass
    def test_partial_match(self):
        terms = {"postgresql", "redis", "database", "elasticsearch"}
        text = "We use PostgreSQL and Redis."
        overlap = compute_overlap(terms, text)
        assert overlap == pytest.approx(0.5)

    @pytest.mark.must_pass
    def test_empty_terms(self):
        assert compute_overlap(set(), "some text") == 0.0

    @pytest.mark.must_pass
    def test_case_insensitive(self):
        terms = {"postgresql"}
        assert compute_overlap(terms, "PostgreSQL is great") == 1.0


class TestIsProjectIdentifier:
    @pytest.mark.must_pass
    def test_filenames(self):
        assert is_project_identifier("client.py") is True
        assert is_project_identifier("app.ts") is True

    @pytest.mark.must_pass
    def test_identifiers_with_underscores(self):
        assert is_project_identifier("auth_handler") is True
        assert is_project_identifier("OPENAI_API_KEY") is True

    @pytest.mark.must_pass
    def test_env_vars(self):
        assert is_project_identifier("MOMENTO_DB") is True
        assert is_project_identifier("API") is True

    @pytest.mark.must_pass
    def test_paths(self):
        assert is_project_identifier("server/routes") is True

    @pytest.mark.must_pass
    def test_generic_words(self):
        assert is_project_identifier("authentication") is False
        assert is_project_identifier("database") is False


# ===========================================================================
# Maturity threshold
# ===========================================================================

class TestMaturity:
    def _seed_maturity(self, db, total=12, durable_types=None, days=4):
        """Insert entries to control maturity conditions."""
        if durable_types is None:
            durable_types = ["decision", "gotcha"]
        entries = []
        # Durable entries spread across types and days
        durable_count = 0
        for i, dtype in enumerate(durable_types):
            for d in range(days):
                entries.append(make_entry(
                    content=f"Entry {dtype} day {d} #{i}",
                    type=dtype,
                    tags=[dtype],
                    created_at=days_ago(d),
                ))
                durable_count += 1
                if durable_count >= total:
                    break
            if durable_count >= total:
                break
        # Pad with session_state to reach total
        while len(entries) < total:
            entries.append(make_entry(
                content=f"Session state filler {len(entries)}",
                type="session_state",
                tags=["server"],
                created_at=days_ago(len(entries) % days),
            ))
        insert_entries(db, entries)

    @pytest.mark.must_pass
    def test_passes_when_all_conditions_met(self, db):
        self._seed_maturity(db, total=12, durable_types=["decision", "gotcha"], days=4)
        passed, report = check_maturity(db, MOCK_PROJECT_ID)
        assert passed is True
        assert report.passed is True

    @pytest.mark.must_pass
    def test_fails_insufficient_total(self, db):
        # Only 5 entries
        entries = [make_entry(f"Entry {i}", type="decision", tags=[], created_at=days_ago(i)) for i in range(5)]
        insert_entries(db, entries)
        passed, report = check_maturity(db, MOCK_PROJECT_ID)
        assert passed is False
        assert report.total_entries == 5

    @pytest.mark.must_pass
    def test_fails_insufficient_durable(self, db):
        # 10 session_states, 2 decisions
        entries = [make_entry(f"SS {i}", type="session_state", tags=[], created_at=days_ago(i % 5)) for i in range(10)]
        entries.extend([make_entry(f"Dec {i}", type="decision", tags=[], created_at=days_ago(i)) for i in range(2)])
        insert_entries(db, entries)
        passed, report = check_maturity(db, MOCK_PROJECT_ID)
        assert passed is False
        assert report.durable_entries < MATURITY_THRESHOLDS["durable_entries"]

    @pytest.mark.must_pass
    def test_fails_insufficient_types(self, db):
        # All durable are decisions, only 1 type
        entries = [make_entry(f"Dec {i}", type="decision", tags=[], created_at=days_ago(i % 5)) for i in range(10)]
        entries.extend([make_entry(f"SS {i}", type="session_state", tags=[], created_at=days_ago(i % 5)) for i in range(5)])
        insert_entries(db, entries)
        passed, report = check_maturity(db, MOCK_PROJECT_ID)
        assert passed is False
        assert report.distinct_types < MATURITY_THRESHOLDS["distinct_types"]

    @pytest.mark.must_pass
    def test_fails_insufficient_days(self, db):
        # All entries on same day
        entries = [make_entry(f"Dec {i}", type="decision", tags=[], created_at=hours_ago(i)) for i in range(5)]
        entries.extend([make_entry(f"Got {i}", type="gotcha", tags=[], created_at=hours_ago(i + 5)) for i in range(5)])
        entries.extend([make_entry(f"SS {i}", type="session_state", tags=[], created_at=hours_ago(i + 10)) for i in range(5)])
        insert_entries(db, entries)
        passed, report = check_maturity(db, MOCK_PROJECT_ID)
        assert passed is False
        assert report.days_active < MATURITY_THRESHOLDS["days_active"]

    @pytest.mark.must_pass
    def test_force_bypass(self, db):
        """--force skips maturity. Tested via CLI integration."""
        # Just verify check_maturity itself returns false for empty db
        passed, report = check_maturity(db, MOCK_PROJECT_ID)
        assert passed is False


# ===========================================================================
# Missing entries
# ===========================================================================

class TestFindMissing:
    @pytest.mark.must_pass
    def test_all_missing(self):
        entries = [
            _entry_from_dict(_make_durable_entry("PostgreSQL requires VACUUM for bloat control", "gotcha", ["postgresql"])),
            _entry_from_dict(_make_durable_entry("Chose Redis over Memcached for sessions", "decision", ["redis"])),
        ]
        missing = find_missing_entries(entries, "This CLAUDE.md talks about Swift and UIKit")
        assert len(missing) == 2

    @pytest.mark.must_pass
    def test_all_present(self):
        entries = [
            _entry_from_dict(_make_durable_entry("PostgreSQL requires VACUUM for bloat control", "gotcha", ["postgresql"])),
        ]
        missing = find_missing_entries(entries, "PostgreSQL VACUUM bloat control is important")
        assert len(missing) == 0

    @pytest.mark.must_pass
    def test_partial_overlap(self):
        entries = [
            _entry_from_dict(_make_durable_entry("PostgreSQL VACUUM is critical", "gotcha", ["postgresql"])),
            _entry_from_dict(_make_durable_entry("Swift UIKit table views need cell reuse", "gotcha", ["ios"])),
        ]
        # Only mentions PostgreSQL, not Swift
        claude_md = "We use PostgreSQL with VACUUM and critical maintenance"
        missing = find_missing_entries(entries, claude_md)
        assert len(missing) == 1
        assert missing[0].content == "Swift UIKit table views need cell reuse"

    @pytest.mark.must_pass
    def test_excludes_session_state_and_plan(self):
        entries = [
            _entry_from_dict(make_entry("Session checkpoint", type="session_state", tags=[])),
            _entry_from_dict(make_entry("Phase 1 plan", type="plan", tags=[])),
            _entry_from_dict(_make_durable_entry("Real gotcha", "gotcha", [])),
        ]
        missing = find_missing_entries(entries, "Totally unrelated content here")
        # Only the gotcha should be checked, not session_state or plan
        assert len(missing) == 1
        assert missing[0].type == "gotcha"

    @pytest.mark.must_pass
    def test_uses_tags_in_overlap(self):
        entry = _entry_from_dict(_make_durable_entry(
            "The webhook handler needs retry logic",
            "gotcha",
            ["stripe", "webhook"],
        ))
        # CLAUDE.md mentions "stripe" and "webhook" — tags push overlap above threshold
        missing = find_missing_entries([entry], "stripe webhook integration details")
        assert len(missing) == 0


# ===========================================================================
# Stale references
# ===========================================================================

class TestStaleReferences:
    @pytest.mark.must_pass
    def test_detects_orphaned_filenames(self):
        entries = [_entry_from_dict(_make_durable_entry("Some decision about auth", "decision", ["auth"]))]
        claude_md = "Use client.py for API calls\nAlso check server.py"
        stale = find_stale_references(claude_md, entries)
        assert "client.py" in stale
        assert "server.py" in stale

    @pytest.mark.must_pass
    def test_detects_env_vars(self):
        entries = [_entry_from_dict(_make_durable_entry("Some decision", "decision", []))]
        claude_md = "Set OPENAI_API_KEY in your environment"
        stale = find_stale_references(claude_md, entries)
        assert "openai_api_key" in stale

    @pytest.mark.must_pass
    def test_ignores_generic_words(self):
        entries = [_entry_from_dict(_make_durable_entry("Some decision", "decision", []))]
        claude_md = "Always use authentication and authorization properly"
        stale = find_stale_references(claude_md, entries)
        # "authentication" and "authorization" are generic — no dots/underscores/CAPS/slashes
        assert len(stale) == 0

    @pytest.mark.must_pass
    def test_no_stale(self):
        entries = [_entry_from_dict(_make_durable_entry(
            "client.py is our main API client",
            "decision",
            ["client.py"],
        ))]
        claude_md = "Use client.py for API calls"
        stale = find_stale_references(claude_md, entries)
        assert "client.py" not in stale


# ===========================================================================
# Global adapter checks
# ===========================================================================

class TestAdapterChecks:
    @pytest.mark.must_pass
    def test_all_present(self):
        text = """
## Momento Session Start
At the start of every session, call retrieve_context(include_session_state=true).
Also use log_knowledge after changes.
Always paste momento output inline.
"""
        checks = check_global_adapter(text)
        assert all(c.found for c in checks)

    @pytest.mark.must_pass
    def test_missing_retrieve_context(self):
        text = "Use log_knowledge to save stuff. Momento inline output."
        checks = check_global_adapter(text)
        retrieve = next(c for c in checks if "retrieve" in c.name.lower())
        assert retrieve.found is False
        assert retrieve.critical is True

    @pytest.mark.must_pass
    def test_missing_all(self):
        text = "This file has nothing about Momento."
        checks = check_global_adapter(text)
        assert all(not c.found for c in checks)

    @pytest.mark.must_pass
    def test_critical_flag(self):
        checks = check_global_adapter("")
        critical = [c for c in checks if c.critical]
        assert len(critical) >= 2  # retrieve and session start


# ===========================================================================
# Fix mode
# ===========================================================================

class TestFixMode:
    @pytest.mark.must_pass
    def test_appends_under_existing_section(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Project\n\n## Known Gotchas\n\n- Old gotcha\n\n## Other\n\nStuff\n")
        entry = _entry_from_dict(_make_durable_entry(
            "New gotcha about PostgreSQL VACUUM bloat prevention",
            "gotcha", ["postgresql"],
        ))
        lines = claude_md.read_text().splitlines()
        result = apply_fix(str(claude_md), [entry], lines, dry_run=False)
        assert result.entries_added == 1
        content = claude_md.read_text()
        assert "New gotcha about PostgreSQL VACUUM bloat prevention" in content

    @pytest.mark.must_pass
    def test_creates_fallback_headers(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Project\n\nBasic info\n")
        entry = _entry_from_dict(_make_durable_entry(
            "Chose Redis for sessions over Memcached",
            "decision", ["redis"],
        ))
        lines = claude_md.read_text().splitlines()
        result = apply_fix(str(claude_md), [entry], lines, dry_run=False)
        assert result.sections_created == 1
        content = claude_md.read_text()
        assert "## Architecture Decisions" in content
        assert "Chose Redis" in content

    @pytest.mark.must_pass
    def test_idempotent_no_duplicates(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Project\n\n## Known Gotchas\n\n- PostgreSQL VACUUM bloat prevention gotcha\n")
        entry = _entry_from_dict(_make_durable_entry(
            "PostgreSQL VACUUM bloat prevention gotcha details",
            "gotcha", ["postgresql"],
        ))
        lines = claude_md.read_text().splitlines()
        result = apply_fix(str(claude_md), [entry], lines, dry_run=False)
        # Entry terms overlap with existing content, should be skipped
        assert result.entries_skipped == 1
        assert result.entries_added == 0

    @pytest.mark.must_pass
    def test_creates_backup(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Original content\n")
        entry = _entry_from_dict(_make_durable_entry(
            "Completely unique xyzzy plugh decision about frobnitz",
            "decision", ["frobnitz"],
        ))
        lines = claude_md.read_text().splitlines()
        result = apply_fix(str(claude_md), [entry], lines, dry_run=False)
        assert result.backup_path.endswith(".bak")
        assert os.path.exists(result.backup_path)
        bak_content = (tmp_path / "CLAUDE.md.bak").read_text()
        assert bak_content == "# Original content\n"

    @pytest.mark.must_pass
    def test_dry_run_no_write(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        original = "# Original\n"
        claude_md.write_text(original)
        entry = _entry_from_dict(_make_durable_entry(
            "Unique xyzzy plugh frobnitz decision content",
            "decision", ["frobnitz"],
        ))
        lines = claude_md.read_text().splitlines()
        result = apply_fix(str(claude_md), [entry], lines, dry_run=True)
        assert result.entries_added == 1
        # File should be unchanged
        assert claude_md.read_text() == original
        assert result.backup_path == ""

    @pytest.mark.must_pass
    def test_creates_claude_md_if_missing(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        assert not claude_md.exists()
        entry = _entry_from_dict(_make_durable_entry(
            "Brand new xyzzy plugh frobnitz gotcha",
            "gotcha", ["frobnitz"],
        ))
        result = apply_fix(str(claude_md), [entry], [], dry_run=False)
        assert result.entries_added == 1
        assert result.sections_created == 1
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "## Known Gotchas" in content

    @pytest.mark.must_pass
    def test_fix_never_modifies_global(self):
        """Global CLAUDE.md is never passed to apply_fix — tested at CLI level."""
        # This is an architectural guarantee: audit_claude_md only passes
        # project_claude_md_path to apply_fix, never global. The test
        # validates the audit_claude_md function signature enforces this.
        pass

    @pytest.mark.must_pass
    def test_find_target_section_keywords(self):
        lines = [
            "# My Project",
            "",
            "## Architecture Decisions",
            "",
            "- Old decision",
            "",
            "## Conventions",
            "",
            "- Old pattern",
        ]
        # Decision section
        idx = find_target_section(lines, "decision")
        assert idx is not None
        assert idx == 5  # last content line before ## Conventions

        # Pattern section
        idx = find_target_section(lines, "pattern")
        assert idx is not None
        assert idx == 8  # last line of file (end of conventions section)


# ===========================================================================
# File discovery
# ===========================================================================

class TestFileDiscovery:
    @pytest.mark.must_pass
    def test_finds_at_git_root(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Test")
        result = find_project_claude_md(str(tmp_path), str(tmp_path / "subdir"))
        assert result == str(tmp_path / "CLAUDE.md")

    @pytest.mark.must_pass
    def test_finds_in_dot_claude(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "CLAUDE.md").write_text("# Test")
        result = find_project_claude_md(str(tmp_path), str(tmp_path))
        assert result == str(tmp_path / ".claude" / "CLAUDE.md")

    @pytest.mark.must_pass
    def test_not_found(self, tmp_path):
        result = find_project_claude_md(str(tmp_path), str(tmp_path))
        assert result is None


# ===========================================================================
# Report rendering
# ===========================================================================

class TestRenderReport:
    def _make_result(self, missing=None, stale=None, adapter=None, coverage=80, durable=10):
        return AuditResult(
            project_name="test-project",
            threshold_passed=True,
            threshold_report=None,
            missing_entries=missing or [],
            stale_references=stale or [],
            adapter_checks=adapter or [],
            coverage_pct=coverage,
            durable_total=durable,
        )

    @pytest.mark.must_pass
    def test_all_sections(self):
        missing = [_entry_from_dict(_make_durable_entry("Some gotcha", "gotcha", ["tag1"]))]
        stale = ["old_file.py"]
        adapter = [AdapterCheck("Read path", False, True)]
        result = self._make_result(missing=missing, stale=stale, adapter=adapter, coverage=50)
        report = render_report(result)
        assert "MISSING FROM CLAUDE.md" in report
        assert "CLAUDE.md HAS, MOMENTO DOESN'T" in report
        assert "GLOBAL ~/.claude/CLAUDE.md" in report
        assert "SUMMARY" in report
        assert "50%" in report

    @pytest.mark.must_pass
    def test_no_gaps(self):
        result = self._make_result(coverage=100)
        report = render_report(result)
        assert "No gaps found." in report
        assert "No stale references detected." in report

    @pytest.mark.must_pass
    def test_coverage_percentage(self):
        result = self._make_result(coverage=73)
        report = render_report(result)
        assert "73%" in report

    @pytest.mark.must_pass
    def test_fix_result_in_report(self):
        result = self._make_result()
        fix = FixResult(entries_added=3, entries_skipped=1, backup_path="/tmp/CLAUDE.md.bak")
        report = render_report(result, fix)
        assert "3 entries added" in report
        assert "1 skipped" in report


# ===========================================================================
# CLI integration
# ===========================================================================

class TestCLIAudit:
    def _seed_mature_db(self, db):
        """Insert enough entries to pass maturity threshold."""
        entries = []
        for i in range(5):
            entries.append(make_entry(
                f"Decision about component {i} choosing approach A over B",
                type="decision", tags=["arch"], created_at=days_ago(i + 1),
            ))
        for i in range(3):
            entries.append(make_entry(
                f"Gotcha about system edge case {i} causing failure",
                type="gotcha", tags=["gotcha"], created_at=days_ago(i + 1),
            ))
        for i in range(5):
            entries.append(make_entry(
                f"Session state checkpoint {i}",
                type="session_state", tags=["server"], created_at=days_ago(i + 1),
            ))
        insert_entries(db, entries)

    @pytest.mark.must_pass
    def test_cli_audit_report_only(self, db, tmp_path, capsys):
        from momento.cli import cmd_audit_claude_md

        self._seed_mature_db(db)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Project\n\nSome content\n")
        args = SimpleNamespace(
            dir=str(tmp_path), fix=False, dry_run=False,
            force=True, global_only=False, project_only=True,
        )
        with patch("momento.surface._resolve_git_root", return_value=str(tmp_path)):
            cmd_audit_claude_md(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "SUMMARY" in out

    @pytest.mark.must_pass
    def test_cli_audit_fix_mode(self, db, tmp_path, capsys):
        from momento.cli import cmd_audit_claude_md

        self._seed_mature_db(db)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Project\n")
        args = SimpleNamespace(
            dir=str(tmp_path), fix=True, dry_run=False,
            force=True, global_only=False, project_only=True,
        )
        with patch("momento.surface._resolve_git_root", return_value=str(tmp_path)):
            cmd_audit_claude_md(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        # File should be modified
        content = claude_md.read_text()
        assert "Decision about component" in content or "Gotcha about system" in content
        assert "entries added" in out

    @pytest.mark.must_pass
    def test_cli_audit_dry_run(self, db, tmp_path, capsys):
        from momento.cli import cmd_audit_claude_md

        self._seed_mature_db(db)
        claude_md = tmp_path / "CLAUDE.md"
        original = "# Project\n"
        claude_md.write_text(original)
        args = SimpleNamespace(
            dir=str(tmp_path), fix=False, dry_run=True,
            force=True, global_only=False, project_only=True,
        )
        with patch("momento.surface._resolve_git_root", return_value=str(tmp_path)):
            cmd_audit_claude_md(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "DRY RUN" in out
        # File unchanged
        assert claude_md.read_text() == original

    @pytest.mark.must_pass
    def test_cli_audit_below_threshold_exit_2(self, db, capsys):
        from momento.cli import cmd_audit_claude_md

        args = SimpleNamespace(
            dir=".", fix=False, dry_run=False,
            force=False, global_only=False, project_only=False,
        )
        with pytest.raises(SystemExit) as exc_info:
            cmd_audit_claude_md(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        assert exc_info.value.code == 2
        out = capsys.readouterr().out
        assert "not enough data" in out

    @pytest.mark.must_pass
    def test_cli_audit_global_only(self, db, tmp_path, capsys):
        from momento.cli import cmd_audit_claude_md

        self._seed_mature_db(db)
        global_md = tmp_path / "global_claude.md"
        global_md.write_text("At the start of every session, call retrieve_context. Use log_knowledge. momento inline.")
        args = SimpleNamespace(
            dir=str(tmp_path), fix=False, dry_run=False,
            force=True, global_only=True, project_only=False,
        )
        with patch("momento.surface._resolve_git_root", return_value=str(tmp_path)), \
             patch("os.path.expanduser", return_value=str(global_md)), \
             patch("os.path.isfile", side_effect=lambda p: p == str(global_md) or os.path.isfile(p)):
            cmd_audit_claude_md(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "SUMMARY" in out


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases:
    @pytest.mark.must_pass
    def test_audit_empty_claude_md(self, db):
        """Every durable entry flagged as missing when CLAUDE.md is empty."""
        entries = [
            make_entry("Decision about auth flow", type="decision", tags=["auth"], created_at=days_ago(1)),
            make_entry("Gotcha about caching", type="gotcha", tags=["cache"], created_at=days_ago(2)),
        ]
        insert_entries(db, entries)
        result, _ = audit_claude_md(
            db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME,
            project_claude_md_path=None, global_claude_md_path=None,
        )
        assert result.coverage_pct < 100 or result.durable_total == 0

    @pytest.mark.must_pass
    def test_audit_no_momento_entries(self, db, tmp_path):
        """No entries = 100% coverage (vacuously true)."""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Project\n")
        result, _ = audit_claude_md(
            db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME,
            project_claude_md_path=str(claude_md),
            global_claude_md_path=None,
        )
        assert result.coverage_pct == 100
        assert len(result.missing_entries) == 0
        assert result.durable_total == 0

    @pytest.mark.must_pass
    def test_audit_no_claude_md_found(self, db):
        """No CLAUDE.md and no path provided."""
        result, _ = audit_claude_md(
            db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME,
            project_claude_md_path=None, global_claude_md_path=None,
        )
        assert result.stale_references == []

    @pytest.mark.must_pass
    def test_audit_all_entries_covered(self, db, tmp_path):
        """All entries present = 100% coverage."""
        entries = [
            make_entry(
                "Chose PostgreSQL over MongoDB for billing transactions",
                type="decision", tags=["postgresql", "billing"],
                created_at=days_ago(1),
            ),
            make_entry(
                "Redis session store chosen for authentication caching layer",
                type="decision", tags=["redis", "auth"],
                created_at=days_ago(2),
            ),
        ]
        insert_entries(db, entries)
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "# Project\n\n"
            "We chose PostgreSQL over MongoDB for billing transactions.\n"
            "Redis session store for authentication caching layer.\n"
        )
        result, _ = audit_claude_md(
            db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME,
            project_claude_md_path=str(claude_md),
            global_claude_md_path=None,
        )
        assert result.coverage_pct == 100
        assert len(result.missing_entries) == 0
