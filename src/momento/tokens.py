"""Token estimation utilities."""


def estimate_tokens(text: str) -> int:
    """Estimate token count for rendered markdown text.

    Uses len(text) / 4 approximation. Includes headers, metadata
    brackets, markdown scaffolding, and blank lines.

    The 2000-token cap is a budget, not a precision target.
    """
    return len(text) // 4
