"""Tests for Hospitalos dashboard microcopy quality."""

from __future__ import annotations

from typing import get_type_hints

from dashboards import microcopy


def string_constants() -> dict[str, str]:
    """Return public string constants from the microcopy module."""
    return {
        name: value
        for name, value in vars(microcopy).items()
        if name.isupper() and isinstance(value, str)
    }


def test_all_microcopy_constants_are_strings() -> None:
    """Every exported microcopy constant is a clean non-empty string."""
    hints = get_type_hints(microcopy)
    constants = string_constants()
    assert constants
    for name, value in constants.items():
        assert name in hints
        assert isinstance(value, str)
        assert value.strip() == value
        assert value


def test_microcopy_no_english_filler_words() -> None:
    """Forbidden filler words are absent from all microcopy strings."""
    forbidden = ("Submit", "Loading", "Error", "Failed", "Oops")
    for value in string_constants().values():
        assert not any(word in value for word in forbidden)


def test_microcopy_synthesis_template_has_required_placeholders() -> None:
    """Forecast synthesis template exposes all required placeholders."""
    template = microcopy.FCT_SYNTHESIS_TEMPLATE
    for placeholder in (
        "{peak_hours}",
        "{peak_value}",
        "{lower}",
        "{upper}",
        "{critical_count}",
        "{plural}",
        "{margin}",
    ):
        assert placeholder in template


def test_microcopy_simulation_summary_template_has_required_placeholders() -> None:
    """Simulation summary template exposes all required placeholders."""
    template = microcopy.SIM_SUMMARY_TEMPLATE
    for placeholder in ("{direction}", "{delta_pct}", "{critical_change}"):
        assert placeholder in template


def test_microcopy_constants_use_french_quotes_when_quoting() -> None:
    """Quoted expressions use French guillemets unless the string is code-like."""
    code_markers = ("uvicorn", "http://", "PYTHONPATH", "streamlit", "artifacts/")
    for value in string_constants().values():
        if any(marker in value for marker in code_markers):
            continue
        assert '"' not in value
