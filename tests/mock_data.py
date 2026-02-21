# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Mock data factory for Momento tests.

Generates realistic test entries simulating a payments platform project
with server, ios, and web surfaces. All content mirrors real developer
memory — no placeholder strings or lorem ipsum.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Time helpers — deterministic timestamps for tests
# ---------------------------------------------------------------------------

def utc_now() -> str:
    """Current UTC time in ISO 8601 format with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hours_ago(n: int) -> str:
    """UTC timestamp n hours in the past."""
    t = datetime.now(timezone.utc) - timedelta(hours=n)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def days_ago(n: int) -> str:
    """UTC timestamp n days in the past."""
    t = datetime.now(timezone.utc) - timedelta(days=n)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def minutes_ago(n: int) -> str:
    """UTC timestamp n minutes in the past."""
    t = datetime.now(timezone.utc) - timedelta(minutes=n)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Project constants
# ---------------------------------------------------------------------------

MOCK_REMOTE_URL = "git@github.com:acme/payments-platform.git"
MOCK_PROJECT_ID = hashlib.sha256(MOCK_REMOTE_URL.encode()).hexdigest()
MOCK_PROJECT_NAME = "payments-platform"

SECOND_REMOTE_URL = "git@github.com:acme/identity-service.git"
SECOND_PROJECT_ID = hashlib.sha256(SECOND_REMOTE_URL.encode()).hexdigest()
SECOND_PROJECT_NAME = "identity-service"

BRANCHES = ["main", "feature/billing-rewrite", "feature/auth-migration", "hotfix/webhook-race"]
SURFACES = ["server", "ios", "web"]


# ---------------------------------------------------------------------------
# Realistic content pools
# ---------------------------------------------------------------------------

SESSION_STATES = [
    (
        "Migrating AuthService from sync to async/await. Completed: TokenManager actor isolation. "
        "Next: update all callers in /server/handlers to use new async interface. 3 of 7 handlers done."
    ),
    (
        "Debugging webhook race condition. Root cause: Stripe sends fulfillment webhook before our DB "
        "transaction commits. Workaround: 200ms delay with idempotency check. Need to verify under load."
    ),
    (
        "iOS Keychain migration in progress. Moved from raw kSecAttrAccount to wrapper. "
        "4 screens updated, 2 remaining: Settings and PaymentSheet."
    ),
    (
        "Web dashboard billing page complete. Invoice table with pagination, filter by status, "
        "and CSV export. Need to add date range picker and hook up real-time webhook status."
    ),
    (
        "Refactored payment intent creation flow. Moved from direct Stripe API calls to PaymentService "
        "abstraction layer. Unit tests passing, integration tests need Stripe test key rotation."
    ),
]

DECISIONS = [
    (
        "Chose server-side Stripe Checkout over client-side. Rationale: PCI scope reduction, "
        "webhook reliability, and consistent UX across platforms. Rejected: Stripe.js elements "
        "(requires client-side token handling, increases PCI scope)."
    ),
    (
        "Auth tokens: moved from JWT to opaque server-side sessions. JWTs can't be revoked "
        "without a blocklist, which defeats the purpose. Session table adds ~2ms per request. Acceptable."
    ),
    (
        "Database: chose PostgreSQL over MongoDB for billing data. Rationale: ACID transactions "
        "for financial records, strong schema enforcement. MongoDB still used for user profiles."
    ),
    (
        "Rate limiting: token bucket at API gateway level, not per-handler. Rationale: consistent "
        "enforcement, single configuration point. Rejected: per-endpoint limits (too many configs)."
    ),
]

GOTCHAS = [
    (
        "Stripe webhook race: fulfillment event arrives before our DB commit completes. "
        "Always verify payment_intent status server-side before updating order state. "
        "Never trust webhook ordering alone."
    ),
    (
        "iOS Keychain: kSecAttrAccessible must be kSecAttrAccessibleAfterFirstUnlock, "
        "not WhenUnlocked. WhenUnlocked breaks background refresh and silent push handling."
    ),
    (
        "iOS URLSession background upload callbacks can fire after app relaunch. "
        "Persist upload state and correlate by taskIdentifier, not in-memory request objects."
    ),
]

PATTERNS = [
    (
        "All new API endpoints follow: validate -> authorize -> execute -> respond. "
        "No business logic in route handlers. Route handlers are thin dispatchers to service layer."
    ),
    (
        "Error responses always include: error_code (machine-readable), message (human-readable), "
        "request_id (for log correlation). Never expose stack traces or internal state."
    ),
]

PLANS = [
    (
        "Billing rewrite phases: (1) Stripe Checkout migration [current], "
        "(2) subscription management, (3) invoice generation, (4) tax calculation via Stripe Tax. "
        "Phase 1 target: end of sprint 4."
    ),
    (
        "Auth migration: (1) Add session table + endpoints [done], "
        "(2) dual-write JWT+session for 2 weeks, (3) flip default to session-only, "
        "(4) remove JWT code. Currently in phase 2."
    ),
]

# Cross-project content (from identity-service)
CROSS_PROJECT_DECISIONS = [
    (
        "Identity service uses PKCE flow for all OAuth clients. Authorization code without PKCE "
        "is rejected. Rationale: prevents authorization code interception attacks on mobile."
    ),
    (
        "User search: chose Elasticsearch over PostgreSQL full-text. Rationale: fuzzy matching, "
        "accent folding, and synonym expansion. PG tsvector insufficient for name matching."
    ),
]


# ---------------------------------------------------------------------------
# Tag helpers
# ---------------------------------------------------------------------------

def _normalize_tags(tags: list[str]) -> list[str]:
    """Canonicalize tags: lowercase, trim, dedup, sort."""
    seen = set()
    result = []
    for t in tags:
        normalized = t.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return sorted(result)


def _tags_to_json(tags: list[str]) -> str:
    """Convert normalized tags to canonical JSON string."""
    return json.dumps(_normalize_tags(tags))


def _content_hash(content: str) -> str:
    """SHA256 hash of content string."""
    return hashlib.sha256(content.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Entry factory
# ---------------------------------------------------------------------------

_UNSET = object()


def make_entry(
    content: str,
    type: str = "decision",
    tags: list[str] | None = None,
    branch: str | None = "main",
    surface: str | None = None,
    source_type: str = "manual",
    confidence: float = 0.9,
    created_at: str | None = None,
    project_id: str | None = _UNSET,
    project_name: str | None = _UNSET,
) -> dict:
    """Create a single valid entry dict.

    All fields match the knowledge table schema. Tags are normalized.
    Timestamps default to UTC now. Project defaults to mock project.
    Pass project_id=None explicitly for cross-project (global) entries.
    """
    if tags is None:
        tags = []
    if surface and surface not in tags:
        tags = [surface] + tags

    normalized_tags = _normalize_tags(tags)
    now = created_at or utc_now()

    # Resolve project defaults — _UNSET means "use mock defaults"
    resolved_project_id = MOCK_PROJECT_ID if project_id is _UNSET else project_id
    resolved_project_name = MOCK_PROJECT_NAME if project_name is _UNSET else project_name

    return {
        "id": str(uuid.uuid4()),
        "content": content,
        "content_hash": _content_hash(content),
        "type": type,
        "tags": _tags_to_json(normalized_tags),
        "project_id": resolved_project_id,
        "project_name": resolved_project_name,
        "branch": branch,
        "source_type": source_type,
        "confidence": confidence,
        "created_at": now,
        "updated_at": now,
    }


# ---------------------------------------------------------------------------
# Scenario factories
# ---------------------------------------------------------------------------

def make_restore_scenario() -> list[dict]:
    """The Restore Contract scenario (T4.1).

    Returns entries that exercise all 5 tiers:
    - 3 session_state: 2 server+feature/billing, 1 ios+main
    - 2 plan: 1 feature/billing, 1 main
    - 4 decision: 2 feature/billing, 2 main
    - 3 gotcha: 1 server, 2 ios
    - 2 pattern: no branch
    - 2 cross-project entries

    Total: 16 entries. All timestamps are deterministic.
    """
    entries = []

    # Tier 1: session_state (3 entries)
    # 2 with server surface + feature/billing branch
    entries.append(make_entry(
        content=SESSION_STATES[0],
        type="session_state",
        tags=["server", "auth", "migration"],
        branch="feature/billing-rewrite",
        surface="server",
        created_at=minutes_ago(10),
    ))
    entries.append(make_entry(
        content=SESSION_STATES[1],
        type="session_state",
        tags=["server", "webhook", "stripe"],
        branch="feature/billing-rewrite",
        surface="server",
        created_at=minutes_ago(30),
    ))
    # 1 with ios surface + main branch
    entries.append(make_entry(
        content=SESSION_STATES[2],
        type="session_state",
        tags=["ios", "keychain", "migration"],
        branch="main",
        surface="ios",
        created_at=hours_ago(2),
    ))

    # Tier 2: plan (2 entries)
    entries.append(make_entry(
        content=PLANS[0],
        type="plan",
        tags=["billing", "stripe", "migration"],
        branch="feature/billing-rewrite",
        created_at=days_ago(2),
    ))
    entries.append(make_entry(
        content=PLANS[1],
        type="plan",
        tags=["auth", "migration", "jwt"],
        branch="main",
        created_at=days_ago(5),
    ))

    # Tier 3: decision (4 entries)
    # 2 on feature/billing
    entries.append(make_entry(
        content=DECISIONS[0],
        type="decision",
        tags=["billing", "stripe", "server"],
        branch="feature/billing-rewrite",
        confidence=0.9,
        created_at=days_ago(3),
    ))
    entries.append(make_entry(
        content=DECISIONS[2],
        type="decision",
        tags=["database", "billing", "postgresql"],
        branch="feature/billing-rewrite",
        confidence=0.9,
        created_at=days_ago(4),
    ))
    # 2 on main
    entries.append(make_entry(
        content=DECISIONS[1],
        type="decision",
        tags=["auth", "jwt", "server"],
        branch="main",
        confidence=0.9,
        created_at=days_ago(7),
    ))
    entries.append(make_entry(
        content=DECISIONS[3],
        type="decision",
        tags=["api", "rate-limiting", "server"],
        branch="main",
        confidence=0.85,
        created_at=days_ago(10),
    ))

    # Tier 4: gotcha + pattern (5 entries, quota is 4 combined)
    # 1 gotcha tagged server
    entries.append(make_entry(
        content=GOTCHAS[0],
        type="gotcha",
        tags=["server", "webhook", "stripe"],
        branch="feature/billing-rewrite",
        confidence=0.9,
        created_at=days_ago(1),
    ))
    # 2 gotchas tagged ios
    entries.append(make_entry(
        content=GOTCHAS[1],
        type="gotcha",
        tags=["ios", "keychain", "security"],
        branch="main",
        confidence=0.9,
        created_at=days_ago(6),
    ))
    entries.append(make_entry(
        content=GOTCHAS[2],
        type="gotcha",
        tags=["ios", "networking", "background"],
        branch="main",
        confidence=0.8,
        created_at=days_ago(8),
    ))
    # 2 patterns (no branch preference)
    entries.append(make_entry(
        content=PATTERNS[0],
        type="pattern",
        tags=["api", "server", "architecture"],
        branch=None,
        confidence=0.9,
        created_at=days_ago(14),
    ))
    entries.append(make_entry(
        content=PATTERNS[1],
        type="pattern",
        tags=["api", "error-handling", "server"],
        branch=None,
        confidence=0.9,
        created_at=days_ago(14),
    ))

    # Tier 5: cross-project entries (2 entries from identity-service)
    entries.append(make_entry(
        content=CROSS_PROJECT_DECISIONS[0],
        type="decision",
        tags=["auth", "oauth", "security"],
        branch="main",
        project_id=SECOND_PROJECT_ID,
        project_name=SECOND_PROJECT_NAME,
        confidence=0.9,
        created_at=days_ago(20),
    ))
    entries.append(make_entry(
        content=CROSS_PROJECT_DECISIONS[1],
        type="decision",
        tags=["search", "elasticsearch"],
        branch="main",
        project_id=SECOND_PROJECT_ID,
        project_name=SECOND_PROJECT_NAME,
        confidence=0.9,
        created_at=days_ago(21),
    ))

    return entries


def make_budget_scenario() -> list[dict]:
    """Entries that exceed 2000 tokens to test budget enforcement.

    Creates 17 entries at max size per type. Total content well over
    2000 tokens (estimated at len/4). Used for T4.3 and T4.5 tests.
    """
    entries = []

    # 6 session_state entries at ~500 chars each (~125 tokens each)
    for i in range(6):
        content = (
            f"Session checkpoint {i+1}: migrating service layer {i+1} of 6. "
            "Completed refactoring of the authentication handler to use the new "
            "async middleware pattern. Updated all error responses to include "
            "request correlation IDs. Remaining work: integration tests for "
            "webhook handlers, load testing the new connection pool, and updating "
            "the deployment scripts to handle the new environment variables "
            "required by the session service."
        )[:500]
        entries.append(make_entry(
            content=content,
            type="session_state",
            tags=["server", "migration"],
            branch="feature/billing-rewrite",
            surface="server",
            created_at=minutes_ago(10 + i * 5),
        ))

    # 3 plan entries at ~800 chars
    for i in range(3):
        content = (
            f"Migration plan phase {i+1}: "
            "Step 1 — Extract service interfaces from monolith handlers into "
            "standalone service modules with dependency injection. "
            "Step 2 — Create adapter layer for backward compatibility during "
            "transition period. Step 3 — Implement new async handlers using "
            "the service interfaces. Step 4 — Run dual-write validation for "
            "two weeks to confirm parity. Step 5 — Cut over traffic to new "
            "handlers with feature flag. Step 6 — Remove legacy code paths "
            "after 30-day observation period. Rationale: incremental migration "
            "reduces risk compared to big-bang rewrite. Rejected: complete "
            "rewrite in parallel (too much coordination overhead, integration "
            "risk at cutover, team capacity insufficient for parallel streams). "
            "Constraints: must maintain backward compatibility during migration."
        )[:800]
        entries.append(make_entry(
            content=content,
            type="plan",
            tags=["migration", "architecture"],
            branch="feature/billing-rewrite",
            created_at=days_ago(i + 1),
        ))

    # 4 decision entries at ~800 chars
    for i in range(4):
        content = (
            f"Decision {i+1}: chose approach A over approach B for the "
            "payment processing pipeline. Rationale: approach A provides "
            "better fault tolerance through circuit breaker patterns and "
            "automatic retry with exponential backoff. The implementation "
            "cost is approximately 20% higher but operational cost is 40% "
            "lower due to reduced manual intervention during outages. "
            "Rejected alternatives: approach B (simpler but no fault "
            "tolerance), approach C (over-engineered for current scale). "
            "Implications: all payment handlers must implement the "
            "CircuitBreakerService interface. Retry configuration is "
            "centralized in the infrastructure layer, not per-handler. "
            "Monitoring dashboards need new circuit breaker state panels."
        )[:800]
        entries.append(make_entry(
            content=content,
            type="decision",
            tags=["payments", "architecture"],
            branch="feature/billing-rewrite",
            confidence=0.9,
            created_at=days_ago(i + 3),
        ))

    # 4 gotcha+pattern entries at ~400 chars
    for i in range(4):
        if i < 2:
            content = (
                f"Gotcha {i+1}: the connection pool does not automatically "
                "reconnect after a PostgreSQL failover. Must implement "
                "health check pings and reconnection logic in the pool "
                "manager. Without this, stale connections cause silent "
                "query failures for up to 30 seconds after failover."
            )[:400]
            entries.append(make_entry(
                content=content,
                type="gotcha",
                tags=["server", "postgresql"],
                branch="main",
                created_at=days_ago(i + 5),
            ))
        else:
            content = (
                f"Pattern {i-1}: all database migrations must be backward "
                "compatible. New columns must have defaults. Removed columns "
                "must be nullable first, then removed in a separate migration "
                "after all code references are cleaned up."
            )[:400]
            entries.append(make_entry(
                content=content,
                type="pattern",
                tags=["database", "migration"],
                branch=None,
                created_at=days_ago(i + 10),
            ))

    return entries


def make_surface_entries() -> list[dict]:
    """Entries with mixed surface tags for surface preference testing.

    Used for T6.* and T4.9 tests.
    """
    return [
        make_entry(
            content="Server-side rate limiting implemented using Redis sliding window.",
            type="decision",
            tags=["server", "rate-limiting", "redis"],
            branch="main",
            surface="server",
            created_at=days_ago(1),
        ),
        make_entry(
            content="iOS biometric auth wrapper handles Face ID and Touch ID fallback gracefully.",
            type="decision",
            tags=["ios", "auth", "biometric"],
            branch="feature/auth-migration",
            surface="ios",
            created_at=days_ago(1),
        ),
        make_entry(
            content="Web dashboard uses React Query for server state management. No Redux.",
            type="decision",
            tags=["web", "state-management", "react"],
            branch="main",
            surface="web",
            created_at=days_ago(2),
        ),
        make_entry(
            content="Android WorkManager handles background sync. Do not use AlarmManager.",
            type="gotcha",
            tags=["android", "background", "sync"],
            branch="main",
            surface="android",
            created_at=days_ago(3),
        ),
        # Entry with no surface
        make_entry(
            content="All API responses must include X-Request-ID header for tracing.",
            type="pattern",
            tags=["api", "tracing", "observability"],
            branch="main",
            created_at=days_ago(5),
        ),
    ]


def make_branch_entries() -> list[dict]:
    """Entries across branches for branch preference testing.

    Used for T4.10 and T1.7 tests.
    """
    return [
        make_entry(
            content="Feature/billing: Stripe Checkout session creation moved to server-side.",
            type="decision",
            tags=["billing", "stripe"],
            branch="feature/billing-rewrite",
            created_at=days_ago(3),
        ),
        make_entry(
            content="Main: API versioning strategy decided. URL prefix /v2/ for breaking changes.",
            type="decision",
            tags=["api", "versioning"],
            branch="main",
            created_at=days_ago(1),
        ),
        make_entry(
            content="Auth migration: TOTP 2FA implementation uses time-step of 30s with 1 step tolerance.",
            type="decision",
            tags=["auth", "2fa", "security"],
            branch="feature/auth-migration",
            created_at=days_ago(2),
        ),
        make_entry(
            content="Hotfix: webhook retry logic had off-by-one in backoff calculation. Fixed.",
            type="gotcha",
            tags=["webhook", "server"],
            branch="hotfix/webhook-race",
            created_at=hours_ago(6),
        ),
    ]


def make_dedup_entries() -> list[dict]:
    """Duplicate and near-duplicate entries for dedup testing.

    Used for T3.4, T3.6, T11.1, T11.2 tests.
    """
    content_a = "Always verify payment_intent status server-side before updating order state."

    return [
        # Exact duplicate (same content, same project)
        make_entry(
            content=content_a,
            type="gotcha",
            tags=["server", "stripe"],
            branch="main",
            created_at=days_ago(5),
        ),
        make_entry(
            content=content_a,
            type="gotcha",
            tags=["server", "stripe"],
            branch="main",
            created_at=days_ago(3),
        ),
        # Same content, different tag order (should still dedup after normalization)
        make_entry(
            content=content_a,
            type="gotcha",
            tags=["stripe", "server"],
            branch="main",
            created_at=days_ago(1),
        ),
        # Same content, different project (should NOT dedup — per-project dedup)
        make_entry(
            content=content_a,
            type="gotcha",
            tags=["server", "stripe"],
            branch="main",
            project_id=SECOND_PROJECT_ID,
            project_name=SECOND_PROJECT_NAME,
            created_at=days_ago(2),
        ),
        # Near-duplicate (slightly different content — should NOT dedup)
        make_entry(
            content="Always verify payment_intent status server-side before updating order state!",
            type="gotcha",
            tags=["server", "stripe"],
            branch="main",
            created_at=days_ago(1),
        ),
        # Cross-project NULL dedup pair
        make_entry(
            content="Universal: never log PII in error messages.",
            type="pattern",
            tags=["security", "logging"],
            branch=None,
            project_id=None,
            project_name=None,
            created_at=days_ago(10),
        ),
        make_entry(
            content="Universal: never log PII in error messages.",
            type="pattern",
            tags=["security", "logging"],
            branch=None,
            project_id=None,
            project_name=None,
            created_at=days_ago(8),
        ),
    ]


def make_cross_project_entries() -> list[dict]:
    """Entries from a second project for cross-project tier testing.

    Used for T12.1, T12.2, T4.7, T4.11 tests.
    """
    return [
        # Has overlapping tags with mock project (auth, server)
        make_entry(
            content="Identity service: SAML assertion validation must check both signature and timestamp.",
            type="gotcha",
            tags=["auth", "saml", "security"],
            branch="main",
            project_id=SECOND_PROJECT_ID,
            project_name=SECOND_PROJECT_NAME,
            created_at=days_ago(15),
        ),
        # Has overlapping tag (auth)
        make_entry(
            content="Session tokens use 256-bit entropy with CSPRNG. Never use math.random or uuid4 for tokens.",
            type="pattern",
            tags=["auth", "security", "tokens"],
            branch="main",
            project_id=SECOND_PROJECT_ID,
            project_name=SECOND_PROJECT_NAME,
            created_at=days_ago(20),
        ),
        # NO overlapping tags with mock project
        make_entry(
            content="Email service: use dedicated IP pool for transactional emails separate from marketing.",
            type="decision",
            tags=["email", "infrastructure", "deliverability"],
            branch="main",
            project_id=SECOND_PROJECT_ID,
            project_name=SECOND_PROJECT_NAME,
            created_at=days_ago(25),
        ),
    ]


def make_decay_entries() -> list[dict]:
    """Session state entries at 1h, 24h, 72h, 10d for decay testing.

    Used for T4.6 tests. The 48h window should include 1h and 24h,
    exclude 72h and 10d.
    """
    return [
        make_entry(
            content="Just finished refactoring the payment webhook handler. Next: add retry tests.",
            type="session_state",
            tags=["server", "webhook"],
            branch="feature/billing-rewrite",
            surface="server",
            created_at=hours_ago(1),
        ),
        make_entry(
            content="Completed Stripe test mode integration. All sandbox tests pass. Moving to live key rotation.",
            type="session_state",
            tags=["server", "stripe", "testing"],
            branch="feature/billing-rewrite",
            surface="server",
            created_at=hours_ago(24),
        ),
        make_entry(
            content="Finished auth token rotation implementation. Need to test edge case with expired refresh.",
            type="session_state",
            tags=["server", "auth"],
            branch="feature/auth-migration",
            surface="server",
            created_at=hours_ago(72),
        ),
        make_entry(
            content="Initial project setup complete. Repository configured, CI pipeline running.",
            type="session_state",
            tags=["setup", "ci"],
            branch="main",
            created_at=hours_ago(240),  # 10 days
        ),
    ]