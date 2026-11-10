"""Handwritten metadata only: no source archive, simulator or ML execution."""

from __future__ import annotations

import builtins
import datetime as dt
from copy import deepcopy
from typing import Any

import pytest

from research_lab.integrated_full_model_v1_contract import make_v041_synthetic_spec
from research_lab.s0c_synthetic_registry import compile_index
from research_lab.s0c_world_registry import build_registry
from research_lab.s0d_cohort_separation import SCHEMA, audit_cohort_metadata, fingerprint

START = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


def at(hour: int) -> str:
    return (START + dt.timedelta(hours=hour)).isoformat()


def sample(ident: str, world: str, role: str, origin: int) -> dict[str, Any]:
    return {
        "id": ident,
        "world": world,
        "role": role,
        "origin": at(origin),
        "label_cutoff": at(origin + 30),
        "support_start": at(origin - 77),
        "support_end": at(origin + 24),
        "uses": [
            {
                "lineage_id": world,
                "event_id": ident + "-obs",
                "version": 1,
                "kind": "observation",
                "start": at(origin - 77),
                "end": at(origin - 77),
                "available_at": at(origin - 70),
            },
            {
                "lineage_id": world,
                "event_id": ident + "-act",
                "version": 1,
                "kind": "action",
                "start": at(origin - 1),
                "end": at(origin),
                "available_at": at(origin),
            },
            {
                "lineage_id": world,
                "event_id": ident + "-label",
                "version": 1,
                "kind": "label",
                "start": at(origin + 24),
                "end": at(origin + 24),
                "available_at": at(origin + 25),
            },
        ],
    }


def fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    spec = make_v041_synthetic_spec()
    spec["history_steps"] = 72
    canonical = []
    for i, part in enumerate(("train", "validation", "test")):
        canonical.append(
            {
                "world_id": f"w{i}",
                "structure_sha256": str(i + 1) * 64,
                "replicate": 0,
                "config": {
                    "hospital_id": f"h{i}",
                    "partition": part,
                    "seed": i,
                    "mechanism_family": "v041",
                    "days": 30,
                },
            }
        )
    index, _ = compile_index(
        {"schema_version": "0.1", "plan": {"split_axis": "structure"}, "worlds": canonical},
        model_spec=spec,
        temporal_dev_days=7,
        embargo_hours=0,
    )
    rows = []
    for i, part in enumerate(("train", "development", "validation", "ood_blind")):
        rows.append(
            {
                "world_id": f"w{i}",
                "partition": part,
                "hospital_id": f"h{i}",
                "generator_family": "v041",
                "observation_profile": "v041",
                "policy_family": "reference",
                "structure_family": f"shape{i}",
                "seed_group": f"seed{i}",
                "source_manifest_sha256": f"{10 + i:064x}",
                "observation_manifest_sha256": f"{20 + i:064x}",
                "action_manifest_sha256": f"{30 + i:064x}",
                "source_clock": "fixed_utc_plus_01_no_dst",
                "mechanism_tags": ["test"],
                "readable_by_lab": part != "ood_blind",
            }
        )
    registry = build_registry(rows, freeze_id="fixture")
    worlds = []
    for i in range(2):
        worlds.append(
            {
                "id": f"w{i}",
                "episode": f"e{i}",
                "hospital_id": f"h{i}",
                "canonical_partition": ("train", "validation")[i],
                "registry_partition": rows[i]["partition"],
                **{
                    k: rows[i][k]
                    for k in (
                        "source_manifest_sha256",
                        "observation_manifest_sha256",
                        "action_manifest_sha256",
                    )
                },
            }
        )
    m = {
        "schema": SCHEMA,
        "scope": "train_dev_only",
        "mode": "independent_episode",
        "bindings": {
            "world_registry_sha256": fingerprint(registry),
            "exposure_index_sha256": fingerprint(index),
        },
        "episodes": [
            {
                "id": f"e{i}",
                "root": f"e{i}",
                "parents": [],
                "realization_sha256": f"{40 + i:064x}",
                "initial_state_group": f"state{i}",
                "rng_groups": [f"stream{i}"],
                "proof_sha256": "a" * 64,
                "start": at(0),
                "end_exclusive": at(720),
                "source_clock": "fixed_utc_plus_01_no_dst",
            }
            for i in range(2)
        ],
        "dependencies": [],
        "worlds": worlds,
        "samples": [sample("s0", "w0", "train", 100), sample("s1", "w1", "development_ood", 100)],
        "policy": {
            "history_steps": 72,
            "step_hours": 1,
            "horizons_hours": [1, 6, 24],
            "max_age_hours": 6,
            "aggregation_lookback_hours": 0,
            "recurrent_lookback_hours": 0,
            "extra_embargo_hours": 0,
            "bounds": "closed_conservative",
            "model_spec_sha256": index["model_spec_sha256"],
        },
        "coverage": {
            "episodes": ["e0", "e1"],
            "start": at(0),
            "end_exclusive": at(720),
            "completeness": "declared_complete",
            "proof_sha256": "b" * 64,
        },
        "preprocessing": {"fit_sample_ids": ["s0"], "proof_sha256": "c" * 64},
    }
    return m, registry, index


