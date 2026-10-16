"""Finite resource conservation, competing requests, lifecycle and old-engine isolation."""

from __future__ import annotations

import json
from collections import Counter, deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from hospitalos.synthetic.config import ClinicalConfig, HospitalConfig, SMRConfig
from hospitalos.synthetic.engine import _HS, _RUN, advance_checked, build_simulation, simulate
from hospitalos.synthetic.generate import generate
from hospitalos.synthetic.smr import Request, SMRAllocator


def config(**changes: Any) -> HospitalConfig:
    raw = json.loads(Path("configs/synthetic/hospital_two_poles.json").read_text())
    raw.update(days=7, warmup_days=0, start="2025-01-06")
    raw.update(changes)
    return HospitalConfig.model_validate(raw)


def pool(**changes: Any) -> SMRConfig:
    return SMRConfig.model_validate(
        {
            "mode": "finite_v1",
            "beds": 1,
            "oxygen_beds": 1,
            "isolation_beds": 1,
            "preparation_h": 1,
            **changes,
        }
    )


def tiny(**changes: Any) -> tuple[SMRAllocator, Any, Any]:
    allocator = SMRAllocator(pool(**changes), 41)
    patients = {
        i: SimpleNamespace(
            pid=i, unit=i, ready_h=0, conf=False, tr=False, dest_decl=-1, aval_dem=False, img=False
        )
        for i in range(2)
    }
    sim = SimpleNamespace(
        p_dest=[1, 1],
        p_oxy=[False, False],
        p_iso=[False, False],
        bloque=lambda p: p.img,
        x=SimpleNamespace(ouvre=[True] * 100),
    )
    st = SimpleNamespace(patients=patients, q_tr=deque())
    return allocator, sim, st


