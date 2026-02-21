"""Tag normalization utilities."""


def normalize_tags(tags: list[str]) -> list[str]:
    """Canonicalize tags: lowercase, trim, dedup, sort alphabetically.

    Example: [" Auth ", "iOS", "auth"] -> ["auth", "ios"]
    """
    raise NotImplementedError("tags.normalize_tags")


def tags_to_json(tags: list[str]) -> str:
    """Convert normalized tag list to canonical JSON string.

    Tags must be normalized first. Returns sorted JSON array string.
    """
    raise NotImplementedError("tags.tags_to_json")
