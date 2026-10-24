"""Hand oracles for censoring/time boundaries and learned-duration integration."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from hospitalos.hybrid.demo import pathway_request
from hospitalos.hybrid.learning_demo import protocol, train_demo
from hospitalos.hybrid.models import Action
from hospitalos.hybrid.planning import PlanRequest, plan
from hospitalos.hybrid.preparation import (
    PreparationCurve,
    PreparationFeatures,
    PreparationForecasts,
    preparation_draw,
)
from hospitalos.hybrid.scoring import score
from hospitalos.hybrid.simulation import simulate
from hospitalos.hybrid.survival import (
    CensoringDistribution,
    Partitions,
    PreparationRecord,
    Selection,
    TemporalProtocol,
    brier_at,
    censored_nll,
    evaluate,
    fit_candidates,
    fit_censoring,
    forecast_preparation,
    observed_cells,
    partition,
    select_model,
    survival_curve,
)
from services.api.hybrid_app import app


def record(minutes: int, observed: bool, *, name: str = "one") -> PreparationRecord:
    at = protocol().train.start
    return PreparationRecord(
        episode_id=name,
        patient_id=name,
        hospital_id="fictional-hospital",
        unit_id="medicine",
        origin=at,
        features_available_at=at,
        features=PreparationFeatures(
            occupied_per_staffed_bed=1,
            waiting_per_staffed_bed=1,
            hour_utc=at.hour,
            weekday_utc=at.weekday(),
        ),
        followed_minutes=minutes,
        event_observed=observed,
        label_available_at=at + timedelta(days=1),
    )


@pytest.fixture(scope="module")
def fitted() -> tuple[Selection, Partitions]:
    return train_demo()


@pytest.mark.parametrize(
    "minutes,observed,expected",
    [
        (1, False, ()),
        (30, False, ((0, 0),)),
        (59, False, ((0, 0),)),
        (30, True, ((0, 1),)),
        (31, True, ((0, 0), (1, 1))),
        (60, True, ((0, 0), (1, 1))),
        (1440, False, tuple((i, 0) for i in range(6))),
    ],
)
def test_censoring_contributes_only_observed_intervals(
    minutes: int, observed: bool, expected: tuple[tuple[int, int], ...]
) -> None:
    assert observed_cells(record(minutes, observed)) == expected


def test_likelihood_matches_hand_calculation_without_fabricated_event() -> None:
    records = (record(31, True), record(59, False, name="two"))
    hazards = ((0.2,) * 6,) * 2
    assert censored_nll(records, hazards) == pytest.approx(-math.log(0.8 * 0.2 * 0.8) / 2)
    assert survival_curve((0.2, 0.5)) == pytest.approx((0.8, 0.4))


def test_pooled_hazard_uses_risk_sets_including_late_censoring() -> None:
    records = (record(30, True), record(1440, False, name="two"))
    baseline, _ = fit_candidates(records, protocol().train.labels_available_by)
    assert baseline.pooled == pytest.approx((0.5, 0.25, 0.25, 0.25, 0.25, 0.25))


@pytest.mark.parametrize("field", ["features_available_at", "label_available_at", "target"])
def test_training_record_rejects_future_features_premature_labels_or_wrong_target(
    field: str,
) -> None:
    r = record(120, True)
    changes: dict[str, Any] = {
        "features_available_at": r.origin + timedelta(minutes=1),
        "label_available_at": r.origin,
        "target": "total_remaining_length_of_stay",
    }
    with pytest.raises(ValidationError):
        PreparationRecord.model_validate({**r.model_dump(), field: changes[field]})


def test_temporal_embargo_cannot_overlap_next_window() -> None:
    split = protocol().model_dump()
    split["calibration"]["start"] = protocol().train.end
    with pytest.raises(ValidationError, match="embargoes overlap"):
        TemporalProtocol.model_validate(split)


@pytest.mark.parametrize("fault", ["duplicate_patient", "late_label", "outside_window"])
def test_partition_rejects_patient_overlap_and_unavailable_information(
    fitted: tuple[Selection, Partitions], fault: str
) -> None:
    _, data = fitted
    r = data.test[0]
    changes: dict[str, Any] = {
        "duplicate_patient": {"patient_id": data.train[0].patient_id},
        "late_label": {
            "label_available_at": protocol().test.labels_available_by + timedelta(days=1)
        },
        "outside_window": {"origin": protocol().test.end},
    }
    # model_copy permits intentionally malformed objects to exercise partition defenses.
    altered = r.model_copy(update=changes[fault])
    with pytest.raises(ValueError):
        partition(
            data.train + data.calibration + data.validation + (altered,) + data.test[1:], protocol()
        )


def test_selector_rejects_swapped_partitions_without_reading_test(
    fitted: tuple[Selection, Partitions],
) -> None:
    _, data = fitted
    with pytest.raises(ValueError, match="selection partition"):
        select_model(data.calibration, data.train, data.validation, protocol())


def test_test_outcomes_and_input_order_do_not_change_selection(
    fitted: tuple[Selection, Partitions],
) -> None:
    original, data = fitted
    changed_test = tuple(
        r.model_copy(update={"event_observed": not r.event_observed}) for r in data.test
    )
    changed = partition(data.train + data.calibration + data.validation + changed_test, protocol())
    again = select_model(
        tuple(reversed(changed.train)), changed.calibration, changed.validation, protocol()
    )
    assert again.selected.model_id == original.selected.model_id
    features = (data.test[0].features,)
    assert again.selected.hazards(features) == original.selected.hazards(features)
    assert again.selected.available_at == protocol().validation.labels_available_by


def test_locked_model_cannot_be_evaluated_before_availability(
    fitted: tuple[Selection, Partitions],
) -> None:
    selection, data = fitted
    with pytest.raises(ValueError, match="unavailable at origin"):
        evaluate(selection.selected, data.train, selection.censoring)


def test_selection_requires_informative_followup(fitted: tuple[Selection, Partitions]) -> None:
    _, data = fitted
    no_information = tuple(
        r.model_copy(update={"followed_minutes": 1, "event_observed": False})
        for r in data.validation
    )
    with pytest.raises(ValueError, match="observed interval information"):
        select_model(data.train, data.calibration, no_information, protocol())


def test_reverse_km_and_ipcw_match_manual_calculation() -> None:
    # At 40 one of three survivors is censored. G(60)=2/3.
    train = (
        record(30, True),
        record(40, False, name="b"),
        record(90, True, name="c"),
        record(120, False, name="d"),
    )
    censoring = fit_censoring(train)
    assert censoring.survival(40, before=True) == 1
    assert censoring.survival(60) == pytest.approx(2 / 3)
    evaluation = (record(30, True), record(40, False, name="b"), record(90, True, name="c"))
    result = brier_at(evaluation, (0.2, 0.5, 0.8), 60, censoring)
    assert result["brier_ipcw"] == pytest.approx((0.2**2 + 0.2**2 / (2 / 3)) / 3)
    assert result["observed_event_rate_ipcw"] == pytest.approx(1 / 3)


def test_brier_without_censoring_is_ordinary_brier_score() -> None:
    records = (record(30, True), record(120, True, name="b"))
    result = brier_at(records, (0.2, 0.7), 60, CensoringDistribution((), 1440))
    assert result["brier_ipcw"] == pytest.approx((0.04 + 0.09) / 2)


@pytest.mark.parametrize(
    "censoring", [CensoringDistribution((), 30), CensoringDistribution(((30, 0.05),), 1440)]
)
def test_unsupported_ipcw_horizon_is_reported_not_clipped(censoring: CensoringDistribution) -> None:
    result = brier_at((record(120, False),), (0.5,), 60, censoring)
    assert result["brier_ipcw"] is None
    assert result["reason"] == "insufficient_censoring_support"


def bundle(request: PlanRequest, *, tail: bool = False) -> PreparationForecasts:
    state = request.state()
    return PreparationForecasts(
        model_id="a" * 64,
        hospital_id=state.hospital_id,
        state_fingerprint=state.fingerprint,
        origin=state.at,
        model_available_at=state.at - timedelta(days=1),
        curves=(
            PreparationCurve(
                patient_id="outgoing",
                mass=(0, 0, 1, 0, 0, 0) if not tail else (0,) * 6,
                beyond_24h=float(tail),
            ),
        ),
    )


def test_tail_probability_never_forces_departure_within_24h() -> None:
    request = pathway_request()
    forecasts = bundle(request, tail=True)
    curve = forecasts.curves[0]
    assert curve.quantile(0.9) is None
    assert preparation_draw(curve, 7, 0) is None
    trace = simulate(
        request.state(),
        Action(kind="request_transport", patient_id="outgoing", bed_id="bed-1"),
        request.assumptions,
        seed=7,
        scenario=0,
        preparation=forecasts,
    )
    assert not any(e.kind == "depart" for e in trace.events)
    assert score(request.state(), trace).violations == ()


def test_learned_delay_is_not_multiplied_by_shared_load_and_resources_are_still_scored() -> None:
    request = pathway_request()
    trace = simulate(
        request.state(),
        Action(kind="request_transport", patient_id="outgoing", bed_id="bed-1"),
        request.assumptions.model_copy(update={"load_multipliers": (2,)}),
        seed=7,
        scenario=0,
        preparation=bundle(request),
    )
    assert next(e.minute for e in trace.events if e.kind == "departure_ready") == 120
    assert next(e.minute for e in trace.events if e.kind == "depart") == 210  # 120 + 2*45 transport
    assert next(e.minute for e in trace.events if e.kind == "admit") == 270  # +2*30 cleaning
    assert score(request.state(), trace).violations == ()


def test_plan_identity_and_persisted_inputs_include_distribution() -> None:
    request = pathway_request()
    learned = PlanRequest.model_validate({**request.model_dump(), "preparation": bundle(request)})
    proposal = plan(learned)
    assert proposal.plan_id != plan(request).plan_id
    assert proposal.preparation == learned.preparation
    assert proposal.schema_version == "HYBRID_PLAN_4"
    assert proposal.selected.kind == "request_transport"
    assert "synthetic_learned_preparation_requires_real_validation" in proposal.warnings


def test_forecast_is_normalized_and_refuses_unknown_site_or_load(
    fitted: tuple[Selection, Partitions],
) -> None:
    selection, _ = fitted
    state = pathway_request().state()
    forecasts = forecast_preparation(selection.selected, state)
    assert [c.patient_id for c in forecasts.curves] == ["outgoing"]
    assert sum(forecasts.curves[0].mass) + forecasts.curves[0].beyond_24h == pytest.approx(1)
    with pytest.raises(ValueError, match="site/unit or load"):
        forecast_preparation(replace(selection.selected, sites_units=frozenset()), state)
    with pytest.raises(ValueError, match="site/unit or load"):
        forecast_preparation(
            replace(selection.selected, feature_bounds=((0, 0.5), (0, 0.5))), state
        )
    with pytest.raises(ValueError, match="not available"):
        forecast_preparation(
            replace(selection.selected, available_at=state.at + timedelta(minutes=1)), state
        )


@pytest.mark.parametrize(
    "fault",
    ["mass", "patient", "fingerprint", "future_model", "origin", "hospital", "medical_clearance"],
)
def test_api_rejects_unusable_forecast_and_never_infers_clearance(fault: str) -> None:
    request = pathway_request()
    forecasts = bundle(request).model_dump(mode="json")
    payload = request.model_dump(mode="json")
    if fault == "mass":
        forecasts["curves"][0]["beyond_24h"] = 0.5
    elif fault == "patient":
        forecasts["curves"][0]["patient_id"] = "incoming"
    elif fault == "fingerprint":
        forecasts["state_fingerprint"] = "b" * 64
    elif fault == "future_model":
        forecasts["model_available_at"] = (request.at + timedelta(minutes=1)).isoformat()
    elif fault == "origin":
        forecasts["origin"] = (request.at + timedelta(minutes=1)).isoformat()
    elif fault == "hospital":
        forecasts["hospital_id"] = "another-hospital"
    else:
        for event in payload["events"]:
            if event["fact"]["kind"] == "patient" and event["fact"]["id"] == "outgoing":
                event["fact"]["medically_cleared"] = False
        # Bind to the new state too: the eligible-patient check must still reject it.
        forecasts["state_fingerprint"] = PlanRequest.model_validate(payload).state().fingerprint
    payload["preparation"] = forecasts
    with TestClient(app) as client:
        response = client.post("/hybrid/plan", json=payload)
    assert response.status_code == 422


def test_api_accepts_valid_json_distribution_without_estimator_payload() -> None:
    request = pathway_request()
    payload = {
        **request.model_dump(mode="json"),
        "preparation": bundle(request).model_dump(mode="json"),
    }
    with TestClient(app) as client:
        response = client.post("/hybrid/plan", json=payload)
    assert response.status_code == 200
    assert response.json()["preparation"]["model_id"] == "a" * 64