@pytest.mark.parametrize(
    "raw",
    [
        {"mode": "finite_v1", "beds": -1},
        {"beds": 3},
        {"mode": "finite_v1", "beds": 1, "oxygen_beds": 2},
        {"mode": "finite_v1", "preparation_h": 0},
        {"mode": "finite_v1", "external_arrivals_per_day": float("nan")},
    ],
)
def test_pool_rejects_invalid_hypotheses(raw: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SMRConfig.model_validate(raw)


def test_clinical_probability_does_not_fall_when_survivor_orientation_changes() -> None:
    legacy = build_simulation(config()).x
    fixed = build_simulation(config(clinical={"destinations": "conditional_survival_v1"})).x
    spec = _HS.UNITS["CSG"]
    old = [legacy.destination_probabilities(spec, 80, d)[3] for d in range(1, 5)]
    new = [fixed.destination_probabilities(spec, 80, d) for d in range(1, 5)]
    assert old[0] > old[-1]  # Reproduces the original normalisation artefact.
    np.testing.assert_allclose([p[3] for p in new], [new[0][3]] * 4)
    for probabilities in new:
        assert probabilities.sum() == pytest.approx(1)
        assert np.all(probabilities >= 0)
    assert new[-1][1] + new[-1][2] > new[0][1] + new[0][2]
    with pytest.raises(ValidationError):
        ClinicalConfig(death_dependence_slope=0.1)


def test_smr_capacity_does_not_change_arriving_cohort_or_other_random_draws() -> None:
    a = build_simulation(config(smr=pool(beds=0, oxygen_beds=0, isolation_beds=0)))
    b = build_simulation(config(smr=pool(beds=30)))
    for k in a.x.pat:
        np.testing.assert_array_equal(a.x.pat[k], b.x.pat[k])
    for k in ("u_politique", "u_reco", "cap_transport"):
        np.testing.assert_array_equal(getattr(a.x, k), getattr(b.x, k))
    assert config().fingerprint == config(smr=SMRConfig(), clinical=ClinicalConfig()).fingerprint
    assert config(smr=pool()).fingerprint != config().fingerprint


def test_two_units_share_one_place_and_release_restores_it() -> None:
    a, sim, st = tiny(stay_median_days=1.0, stay_sigma=0.0)
    a.prepare(sim, st, 0, None)
    a.prepare(sim, st, 10, None)
    assert a.permits(sim, st, st.patients[0], 10)
    assert not a.permits(sim, st, st.patients[1], 10)
    a.depart(sim, st, st.patients.pop(0), 10, None)
    assert a.inspect(sim, st, 10)["smr_occupied"] == 1
    a.prepare(sim, st, 34, None)
    assert a.permits(sim, st, st.patients[1], 34)
    assert a.inspect(sim, st, 34)["smr_reserved"] == 1


def test_incompatible_bed_is_not_allocated_and_head_does_not_block_compatible_request() -> None:
    a, sim, st = tiny(oxygen_beds=0, isolation_beds=0)
    sim.p_oxy[0] = True
    a.prepare(sim, st, 0, None)
    a.prepare(sim, st, 10, None)
    assert not a.permits(sim, st, st.patients[0], 10)
    assert a.permits(sim, st, st.patients[1], 10)


@pytest.mark.parametrize("reason", ["clinical", "expiry", "orientation"])
def test_reservation_restitution_removes_transport_and_confirmation(reason: str) -> None:
    a, sim, st = tiny(reservation_ttl_h=2)
    a.prepare(sim, st, 0, None)
    a.prepare(sim, st, 10, None)
    st.patients[0].tr = True
    st.q_tr.append((0, 10))
    if reason == "clinical":
        st.patients[0].img = True
    elif reason == "orientation":
        sim.p_dest[0] = 0
    a.prepare(sim, st, 12, None)
    assert not st.q_tr and not st.patients[0].tr and not st.patients[0].conf
    assert a.inspect(sim, st, 12)["smr_free"] == 1
    assert not a.permits(sim, st, st.patients[0], 12) or reason == "orientation"
    a.prepare(sim, st, 34, None)
    assert a.permits(sim, st, st.patients[1], 34)


def test_external_request_uses_same_queue_and_cannot_create_capacity() -> None:
    a, sim, st = tiny()
    state = a.state(st)
    state.requests["outside"] = Request("outside", None, 0, -1, 0, False, False)
    a.prepare(sim, st, 0, None)
    a.prepare(sim, st, 10, None)
    assert state.requests["outside"].status == "occupied"
    assert not any(a.permits(sim, st, p, 10) for p in st.patients.values())
    assert a.inspect(sim, st, 10)["smr_waiting_internal"] == 2


def test_external_abandonment_is_explicit() -> None:
    a, sim, st = tiny(beds=0, oxygen_beds=0, isolation_beds=0, external_patience_h=1)
    state = a.state(st)
    state.requests["outside"] = Request("outside", None, 0, 0, 0, False, False)
    a.prepare(sim, st, 1, None)
    assert state.requests["outside"].status == "cancelled"


def test_double_assignment_mutation_and_departure_without_offer_fail() -> None:
    a, sim, st = tiny()
    with pytest.raises(RuntimeError, match="without eligible"):
        a.depart(sim, st, st.patients[0], 10, None)
    a.prepare(sim, st, 0, None)
    a.prepare(sim, st, 10, None)
    state = a.state(st)
    other = state.requests[state.internal[1]]
    other.status, other.bed, other.reserved_h = "reserved", 0, 10
    with pytest.raises(RuntimeError, match="capacity"):
        a.inspect(sim, st, 10)


def patient(pid: int, unit: int) -> Any:
    p = _HS.Pat.__new__(_HS.Pat)
    for k in _HS.Pat.__slots__:
        setattr(p, k, 0)
    p.pid, p.home, p.unit, p.dec_h = pid, unit, -1, 0
    p.dsp, p.dest_decl, p.aide_h = -1, -1, -1
    return p


def test_capacity_change_propagates_to_urgent_queue_from_identical_state() -> None:
    sim = build_simulation(config(smr=pool(), days=30))
    state = _HS.State(sim.x)
    sim.x.arrivees = [[] for _ in range(sim.x.H)]
    for pid in (0, 1, 2):
        sim.p_iso[pid] = sim.p_oxy[pid] = False
        sim.p_montee[pid] = 0
        sim.x.pat["img"][pid] = sim.x.pat["avis"][pid] = False
        sim.x.pat["los_med_h"][pid] = 1
        sim.p_dest[pid] = 1
    for pid in (0, 1):
        sim.admettre(state, patient(pid, pid), pid, 0, 0, False, None)
    # Close all free standard beds: the next arrival needs a discharge and cleaning.
    sim.x.fermes[:, :] = sim.x.lits[:, None]
    # Leave only this bed reopenable. Control retains its occupant, treatment frees it.
    sim.x.ordre_fermeture[0] = [b for b in sim.x.ordre_fermeture[0] if b != 0] + [0]
    sim.x.fermes[0, :] = sim.x.lits[0] - 1
    state.q_urg[0].append(patient(2, 0))
    original = state.clone()
    summaries = []
    for beds in (0, 1):
        sim.smr = SMRAllocator(pool(beds=beds, oxygen_beds=beds, isolation_beds=beds), sim.x.seed)
        branch = original.clone()
        waiting = 0
        for h in range(48):
            m = sim.step(branch, h, politique=False)
            sim.smr.inspect(sim, branch, h)
            waiting += int(m["attente"].sum())
        summaries.append(waiting)
    assert summaries[1] < summaries[0]
    assert not hasattr(original, "smr_state")


@pytest.mark.parametrize("family", ["v041", "local_v1", "hybrid_v1"])
def test_full_engine_conservation_and_clone_with_ledger(family: str) -> None:
    cfg = config(
        days=12,
        warmup_days=7,
        mechanism_family=family,
        smr=pool(beds=8, external_arrivals_per_day=0.5),
        clinical={"destinations": "conditional_survival_v1"},
        documentary={
            "staff_forecasts": "milestones_v1",
            "downstream_confirmation": "request_delay_v1",
        },
        dynamics={"discharges": "rolling_v1"},
    )
    sim = build_simulation(cfg)
    st, log = _HS.State(sim.x), _RUN.Journal(sim)
    checks: Counter[str] = Counter()
    for h in range(200):
        advance_checked(sim, st, h, log, checks, politique=True)
    fork = st.clone()
    assert fork.smr_state == st.smr_state and fork.smr_state is not st.smr_state
    for h in range(200, 230):
        a = sim.step(st, h, politique=False, log=log)
        b = sim.step(fork, h, politique=False)
        for k in a:
            np.testing.assert_array_equal(a[k], b[k])
        assert st.smr_state == fork.smr_state
        sim.smr.inspect(sim, st, h)
    assert all(v == 0 for k, v in checks.items() if k != "heures_controlees")
    assert any(e["type"] == "SMR_REQUESTED" for e in log.events)
    assert all("release_h" not in e["payload"] for e in log.events)


def test_export_contains_censored_current_capacity_and_reproducible_ledger(tmp_path: Path) -> None:
    cfg = config(days=4, warmup_days=7, smr=pool(beds=8))
    a, b = generate(cfg, tmp_path / "a"), generate(cfg, tmp_path / "b")
    assert a["files_sha256"] == b["files_sha256"]
    assert "smr_capacity" in (tmp_path / "a/truth/shared_resources_hourly.csv").read_text()
    result = simulate(cfg)
    for row in result.resources:
        assert row["smr_capacity"] == row["smr_free"] + row["smr_reserved"] + row["smr_occupied"]


def test_silent_partial_csv_write_never_publishes_complete_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.write_bytes

    def truncated(path: Path, data: bytes) -> int:
        if path.name == "units_hourly.csv":
            original(path, data[: len(data) // 2])
            return len(data)  # Simulate even a misleading successful write count.
        return original(path, data)

    monkeypatch.setattr(Path, "write_bytes", truncated)
    with pytest.raises(RuntimeError, match="Incomplete CSV write"):
        generate(config(days=1), tmp_path / "output")
    assert not (tmp_path / "output").exists()
