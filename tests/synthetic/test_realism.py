"""Independent arithmetic fixtures, censoring, malformed input and reserved-test guards."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from hospitalos.synthetic.config import HospitalConfig
from hospitalos.synthetic.generate import generate
from hospitalos.synthetic.realism import (
    HOURLY,
    load_references,
    measure,
    publish,
    reconstruct,
    score_run,
)


def config(**changes: Any) -> HospitalConfig:
    return HospitalConfig.model_validate(
        {
            "hospital_id": "H",
            "seed": 41,
            "start": "2026-02-28",
            "days": 1,
            "warmup_days": 2,
            "partition": "development",
            "poles": [
                {
                    "pole_id": "P",
                    "units": [
                        {
                            "unit_id": u,
                            "template": "CSG",
                            "beds": 4,
                            "isolation_beds": 1,
                            "oxygen_beds": 2,
                        }
                        for u in ("U_A", "U_B")
                    ],
                }
            ],
            **changes,
        }
    )


def event(hour: int, kind: str, sid: str, unit: str = "U_A", **payload: Any) -> dict[str, Any]:
    return {
        "h": hour,
        "hospital_id": "H",
        "unit_id": unit,
        "type": kind,
        "stay_id": "H:" + sid,
        "payload": payload,
    }


def fixture() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # A crosses the left boundary and changes unit; B crosses the right boundary.
    # C is redirected without admission; D is still waiting at the right boundary.
    events = [
        event(-42, "DEMANDE_ADMISSION", "A", mode_entree="urgences", age=80),
        event(-40, "ADMISSION", "A", attente_h=2),
        event(-30, "SORTANT_MEDICAL", "A"),
        event(1, "DEMANDE_ADMISSION", "B", mode_entree="urgences", age=60),
        event(2, "ADMISSION", "B", attente_h=1),
        event(3, "TRANSFERT_INTERNE", "A", "U_B", depuis="U_A"),
        event(4, "DEMANDE_ADMISSION", "C", mode_entree="urgences", age=90),
        event(6, "SORTIE", "A", "U_B", destination="SMR"),
        event(10, "DEMANDE_ADMISSION", "D", mode_entree="urgences", age=75),
        event(12, "ORIENTATION_HORS_PERIMETRE", "C", attente_h=8),
        event(20, "SORTANT_MEDICAL", "B"),
    ]
    rows = []
    for h in range(24):
        for u in ("U_A", "U_B"):
            a = int(h < 3) if u == "U_A" else int(3 <= h < 6)
            b = int(h >= 2) if u == "U_A" else 0
            ready = a + int(u == "U_A" and h >= 20)
            q = int(h == 1) + int(4 <= h < 12) + int(h >= 10) if u == "U_A" else 0
            rows.append(
                {
                    **dict.fromkeys(HOURLY, 0),
                    "hospital_id": "H",
                    "pole_id": "P",
                    "unit_id": u,
                    "h": h,
                    "lits_physiques": 4,
                    "lits_ouverts": 4,
                    "lits_occupes": a + b,
                    "attente_urgences_nb": q,
                    "sortants_medicaux_presents": ready,
                    "en_attente_aval": a,
                    "patients_heberges_presents": int(u == "U_B") * a,
                    "soignants_prevus": 2,
                    "soignants_presents": 3,
                    "ide_presents": 1,
                }
            )
    return events, rows


def test_window_integrates_both_boundaries_and_transfer_segments() -> None:
    events, rows = fixture()
    report = measure(config(), events, rows)
    h = report["entities"]["H"]["hourly"]
    assert h["occupied_bed_hours"] == 28  # A: 6 hours; B: 22 hours.
    assert h["first_ready_present_hours"] == 10
    assert h["first_ready_beyond_24h_present_hours"] == 6
    assert h["first_ready_beyond_24h_bed_hours_share"] == pytest.approx(6 / 28)
    assert report["entities"]["U_A"]["hourly"]["occupied_bed_hours"] == 25
    assert report["entities"]["U_B"]["hourly"]["occupied_bed_hours"] == 3
    assert h["occupancy_open_capacity_weighted"] == pytest.approx(28 / 192)
    stays = report["stays"]
    assert stays["admissions_in_window"] == stays["discharges_in_window"] == 1
    assert stays["prewindow_admissions_discharged_in_window"] == 1
    assert stays["admissions_in_window_still_present_at_end"] == 1
    assert stays["hospital_los_days_discharges_in_window"]["mean"] == pytest.approx(46 / 24)
    assert stays["hospital_los_days_admitted_and_discharged_in_window"]["mean"] is None
    assert stays["first_ready_to_end_h_censored_lower_bounds"]["n"] == 1
    assert stays["first_ready_to_end_h_censored_lower_bounds"]["mean"] == 4


def test_nonadmitted_requests_are_not_silently_dropped() -> None:
    events, rows = fixture()
    r = measure(config(), events, rows)["entities"]["H"]
    ed = r["ed_by_requested_unit"]
    assert ed["request_cohort_n"] == 3
    assert ed["admitted_n"] == 1
    assert ed["nonadmitted_terminal_outcomes"] == {"ORIENTATION_HORS_PERIMETRE": 1}
    assert ed["pending_at_end_n"] == 1
    assert ed["nonadmitted_terminal_wait_h"]["mean"] == 8
    assert ed["pending_wait_h_censored_lower_bounds"]["mean"] == 14
    assert r["hourly"]["ed_queue_patient_hours"] == 23


def test_requested_and_actual_admission_units_are_separate() -> None:
    events, rows = fixture()
    events[3]["unit_id"] = "U_B"  # B requests U_B but is hosted in U_A.
    for row in rows:
        if row["h"] == 1:
            row["attente_urgences_nb"] = int(row["unit_id"] == "U_B")
    report = measure(config(), events, rows)
    assert report["entities"]["U_B"]["admissions_by_requested_unit"] == 1
    assert report["entities"]["U_B"]["admissions_by_actual_admission_unit"] == 0
    assert report["entities"]["U_A"]["admissions_by_actual_admission_unit"] == 1


def test_calendar_comes_from_config_and_spans_leap_day() -> None:
    events, rows = fixture()
    r = measure(config(), events, rows)
    assert r["discharge_weekday_counts"] == {"5": 1}  # 28 February 2026 is Saturday.
    assert r["window"]["end_exclusive"] == "2026-03-01"
    assert set(r["entities"]["H"]["hourly"]["monthly"]) == {"2026-02"}
    r = measure(config(start="2024-02-28"), events, rows)
    assert r["window"]["end_exclusive"] == "2024-02-29"
    assert r["discharge_weekday_counts"] == {"2": 1}


def test_net_staff_surplus_does_not_become_gross_absenteeism() -> None:
    events, rows = fixture()
    h = measure(config(), events, rows)["entities"]["H"]["hourly"]
    assert h["gross_absenteeism"] is None
    assert h["net_staff_deficit_signed_share"] == -0.5
    assert h["staff_hours_above_plan"] == 48
    assert h["staff_hours_below_plan"] == 0
    assert h["coordination_minutes"] is None
    assert h["capacity_caused_downstream_blocked_hours"] is None


def test_empty_population_and_zero_denominators_emit_strict_json_nulls() -> None:
    _, rows = fixture()
    for row in rows:
        row.update(dict.fromkeys(HOURLY, 0))
    r = measure(config(), [], rows)
    assert r["stays"]["hospital_los_days_discharges_in_window"]["mean"] is None
    h = r["entities"]["H"]["hourly"]
    assert h["occupancy_open_capacity_weighted"] is None
    assert h["hours_at_full_open_capacity_share"] is None
    json.dumps(r, allow_nan=False)


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "negative", "nan", "occupancy", "queue"]
)
def test_bad_hourly_inputs_cannot_produce_a_report(mutation: str) -> None:
    events, rows = fixture()
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif mutation in {"negative", "nan"}:
        rows[0]["charge_soins_min_h"] = -1 if mutation == "negative" else float("nan")
    elif mutation == "occupancy":
        rows[10]["lits_occupes"] += 1  # Plausible stock, but inconsistent with movements.
    else:
        rows[0]["attente_urgences_nb"] += 1
    with pytest.raises(ValueError):
        measure(config(), events, rows)


@pytest.mark.parametrize(
    "mutation", ["future", "duplicate", "request", "transfer", "wait", "order"]
)
def test_impossible_or_future_paths_rejected(mutation: str) -> None:
    events, _ = fixture()
    if mutation == "future":
        events.append(event(24, "SORTIE", "B", destination="domicile"))
    elif mutation == "duplicate":
        events.insert(1, copy.deepcopy(events[0]))
    elif mutation == "request":
        events.pop(0)
    elif mutation == "transfer":
        events[5]["payload"]["depuis"] = "U_B"
    elif mutation == "wait":
        events[4]["payload"]["attente_h"] = 99
    else:
        events.reverse()
    with pytest.raises(ValueError):
        reconstruct(config(), events)


def test_test_partition_blocked_before_consuming_events() -> None:
    def forbidden() -> Any:
        raise AssertionError("Test events opened")
        yield  # pragma: no cover

    with pytest.raises(ValueError, match="Reserved test"):
        measure(config(partition="test"), forbidden(), [])


def test_verified_export_publish_is_reproducible_and_refuses_mutations(tmp_path: Path) -> None:
    source = tmp_path / "source"
    generate(config(days=3, warmup_days=2), source)
    first = publish(source, tmp_path / "first")
    second = publish(source, tmp_path / "second")
    assert first == second
    assert (tmp_path / "first/scorecard.json").read_bytes() == (
        tmp_path / "second/scorecard.json"
    ).read_bytes()
    with pytest.raises(FileExistsError):
        publish(source, tmp_path / "first")
    with (source / "truth/units_hourly.csv").open("a") as stream:
        stream.write("corruption\n")
    with pytest.raises(ValueError, match="checksum"):
        publish(source, tmp_path / "failed")
    assert not (tmp_path / "failed").exists()


def test_test_run_refused_and_source_unmodified(tmp_path: Path) -> None:
    source = tmp_path / "test"
    generate(config(partition="test"), source)
    before = (source / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="Reserved test"):
        score_run(source)
    assert (source / "manifest.json").read_bytes() == before


def test_known_runtime_overlay_is_not_accepted_as_versioned_truth(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(config().model_dump_json())
    (tmp_path / "OVERLAY.json").write_text(json.dumps({"experimental_overlay": True}))
    with pytest.raises(ValueError, match="Runtime overlay"):
        score_run(tmp_path)


def test_reference_registry_cannot_introduce_unreviewed_acceptance_bands(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    path = root / "configs/synthetic/realism_references_v1.json"
    data = load_references(path)
    assert data["target"]["individual_real_patient_data_used"] is False
    assert len(data["references"]) == 8
    data["references"][0]["acceptance_band"] = [0.9, 0.96]
    mutated = tmp_path / "references.json"
    mutated.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="acceptance bands"):
        load_references(mutated)


def test_ght600_configuration_labels_only_250_simulated_beds() -> None:
    root = Path(__file__).resolve().parents[2]
    raw = json.loads((root / "configs/synthetic/hospital_ght600_medical_scope_v1.json").read_text())
    cfg = HospitalConfig.model_validate(raw)
    assert sum(u.beds for u in cfg.units) == 250
    assert len(cfg.units) == 9
    assert len(cfg.changes) == 18
    assert cfg.partition == "development"
    assert cfg.documentary.staff_forecasts == "milestones_v1"
    assert cfg.documentary.downstream_confirmation == "request_delay_v1"
