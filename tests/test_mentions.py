"""Unit-tests voor @handle-parsing."""

from __future__ import annotations

from betonning import mentions


def test_single_mention():
    assert mentions.parse("hoi @person kijk hier") == ["person"]


def test_mention_at_start():
    assert mentions.parse("@claude doe dit") == ["claude"]


def test_multiple_unique_in_order():
    assert mentions.parse("@person @claude @person") == ["person", "claude"]


def test_handles_with_hyphen_and_digits():
    assert mentions.parse("@hermes-01 en @bot2") == ["hermes-01", "bot2"]


def test_email_is_not_a_mention():
    assert mentions.parse("mail person@gmail.com") == []


def test_empty_and_none():
    assert mentions.parse("") == []
    assert mentions.parse(None) == []


def test_no_mentions():
    assert mentions.parse("gewoon tekst zonder") == []
