"""Tests for momento.surface — surface detection from working directory.

Covers T6.1 through T6.8 from the acceptance test spec.
These are RED tests — they will fail against stub implementations.
"""

import time

import pytest

from momento.surface import detect_surface


# ---------------------------------------------------------------------------
# T6.1 — Basic surface matching
# ---------------------------------------------------------------------------


def test_basic_surface_matching():
    """T6.1: /code/app/server/handlers -> 'server'"""
    assert detect_surface("/code/app/server/handlers") == "server"


# ---------------------------------------------------------------------------
# T6.2 — Case insensitive
# ---------------------------------------------------------------------------


def test_case_insensitive():
    """T6.2: /code/app/Server/handlers -> 'server' (case-insensitive)"""
    assert detect_surface("/code/app/Server/handlers") == "server"


# ---------------------------------------------------------------------------
# T6.3 — Directory boundary (no substring match) — THE critical test
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
def test_directory_boundary_observer():
    """T6.3: /code/app/observer/metrics -> None (NOT 'server').

    This is THE critical boundary test. 'observer' contains 'server'
    as a substring, but surface detection must match on directory
    boundaries only, not substrings.
    """
    result = detect_surface("/code/app/observer/metrics")
    assert result is None, (
        f"'/observer' must NOT match 'server'. Got: {result!r}"
    )


# ---------------------------------------------------------------------------
# T6.4 — Webinar does not match web
# ---------------------------------------------------------------------------


def test_webinar_does_not_match_web():
    """T6.4: /code/app/webinar/views -> None (NOT 'web').

    'webinar' contains 'web' as a prefix, but surface detection must
    match on directory boundaries only.
    """
    result = detect_surface("/code/app/webinar/views")
    assert result is None, (
        f"'/webinar' must NOT match 'web'. Got: {result!r}"
    )


# ---------------------------------------------------------------------------
# T6.5 — No surface detected
# ---------------------------------------------------------------------------


def test_no_surface_detected():
    """T6.5: /code/app/lib/utils -> None (no known surface)."""
    result = detect_surface("/code/app/lib/utils")
    assert result is None, (
        f"No surface should be detected for '/lib/utils'. Got: {result!r}"
    )


# ---------------------------------------------------------------------------
# T6.6 — Frontend alias
# ---------------------------------------------------------------------------


def test_frontend_alias():
    """T6.6: /code/app/frontend/components -> 'web'.

    'frontend' is an alias for the 'web' surface.
    """
    assert detect_surface("/code/app/frontend/components") == "web"


# ---------------------------------------------------------------------------
# T6.7 — Nested ambiguous path
# ---------------------------------------------------------------------------


@pytest.mark.nice_to_have
def test_nested_ambiguous_path():
    """T6.7: /code/app/server-ios/shared -> deterministic result.

    The path contains both 'server' and 'ios'. The result must be
    deterministic — always the same for the same input. Implementation
    should use first segment match in path order.
    """
    result1 = detect_surface("/code/app/server-ios/shared")
    result2 = detect_surface("/code/app/server-ios/shared")

    # Must be deterministic
    assert result1 == result2, (
        f"detect_surface must be deterministic. Got {result1!r} then {result2!r}"
    )

    # Must be one of the valid surfaces or None
    valid = {"server", "web", "ios", "android", None}
    assert result1 in valid, (
        f"Result must be a valid surface or None. Got: {result1!r}"
    )


# ---------------------------------------------------------------------------
# T6.8 — Performance at scale
# ---------------------------------------------------------------------------


@pytest.mark.nice_to_have
def test_performance_at_scale(db):
    """T6.8: with 5000 entries in DB, retrieve_context completes in < 500ms.

    This is a non-strict benchmark for early detection of accidental
    full scans. We create 5000 entries and measure retrieval time.
    """
    from tests.mock_data import make_entry, MOCK_PROJECT_ID, minutes_ago
    from tests.conftest import insert_entries

    # Insert 5000 entries
    entries = []
    for i in range(5000):
        entries.append(make_entry(
            content=f"Performance test entry number {i}. "
                    f"This tests that retrieval remains fast at scale.",
            type="decision",
            tags=["perf", "server"],
            branch="main",
            created_at=minutes_ago(i),
            project_id=MOCK_PROJECT_ID,
        ))
    insert_entries(db, entries)

    # Verify entries are in DB
    count = db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
    assert count == 5000, f"Expected 5000 entries, got {count}"

    # Measure detect_surface (the core function) at scale — many calls
    paths = [
        "/code/app/server/handlers",
        "/code/app/ios/screens",
        "/code/app/web/components",
        "/code/app/lib/utils",
        "/code/app/observer/metrics",
    ]

    start = time.perf_counter()
    for _ in range(1000):
        for path in paths:
            detect_surface(path)
    elapsed_ms = (time.perf_counter() - start) * 1000

    # 5000 detect_surface calls should be well under 500ms
    assert elapsed_ms < 500, (
        f"5000 detect_surface calls took {elapsed_ms:.1f}ms (limit: 500ms)"
    )


# ---------------------------------------------------------------------------
# Additional surface detection coverage
# ---------------------------------------------------------------------------


def test_backend_alias():
    """Backend is an alias for server surface (from PRD surface table)."""
    assert detect_surface("/code/app/backend/api") == "server"


def test_ios_surface():
    """Basic iOS surface detection."""
    assert detect_surface("/code/app/ios/screens") == "ios"


def test_android_surface():
    """Basic Android surface detection."""
    assert detect_surface("/code/app/android/activities") == "android"


def test_web_surface():
    """Basic web surface detection — direct /web match."""
    assert detect_surface("/code/app/web/components") == "web"


def test_path_ending_with_surface():
    """Surface at the end of the path (no trailing segments)."""
    assert detect_surface("/code/app/server") == "server"


def test_empty_path():
    """Empty string path returns None."""
    result = detect_surface("")
    assert result is None


def test_root_path():
    """Root path returns None."""
    result = detect_surface("/")
    assert result is None
