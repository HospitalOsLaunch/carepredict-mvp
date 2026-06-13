"""Tests for Hospitalos dashboard glossary helpers."""

from __future__ import annotations

from dashboards.glossary import GLOSSARY, get_definition, render_term, term_tooltip


def test_glossary_has_minimum_terms() -> None:
    """The glossary covers the main user-facing terms."""
    assert len(GLOSSARY) >= 8


def test_glossary_definitions_are_complete_sentences() -> None:
    """Definitions are complete and explanatory enough for tooltips."""
    for definition in GLOSSARY.values():
        assert definition.endswith(".")
        assert len(definition.split()) >= 5


def test_get_definition_known() -> None:
    """Known terms return a definition."""
    definition = get_definition("SIIPS")
    assert definition is not None
    assert definition


def test_get_definition_unknown_returns_none() -> None:
    """Unknown terms return None."""
    assert get_definition("ZZZ") is None


def test_term_tooltip_passthrough() -> None:
    """Unknown terms pass through unchanged."""
    assert term_tooltip("ZZZ") == "ZZZ"


def test_render_term_contains_term_and_tooltip() -> None:
    """Rendered terms include the term and definition in a title attribute."""
    html = render_term("SIIPS")
    assert "SIIPS" in html
    assert 'title="' in html
    assert GLOSSARY["SIIPS"] in html