def audit(m: dict[str, Any], r: dict[str, Any], x: dict[str, Any]) -> dict[str, Any]:
    return audit_cohort_metadata(
        m, world_registry=r, exposure_index=x, expected_manifest_sha256=fingerprint(m)
    )


def temporal() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    m, r, x = fixture()
    m["mode"] = "within_episode_temporal"
    m["worlds"] = m["worlds"][:1]
    m["samples"] = [
        sample("s0", "w0", "train", 450),
        sample("s1", "w0", "development_temporal", 552),
    ]
    return m, r, x


def edge(members: list[str], kind: str = "transfer", ident: str = "edge0") -> dict[str, Any]:
    return {
        "id": ident,
        "kind": kind,
        "members": members,
        "start": at(0),
        "end_exclusive": at(1),
        "proof_sha256": "d" * 64,
    }


def test_independent_episodes_same_dates_do_not_claim_source_qualification() -> None:
    m, r, x = fixture()
    before = deepcopy((m, r, x))
    out = audit(m, r, x)
    assert out["metadata_status"] == "CONSISTENT_METADATA_ONLY"
    assert out["separation_status"] == "NOT_QUALIFIED"
    assert out["components_by_role"] == {"train": 1, "development_ood": 1}
    assert out["source_authenticity_verified"] is False
    assert all(
        out[k] is False
        for k in (
            "training_authorized",
            "model_forward_authorized",
            "simulation_authorized",
            "promotion_authorized",
            "reserved_holdout_opened",
        )
    )
    assert (m, r, x) == before


@pytest.mark.parametrize("field", ["realization_sha256", "initial_state_group", "rng_groups"])
def test_n1_n5_renamed_worlds_cannot_hide_shared_provenance(field: str) -> None:
    m, r, x = fixture()
    m["episodes"][1][field] = m["episodes"][0][field]
    assert audit(m, r, x)["reason_codes"] == ["DEPENDENCY_CROSSES_ROLES"]


def test_n2d_forks_with_new_rng_keep_their_ancestor() -> None:
    m, r, x = fixture()
    m["episodes"][1].update(root="e0", parents=["e0"])
    assert audit(m, r, x)["metadata_status"] == "REJECTED"


@pytest.mark.parametrize(
    "kind",
    [
        "transfer",
        "shared_shock",
        "shared_resource",
        "shared_staff",
        "shared_rng",
        "inherited_state",
    ],
)
def test_n2_n14_coupling_survives_end_of_edge(kind: str) -> None:
    m, r, x = fixture()
    m["dependencies"] = [edge(["e0", "e1"], kind)]
    assert audit(m, r, x)["reason_codes"] == ["DEPENDENCY_CROSSES_ROLES"]


def test_transitive_coupling_through_unselected_episode() -> None:
    m, r, x = fixture()
    extra = deepcopy(m["episodes"][0])
    extra.update(
        id="e2",
        root="e2",
        realization_sha256="e" * 64,
        initial_state_group="state2",
        rng_groups=["stream2"],
    )
    m["episodes"].append(extra)
    m["coverage"]["episodes"].append("e2")
    m["dependencies"] = [edge(["e0", "e2"]), edge(["e2", "e1"], ident="edge1")]
    assert audit(m, r, x)["reason_codes"] == ["DEPENDENCY_CROSSES_ROLES"]


@pytest.mark.parametrize(
    ("train_origin", "status"),
    [(450, "CONSISTENT_METADATA_ONLY"), (451, "REJECTED"), (456, "REJECTED")],
)
def test_n3_effective_footprint_boundary_and_nominal_false_positive(
    train_origin: int,
    status: str,
) -> None:
    m, r, x = temporal()
    m["samples"][0] = sample("s0", "w0", "train", train_origin)
    assert audit(m, r, x)["metadata_status"] == status


def test_temporal_shared_episode_is_not_independent_generalization() -> None:
    m, r, x = temporal()
    m["mode"] = "independent_episode"
    assert audit(m, r, x)["reason_codes"] == ["DEPENDENCY_CROSSES_ROLES"]


def test_temporal_mode_does_not_exempt_ood_dependency() -> None:
    m, r, x = fixture()
    m["mode"] = "within_episode_temporal"
    m["dependencies"] = [edge(["e0", "e1"])]
    assert audit(m, r, x)["reason_codes"] == ["OOD_DEPENDENCY_CROSSES_ROLES"]


