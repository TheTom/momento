"""Project identity resolution from git and filesystem."""


def resolve_project_id(working_dir: str) -> tuple[str, str]:
    """Resolve project identity from working directory.

    Resolution order:
    1. hash(git remote.origin.url) — survives folder moves
    2. hash(git --git-common-dir) — no remote, local git root
    3. hash(absolute working directory) — not a git repo

    Returns (project_id, human_name).
    """
    raise NotImplementedError("identity.resolve_project_id")


def resolve_branch(working_dir: str) -> str | None:
    """Resolve current git branch.

    Returns branch name string, or None for detached HEAD / non-git.
    Branch names are case-sensitive — never lowercased.
    """
    raise NotImplementedError("identity.resolve_branch")
