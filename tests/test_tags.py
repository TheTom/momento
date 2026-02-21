"""Unit tests for tag normalization helpers."""

from momento.tags import normalize_tags, tags_to_json


def test_normalize_tags_dedups_sorts_and_ignores_blanks():
    tags = [" Auth ", "ios", "auth", "  ", "", "SERVER"]
    assert normalize_tags(tags) == ["auth", "ios", "server"]


def test_tags_to_json_uses_canonical_order():
    assert tags_to_json(["stripe", "auth", "stripe"]) == '["auth", "stripe"]'

