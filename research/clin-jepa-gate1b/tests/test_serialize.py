"""Tests for deterministic stay serialization with provenance-based leak guards."""

from __future__ import annotations

import pytest

from loaders.serialize import (
    SerializationLeakError,
    serialize_fluent,
    serialize_structured,
    serialized_field_names,
)
from loaders.sparcs_adapter import APR_FEATURES, LEAK_PRONE_COLUMNS


SERIALIZERS = (serialize_structured, serialize_fluent)


def _row() -> dict[str, object]:
    return {
        "age_group": "70 or Older",
        "gender": "F",
        "type_admission": "Emergency",
        "ed_indicator": "Y",
        "apr_drg": "Heart Failure",
        "apr_medsurg": "Medical",
        "ccsr_diagnosis": "Rehabilitation care",
        "health_service_area": "New York City",
        "payment_typology": "Home Plan Advantage",
        "apr_severity": "Major",
        "apr_risk_mortality": "Moderate",
        "length_of_stay": 987654321,
        "total_charges": 876543210.99,
        "total_costs": 765432109.88,
        "Patient Disposition": "Skilled Nursing Home",
        "target_disposition": "aval_institu",
        "mapped_class": "aval_institu",
    }


@pytest.mark.parametrize("serializer", SERIALIZERS)
def test_present_drg_and_admission_are_serialized_conditionally(serializer) -> None:
    text = serializer(_row())

    assert "Heart Failure" in text
    assert "Emergency" in text


@pytest.mark.parametrize("serializer", SERIALIZERS)
def test_absent_drg_and_unknown_fields_are_omitted_cleanly(serializer) -> None:
    row = _row()
    row["apr_drg"] = "Unknown"
    row["type_admission"] = ""

    text = serializer(row)

    assert "Heart Failure" not in text
    assert "Unknown" not in text
    assert "Admission: ." not in text
    assert "admission type was ." not in text


@pytest.mark.parametrize("serializer", SERIALIZERS)
def test_post_stay_values_never_appear(serializer) -> None:
    text = serializer(_row())

    assert "987654321" not in text
    assert "876543210.99" not in text
    assert "765432109.88" not in text


@pytest.mark.parametrize("serializer", SERIALIZERS)
def test_target_value_is_excluded_by_provenance_not_clinical_substrings(serializer) -> None:
    row = _row()
    text = serializer(row)

    assert row["Patient Disposition"] not in text
    assert "Rehabilitation care" in text
    assert "Home Plan Advantage" in text


def test_target_provenance_guard_raises_on_exact_value_collision() -> None:
    row = _row()
    row["payment_typology"] = row["Patient Disposition"]

    with pytest.raises(SerializationLeakError, match="Patient Disposition"):
        serialize_structured(row)


def test_target_and_leak_columns_are_absent_from_serialization_contract() -> None:
    target_columns = {
        name for name, reason in LEAK_PRONE_COLUMNS.items() if "target" in reason
    }
    for include_apr in (False, True):
        fields = set(serialized_field_names(include_apr=include_apr))
        assert fields.isdisjoint(target_columns)
        assert fields.isdisjoint({"length_of_stay", "total_charges", "total_costs"})


@pytest.mark.parametrize("serializer", SERIALIZERS)
def test_apr_fields_are_excluded_by_default_and_included_only_on_opt_in(serializer) -> None:
    no_apr = serializer(_row())
    with_apr = serializer(_row(), include_apr=True)

    assert "Severity" not in no_apr
    assert "Mortality risk" not in no_apr
    assert "Major" not in no_apr
    assert "Moderate" not in no_apr
    assert "Major" in with_apr
    assert "Moderate" in with_apr
    assert set(APR_FEATURES).issubset(serialized_field_names(include_apr=True))


def test_structured_serialization_is_exact_and_deterministic() -> None:
    expected = (
        "Inpatient admission. Age: 70 or Older. Sex: F. Admission: Emergency. ED: Y. "
        "Diagnosis group: Heart Failure. Med/Surg: Medical. "
        "Clinical category: Rehabilitation care. Region: New York City. "
        "Payer: Home Plan Advantage."
    )

    assert serialize_structured(_row()) == expected
    assert serialize_structured(_row()) == serialize_structured(_row())


def test_fluent_serialization_is_exact_and_deterministic() -> None:
    expected = (
        "This is an inpatient admission. The age group was 70 or Older. "
        "The recorded sex was F. The admission type was Emergency. "
        "The emergency department indicator was Y. The diagnosis group was Heart Failure. "
        "The medical or surgical class was Medical. "
        "The clinical category was Rehabilitation care. "
        "The hospital region was New York City. The payer category was Home Plan Advantage."
    )

    assert serialize_fluent(_row()) == expected
    assert serialize_fluent(_row()) == serialize_fluent(_row())
