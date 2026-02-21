"""Knowledge retrieval — the read path."""

import sqlite3


def retrieve_context(
    conn: sqlite3.Connection,
    project_id: str,
    branch: str | None = None,
    surface: str | None = None,
    query: str | None = None,
    include_session_state: bool = True,
) -> "RestoreResult":
    """Retrieve relevant knowledge for the current project.

    Two modes:
    - Restore mode (query is None/empty): deterministic 5-tier state reconstruction
    - Search mode (query provided): FTS5 keyword search ranked by relevance

    Returns RestoreResult with .entries, .rendered, .total_tokens.
    """
    from momento.models import RestoreResult  # noqa: F811
    raise NotImplementedError("retrieve.retrieve_context")
