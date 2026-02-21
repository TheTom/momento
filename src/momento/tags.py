# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Tag normalization utilities."""

import json


def normalize_tags(tags: list[str]) -> list[str]:
    """Canonicalize tags: lowercase, trim, dedup, sort alphabetically.

    Example: [" Auth ", "iOS", "auth"] -> ["auth", "ios"]
    """
    seen = set()
    result = []
    for t in tags:
        normalized = t.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return sorted(result)


def tags_to_json(tags: list[str]) -> str:
    """Convert normalized tag list to canonical JSON string.

    Tags must be normalized first. Returns sorted JSON array string.
    """
    return json.dumps(normalize_tags(tags))