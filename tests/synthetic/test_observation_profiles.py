"""Site observation clocks, fixed-physics invariance and impaired policy inputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hospitalos.synthetic.asof import replay
from hospitalos.synthetic.baseline24 import predict
from hospitalos.synthetic.config import HospitalConfig, ObservationProfile
from hospitalos.synthetic.engine import simulate
from hospitalos.synthetic.generate import export_result
from hospitalos.synthetic.learning import prepare_learning_run
from hospitalos.synthetic.observation_profiles import SiteObservationStream
from hospitalos.synthetic.observations import Delivery, ObservedState, observe_snapshots
from hospitalos.synthetic.online import OnlineSnapshots
from hospitalos.synthetic.policy import ObservedRulePolicy, PolicyContext
from hospitalos.synthetic.policy_loop import PolicyEnvironment, run_policy
from hospitalos.synthetic.registry import CohortPlan, _entries, validate_worlds

IDEAL: dict[str, Any] = {
    "mode": "site_v1",
    "missing_probability": 0.0,
    "recording_delay_median_minutes": 0.0,
    "recording_delay_sigma": 0.0,
    "ingestion_delay_min_minutes": 0.0,
    "ingestion_delay_max_minutes": 0.0,
    "availability_delay_minutes": 0.0,
    "charge_noise_sigma": 0.0,
    "ready_documented_probability": 1.0,
    "downstream_documented_probability": 1.0,
    "revision_probability": 0.0,
    "duplicate_probability": 0.0,
}


@pytest.fixture
def config() -> HospitalConfig:
    raw = json.loads(Path("configs/synthetic/hospital_two_poles.json").read_text())
    raw.update(days=3, warmup_days=1, observation=IDEAL)
    return HospitalConfig.model_validate(raw)


def profiled(config: HospitalConfig, **options: Any) -> HospitalConfig:
    return HospitalConfig.model_validate(
        {**config.model_dump(), "observation": {**config.observation.model_dump(), **options}}
    )


def outage(start: int = 6, end: int = 20, **options: Any) -> dict[str, Any]:
    return {
        "outage_id": "O_TEST",
        "starts_at": f"2025-01-01T{start:02d}:00:00+01:00",
        "ends_at": f"2025-01-01T{end:02d}:00:00+01:00",
        **options,
    }


def event(config: HospitalConfig, hour: float, unit: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = dict.fromkeys(ObservedState.model_fields, 0)
    payload.update(
        lits_occupes=12,
        lits_ouverts=28,
        sortants_medicaux_presents=5,
        en_attente_aval=3,
        charge_soins_min_h=120.0,
        minutes_non_couvertes_h=0,
    )
    return {
        "event_id": f"E{hour}",
        "type": "ETAT_UNITE",
        "unite": unit or config.units[0].unit_id,
        "h": hour + config.warmup_days * 24,
        "payload": payload,
    }


@pytest.mark.parametrize(
    "options",
    [
        {"missing_probability": -0.1},
        {"revision_probability": 1.1},
        {"duplicate_probability": True},
        {"recording_delay_median_minutes": float("nan")},
        {"charge_noise_sigma": float("inf")},
        {"revision_delay_min_h": 0.0},
        {"ingestion_delay_min_minutes": 20.0, "ingestion_delay_max_minutes": 10.0},
        {"revision_delay_min_h": 10.0, "revision_delay_max_h": 5.0},
        {"mode": "unknown"},
        {"mode": "v041", "missing_probability": 0.2},
    ],
)
def test_invalid_profile_rejected(options: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        ObservationProfile.model_validate({"mode": "site_v1", **options})


@pytest.mark.parametrize(
    "windows",
    [
        [outage(end=6)],
        [outage(starts_at="2025-01-01T06:00:00")],
        [outage(starts_at="2025-01-01T06:00:00Z")],
        [outage(starts_at="2025-01-01T06:30:00+01:00")],
        [outage(starts_at="2024-12-31T06:00:00+01:00")],
        [outage(ends_at="2025-01-05T00:00:00+01:00")],
        [outage(unit_ids=["UNKNOWN"])],
        [outage(), outage()],
        [outage(), outage(19, 22, outage_id="O_SECOND")],
    ],
)
def test_invalid_outage_rejected(config: HospitalConfig, windows: list[dict[str, Any]]) -> None:
    with pytest.raises(ValueError):
        profiled(config, outages=windows)


def test_default_fingerprint_and_explicit_profile_identity(config: HospitalConfig) -> None:
    raw = config.model_dump(exclude={"observation"})
    implicit = HospitalConfig.model_validate(raw)
    explicit = HospitalConfig.model_validate({**raw, "observation": {"mode": "v041"}})
    assert implicit.fingerprint == explicit.fingerprint != config.fingerprint


def test_exact_receipts_and_documentation_rates(config: HospitalConfig) -> None:
    row = event(config, 1.0)
    observed = SiteObservationStream(config).observe(row)[0]
    assert observed["t_evenement"] == observed["t_disponible"] == 25.0
    assert observed["payload"] == row["payload"]
    empty = profiled(
        config, ready_documented_probability=0.0, downstream_documented_probability=0.0
    )
    changed = SiteObservationStream(empty).observe(row)[0]
    assert changed["payload"]["sortants_medicaux_presents"] == 0
    assert changed["payload"]["en_attente_aval"] == 0
    assert row["payload"]["sortants_medicaux_presents"] == 5


def test_load_modifies_missingness_and_delay(config: HospitalConfig) -> None:
    delayed = profiled(config, recording_delay_median_minutes=60.0, load_delay_multiplier=3.0)
    row = event(config, 1.0)
    normal = SiteObservationStream(delayed).observe(row)[0]
    row["payload"]["minutes_non_couvertes_h"] = 20
    busy = SiteObservationStream(delayed).observe(row)[0]
    assert normal["t_saisie"] == 26.0 and busy["t_saisie"] == 28.0
    missing = profiled(config, missing_probability=0.5, load_missing_multiplier=2.0)
    assert SiteObservationStream(missing).observe(row) == []


def test_outage_blocks_initial_revision_duplicate_and_releases_backlog(
    config: HospitalConfig,
) -> None:
    changed = profiled(
        config,
        outages=[outage()],
        revision_probability=1.0,
        revision_delay_min_h=2.0,
        revision_delay_max_h=2.0,
        duplicate_probability=1.0,
    )
    stream = SiteObservationStream(changed)
    rows = stream.observe(event(changed, 7.0))
    assert len(rows) == 3
    assert {r["event_version"] for r in rows} == {1, 2}
    assert all(r["t_evenement"] == 31.0 and r["t_disponible"] == 44.0 for r in rows)
    assert all(r["t_ingestion"] == 44.0 for r in rows)
    assert rows[0]["t_saisie"] == rows[2]["t_saisie"] == 31.0
    assert rows[0]["payload"] == rows[2]["payload"]
    assert rows[1]["payload"]["lits_occupes"] == 12


def test_outage_gates_availability_after_earlier_ingestion(config: HospitalConfig) -> None:
    changed = profiled(config, outages=[outage()], availability_delay_minutes=120.0)
    row = SiteObservationStream(changed).observe(event(changed, 5.0))[0]
    assert row["t_ingestion"] == 29.0 and row["t_disponible"] == 44.0


def test_unit_scope_adjacent_windows_and_end_exclusion(config: HospitalConfig) -> None:
    a, b = (u.unit_id for u in config.units[:2])
    windows = [outage(6, 10, unit_ids=[a]), outage(10, 20, outage_id="O_TWO", unit_ids=[a])]
    changed = profiled(config, outages=windows)
    stream = SiteObservationStream(changed)
    assert stream.observe(event(config, 7.0, a))[0]["t_disponible"] == 44.0
    assert stream.observe(event(config, 7.0, b))[0]["t_disponible"] == 31.0
    assert stream.observe(event(config, 20.0, a))[0]["t_disponible"] == 44.0
    # A global outage must also conflict with a unit-specific window.
    with pytest.raises(ValueError, match="Overlapping outages"):
        profiled(config, outages=[*windows, outage(8, 9, outage_id="GLOBAL")])


def test_future_outage_and_event_order_cannot_modify_delivered_past(config: HospitalConfig) -> None:
    config = profiled(
        config,
        recording_delay_median_minutes=12.0,
        revision_probability=1.0,
        duplicate_probability=1.0,
    )
    changed = profiled(config, outages=[outage(18, 23)])
    events = [event(config, float(h)) for h in range(1, 24)]

    def before(c: HospitalConfig, ordered: list[dict[str, Any]]) -> list[dict[str, Any]]:
        stream = SiteObservationStream(c)
        return sorted(
            [r for e in ordered for r in stream.observe(e) if r["t_disponible"] < 42],
            key=lambda r: (r["event_id"], r["event_version"], r["t_disponible"]),
        )

    assert before(config, events) == before(changed, list(reversed(events)))


@pytest.mark.parametrize("family", ["v041", "local_v1", "hybrid_v1"])
def test_profile_cannot_modify_physics_at_fixed_policy(config: HospitalConfig, family: str) -> None:
    config = HospitalConfig.model_validate({**config.model_dump(), "mechanism_family": family})
    before = simulate(config)
    changed = profiled(config, missing_probability=1.0, outages=[outage()])
    after = simulate(changed)
    for field in ("etats", "events", "actions"):
        assert getattr(before.journal, field) == getattr(after.journal, field)
    assert before.resources == after.resources and before.checks == after.checks


def test_future_outage_does_not_change_policy_context_or_recommendation(
    config: HospitalConfig,
) -> None:
    policies = [ObservedRulePolicy(), ObservedRulePolicy()]
    configs = [config, profiled(config, outages=[outage(18, 23)])]
    contexts = []
    recommendations = []
    for profile, policy in zip(configs, policies, strict=True):
        env = PolicyEnvironment(profile, policy.descriptor)
        env.reset()
        policy.reset(env.site)
        for _ in range(9):
            env.advance()
        context = env.observe()
        assert context is not None
        contexts.append(
            [r.model_dump(exclude={"run_id", "sample_id"}) for r in context.observations]
        )
        recommendations.append(policy.recommend(context).units)
    assert contexts[0] == contexts[1]
    assert recommendations[0] == recommendations[1]


def test_online_and_offline_receipts_agree_and_cutoff_is_frozen(config: HospitalConfig) -> None:
    config = profiled(
        config,
        outages=[outage()],
        recording_delay_median_minutes=90.0,
        revision_probability=0.5,
        duplicate_probability=0.5,
    )
    result = simulate(config)
    stream = OnlineSnapshots(config, result.simulation.x)
    truth = []
    for hour in range((config.days + config.warmup_days) * 24):
        batch = result.journal.etats[hour * len(config.units) : (hour + 1) * len(config.units)]
        stream.push(hour, batch)
        for index, snapshot in enumerate(batch):
            unit = config.units[index].unit_id
            truth.append(
                {
                    "event_id": f"BATCH:{hour}:{index}",
                    "hospital_id": config.hospital_id,
                    "pole_id": config.unit_poles[unit],
                    "unit_id": unit,
                    "h": hour - config.warmup_days * 24,
                    "type": "ETAT_UNITE",
                    "payload": {k: v for k, v in snapshot.items() if k not in ("h", "u")},
                }
            )
        stream.receive(hour + 1 - config.warmup_days * 24)
    offline = observe_snapshots(reversed(truth), config)

    def semantic(rows: list[Delivery]) -> list[str]:
        return sorted(r.model_dump_json(exclude={"event_id", "delivery_id"}) for r in rows)

    assert semantic(offline) == semantic(stream.delivered)
    assert offline == observe_snapshots(truth, config)
    assert all(r.available_h <= config.days * 24 for r in offline)
    assert stream.pending  # late receipts really exist and were not pulled forward
    rows = list(replay(offline, config, run_id="profile"))
    stale = [r for r in rows if r.level == "unit" and r.decision_h == 18]
    assert all(r.stale for r in stale)
    assert all(p["status"] == "stale" for p in predict(stale))


def test_total_missingness_is_abstention_and_null_score(
    config: HospitalConfig, tmp_path: Path
) -> None:
    changed = profiled(config, missing_probability=1.0)
    export_result(changed, simulate(changed), tmp_path / "truth")
    report = prepare_learning_run(tmp_path / "truth", tmp_path / "learning")
    assert report["observation_quality"]["deliveries"] == 0
    assert not report["macro_mae"]
    assert all(r["coverage"] == 0 and r["mae"] is None for r in report["metrics"])
    env = PolicyEnvironment(changed, ObservedRulePolicy().descriptor)
    context: PolicyContext | None = env.reset()
    for _ in range(9):
        context = env.advance()
    assert context is not None
    assert all(r.values is None and r.missing for r in context.observations)
    assert all(
        r.probabilities == (0, 0, 0, 0) for r in ObservedRulePolicy().recommend(context).units
    )
    assert "outages" not in env.site.model_dump_json() + context.model_dump_json()


def test_policy_export_reproducible_with_profile_and_no_future_schedule(
    config: HospitalConfig, tmp_path: Path
) -> None:
    changed = profiled(config, outages=[outage()], missing_probability=0.1)
    first = run_policy(changed, ObservedRulePolicy(), tmp_path / "first")
    second = run_policy(changed, ObservedRulePolicy(), tmp_path / "second")
    assert first == second
    assert first["checks"]["online_replay_equal"]
    assert first["settings"]["observation"] == changed.observation.model_dump(mode="json")
    for name in first["files_sha256"]:
        assert (tmp_path / "first" / name).read_bytes() == (tmp_path / "second" / name).read_bytes()


def test_registry_preserves_profiles_across_replicates(config: HospitalConfig) -> None:
    raw = json.loads(Path("configs/synthetic/cohort_structures_v1.json").read_text())
    for index, spec in enumerate(raw["structures"]):
        spec["observation"] = {"mode": "site_v1", "missing_probability": index / 10}
    worlds = _entries(CohortPlan.model_validate(raw))
    validate_worlds(worlds)
    profiles = {
        s["structure_id"]: ObservationProfile.model_validate(s["observation"])
        for s in raw["structures"]
    }
    assert all(w.config.observation == profiles[w.structure_id] for w in worlds)
    assert len({w.config.observation.missing_probability for w in worlds}) >= 3
