"""Unit tension (LISCOP legend) and the HET decision aid."""

from __future__ import annotations

from services.admissions_smr.domain import ror
from services.admissions_smr.domain.tension import (
    HetInputs,
    HetThresholds,
    het_aid,
    tension_of,
)


def calm(**changes: object) -> HetInputs:
    values: dict[str, object] = {
        "boarding_10h": 0,
        "waiting_bed": 2,
        "longest_wait_hours": 3.0,
        "critical_units": 0,
        "mco_units": 6,
    }
    values.update(changes)
    return HetInputs(**values)  # type: ignore[arg-type]


def test_liscop_legend_boundaries() -> None:
    assert tension_of(2, 10).level == "normal"  # exactly 20 %
    assert tension_of(1, 10).level == "tension"
    assert tension_of(0, 10).level == "critique"
    assert tension_of(0, 0).level == "normal"


def test_ror_module_uses_the_same_legend() -> None:
    assert ror.tension_of is tension_of


def test_no_criterion_met_means_no_signal() -> None:
    aid = het_aid(calm())

    assert aid.level == "aucun"
    assert aid.triggered == []


def test_one_criterion_means_vigilance_with_its_value_and_threshold() -> None:
    aid = het_aid(calm(boarding_10h=5))

    assert aid.level == "vigilance"
    [only] = aid.triggered
    assert (only.code, only.value, only.threshold) == ("boarding_10h", 5, 5)


def test_two_criteria_suggest_a_het_declaration() -> None:
    aid = het_aid(calm(boarding_10h=7, critical_units=2, mco_units=6))

    assert aid.level == "het_suggere"
    assert {c.code for c in aid.triggered} == {"boarding_10h", "critical_units_share"}


def test_thresholds_are_configurable() -> None:
    aid = het_aid(calm(waiting_bed=4), HetThresholds(waiting_bed=4))

    assert [c.code for c in aid.triggered] == ["waiting_bed"]


def test_unknown_values_never_trigger() -> None:
    aid = het_aid(calm(longest_wait_hours=None, mco_units=0))

    unknown = {c.code: c for c in aid.criteria}
    assert unknown["longest_wait_hours"].value is None
    assert unknown["critical_units_share"].value is None
    assert aid.level == "aucun"