def test_correlated_training_windows_are_reported_not_rejected() -> None:
    m, r, x = fixture()
    m["samples"].append(sample("s2", "w0", "train", 101))
    assert audit(m, r, x)["correlated_within_role_pairs"] == 1


@pytest.mark.parametrize(
    "change",
    [
        "unknown_member",
        "missing_proof",
        "unknown_parent",
        "coverage",
        "naive_clock",
        "bad_end",
        "unknown_field",
        "unknown_root",
    ],
)
def test_n4_n6_incomplete_lineage_is_never_accepted(change: str) -> None:
    m, r, x = fixture()
    if change == "unknown_member":
        m["dependencies"] = [edge(["e0", "missing"])]
    elif change == "missing_proof":
        m["episodes"][0]["proof_sha256"] = None
    elif change == "unknown_parent":
        m["episodes"][0]["parents"] = ["missing"]
    elif change == "coverage":
        m["coverage"]["completeness"] = "unknown"
    elif change == "naive_clock":
        m["samples"][0]["origin"] = "2026-01-05T04:00:00"
    elif change == "bad_end":
        m["episodes"][0]["end_exclusive"] = at(0)
    elif change == "unknown_root":
        m["episodes"][0]["root"] = "missing"
    else:
        m["training_authorized"] = True
    assert audit(m, r, x)["metadata_status"] == "NOT_QUALIFIED"


def test_n7_event_version_change_does_not_erase_identity() -> None:
    m, r, x = fixture()
    m["samples"][1]["uses"][0].update(lineage_id="w0", event_id="s0-obs", version=2)
    assert audit(m, r, x)["reason_codes"] == ["REUSED_EVENT_ACROSS_ROLES"]


@pytest.mark.parametrize("source_index", [0, 1])
def test_n8_future_information_refused(source_index: int) -> None:
    m, r, x = fixture()
    m["samples"][0]["uses"][source_index]["available_at"] = at(101)
    assert audit(m, r, x)["reason_codes"] == ["ASOF_LEAKAGE"]


def test_n9_fit_on_development_refused() -> None:
    m, r, x = fixture()
    m["preprocessing"]["fit_sample_ids"] = ["s1"]
    assert audit(m, r, x)["reason_codes"] == ["PREPROCESSING_LEAKAGE"]


@pytest.mark.parametrize(
    "field", ["source_manifest_sha256", "observation_manifest_sha256", "action_manifest_sha256"]
)
def test_n10_triplet_binding_mismatch(field: str) -> None:
    m, r, x = fixture()
    m["worlds"][0][field] = "f" * 64
    assert audit(m, r, x)["reason_codes"] == ["ARCHIVE_BINDING_MISMATCH"]


@pytest.mark.parametrize("role", ["validation", "ood_blind", "test"])
def test_n11_n12_reserved_roles_without_any_io(role: str, monkeypatch: pytest.MonkeyPatch) -> None:
    m, r, x = fixture()
    m["samples"][1]["role"] = role

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("No file opening allowed")

    monkeypatch.setattr(builtins, "open", forbidden)
    assert audit(m, r, x)["metadata_status"] == "ACCESS_REFUSED"


def test_n11_relabel_of_canonical_validation_refused() -> None:
    m, r, x = fixture()
    m["worlds"][1]["canonical_partition"] = "train"
    assert audit(m, r, x)["reason_codes"] == ["PARTITION_RELABEL"]


def test_n13_external_pin_cannot_be_updated_by_manifest() -> None:
    m, r, x = fixture()
    pinned = fingerprint(m)
    m["policy"]["max_age_hours"] = 0
    out = audit_cohort_metadata(
        m, world_registry=r, exposure_index=x, expected_manifest_sha256=pinned
    )
    assert out["reason_codes"] == ["MANIFEST_PIN_MISMATCH"]


def test_registry_mutation_detected_even_with_refreshed_bundle_pin() -> None:
    m, r, x = fixture()
    r["readable_worlds"][0]["partition"] = "development"
    assert audit(m, r, x)["reason_codes"] == ["REGISTRY_COMMITMENT_MISMATCH"]


@pytest.mark.parametrize("value", [None, True, -1, float("inf")])
def test_unbounded_or_invalid_recurrent_support(value: Any) -> None:
    m, r, x = fixture()
    m["policy"]["recurrent_lookback_hours"] = value
    # Infinity cannot be canonically pinned; exercise the public failure path.
    out = (
        audit_cohort_metadata(
            m, world_registry=r, exposure_index=x, expected_manifest_sha256="a" * 64
        )
        if value == float("inf")
        else audit(m, r, x)
    )
    assert out["metadata_status"] == "NOT_QUALIFIED"


