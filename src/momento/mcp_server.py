# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Momento MCP server — exposes retrieve_context and log_knowledge tools."""

import json
import os

from mcp.server.fastmcp import FastMCP

from momento import db, identity, retrieve, store, surface

server = FastMCP("momento")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db_path() -> str:
    return os.environ.get("MOMENTO_DB", os.path.expanduser("~/.momento/knowledge.db"))


def _resolve_env(cwd: str) -> dict:
    """Resolve project identity, branch, and surface from cwd."""
    project_id, project_name = identity.resolve_project_id(cwd)
    branch = identity.resolve_branch(cwd)
    sfc = surface.detect_surface(cwd)
    return {
        "project_id": project_id,
        "project_name": project_name,
        "branch": branch,
        "surface": sfc,
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@server.tool(
    description=(
        "Retrieve relevant knowledge for the current project. "
        "Two modes: (1) Restore mode (empty query): deterministic 5-tier state reconstruction "
        "returning session checkpoints, plans, decisions, gotchas, patterns, and cross-project entries. "
        "(2) Search mode (query provided): FTS5 keyword search ranked by BM25 relevance, "
        "no tier ordering. Call restore mode after /clear, at session start, or after context overflow. "
        "Call search mode when looking for specific knowledge."
    ),
)
def retrieve_context(query: str = "", include_session_state: bool = True) -> str:
    cwd = os.getcwd()
    env = _resolve_env(cwd)
    conn = db.ensure_db(_db_path())
    try:
        result = retrieve.retrieve_context(
            conn=conn,
            project_id=env["project_id"],
            branch=env["branch"],
            surface=env["surface"],
            query=query or None,
            include_session_state=include_session_state,
        )
        return result.rendered
    finally:
        conn.close()


@server.tool(
    description=(
        "Store a knowledge entry. Use for recording decisions, gotchas, patterns, "
        "or current task progress. When the user says 'checkpoint' or 'save progress', "
        "call this with type='session_state'."
    ),
)
def log_knowledge(content: str, type: str, tags: list[str]) -> str:
    cwd = os.getcwd()
    env = _resolve_env(cwd)
    conn = db.ensure_db(_db_path())
    try:
        result = store.log_knowledge(
            conn=conn,
            content=content,
            type=type,
            tags=tags,
            project_id=env["project_id"],
            project_name=env["project_name"],
            branch=env["branch"],
            source_type="manual",
            confidence=0.9,
            enforce_limits=True,
        )
        return json.dumps(result)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    server.run()