def test_n3_aggregation_and_age_compose() -> None:
    m, r, x = fixture()
    m["policy"]["aggregation_lookback_hours"] = 2
    assert audit(m, r, x)["reason_codes"] == ["UNDERSTATED_SOURCE_SUPPORT"]


def test_duplicate_origins_refused() -> None:
    m, r, x = fixture()
    duplicate = deepcopy(m["samples"][0])
    duplicate["id"] = "another"
    m["samples"].append(duplicate)
    assert audit(m, r, x)["reason_codes"] == ["DUPLICATE_ORIGIN"]


def test_n15_n16_clean_metadata_never_promotes_science() -> None:
    out = audit(*temporal())
    assert out["statistical_design_status"] == "NOT_QUALIFIED"
    assert out["supervision_status"] == "NOT_QUALIFIED"
    assert out["training_authorized"] is False


def repin(m: dict[str, Any], r: dict[str, Any], x: dict[str, Any]) -> None:
    r["registry_sha256"] = fingerprint({k: v for k, v in r.items() if k != "registry_sha256"})
    m["bindings"] = {
        "world_registry_sha256": fingerprint(r),
        "exposure_index_sha256": fingerprint(x),
    }


def test_n3d_cross_hospital_temporal_overlap() -> None:
    m, r, x = temporal()
    # A second hospital in the same physical episode, separate S0c world.
    w = deepcopy(m["worlds"][0])
    w.update(
        id="w-new",
        hospital_id="h-new",
        source_manifest_sha256="d" * 64,
        observation_manifest_sha256="e" * 64,
        action_manifest_sha256="f" * 64,
    )
    m["worlds"].append(w)
    rr = deepcopy(r["readable_worlds"][0])
    rr.update(world_id=w["id"], hospital_id=w["hospital_id"])
    for key in ("source_manifest_sha256", "observation_manifest_sha256", "action_manifest_sha256"):
        rr[key] = w[key]
    r["readable_worlds"].append(rr)
    for role in ("train", "development_temporal"):
        row = deepcopy(x["partitions"][role][0])
        row.update(world_id=w["id"], hospital_id=w["hospital_id"])
        x["partitions"][role].append(row)
    m["samples"] = [
        sample("s0", "w0", "train", 456),
        sample("s1", "w-new", "development_temporal", 552),
    ]
    repin(m, r, x)
    assert audit(m, r, x)["reason_codes"] == ["TEMPORAL_SUPPORT_OVERLAP"]


def test_ancestry_cycle_fails_closed() -> None:
    m, r, x = fixture()
    ancestor = deepcopy(m["episodes"][0])
    ancestor.update(id="ancestor", root="ancestor", parents=[])
    m["episodes"].append(ancestor)
    m["episodes"][0].update(root="ancestor", parents=["e1"])
    m["episodes"][1].update(root="ancestor", parents=["e0"])
    assert audit(m, r, x)["reason_codes"] == ["ANCESTRY_CYCLE"]


def test_n13_recomputed_registry_hash_does_not_bypass_archive_uniqueness() -> None:
    m, r, x = fixture()
    value = m["worlds"][0]["source_manifest_sha256"]
    m["worlds"][1]["source_manifest_sha256"] = value
    r["readable_worlds"][1]["source_manifest_sha256"] = value
    repin(m, r, x)
    assert audit(m, r, x)["reason_codes"] == ["ARCHIVE_REUSED"]


def test_s0c_seed_group_invariant_is_preserved() -> None:
    m, r, x = fixture()
    r["readable_worlds"][1]["seed_group"] = r["readable_worlds"][0]["seed_group"]
    repin(m, r, x)
    assert audit(m, r, x)["reason_codes"] == ["SEED_GROUP_CROSSES_ROLES"]


def test_index_temporal_world_cannot_change_configuration() -> None:
    m, r, x = fixture()
    x["partitions"]["development_temporal"][0]["config_content_sha256"] = "f" * 64
    repin(m, r, x)
    assert audit(m, r, x)["reason_codes"] == ["TEMPORAL_WORLD_METADATA_MISMATCH"]


def test_reserved_world_scope_refused() -> None:
    m, r, x = fixture()
    m["worlds"][0]["id"] = "w2"
    assert audit(m, r, x)["metadata_status"] == "ACCESS_REFUSED"


def test_no_ml_or_simulator_imports_during_check(monkeypatch: pytest.MonkeyPatch) -> None:
    original = builtins.__import__

    def guarded(name: str, *args: Any, **kwargs: Any) -> Any:
        assert not name.startswith(("torch", "numpy", "rs_jepa", "hospitalos.synthetic"))
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    assert audit(*fixture())["metadata_status"] == "CONSISTENT_METADATA_ONLY"
