"""Tests for frozen, leak-guarded Gate 1-B embedding extraction."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "gate1b_encode_frozen.py"
SPEC = importlib.util.spec_from_file_location("gate1b_encode_frozen", SCRIPT_PATH)
assert SPEC and SPEC.loader
ENCODING = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ENCODING
SPEC.loader.exec_module(ENCODING)


def test_pooling_respects_mask_and_last_non_padding_token() -> None:
    hidden = np.asarray(
        [
            [[1.0, 2.0], [3.0, 4.0], [100.0, 200.0]],
            [[5.0, 6.0], [7.0, 8.0], [9.0, 10.0]],
        ]
    )
    mask = np.asarray([[1, 1, 0], [1, 1, 1]])

    mean = ENCODING.mean_pooling(hidden, mask)
    last = ENCODING.last_token_pooling(hidden, mask)

    np.testing.assert_allclose(mean, [[2.0, 3.0], [7.0, 8.0]])
    np.testing.assert_allclose(last, [[3.0, 4.0], [9.0, 10.0]])


def test_toy_encoder_is_deterministic_and_has_nonzero_dimension() -> None:
    texts = ["Age: 70 or Older. Diagnosis group: Heart failure.", "Age: 18-29."]

    first, stats = ENCODING.toy_encode_texts(
        texts,
        batch_size=2,
        max_length=32,
        seed=42,
        poolings=["mean", "last"],
    )
    second, _ = ENCODING.toy_encode_texts(
        texts,
        batch_size=1,
        max_length=32,
        seed=42,
        poolings=["mean", "last"],
    )

    assert first["mean"].shape == first["last"].shape == (2, ENCODING.TOY_EMBEDDING_DIM)
    assert stats["truncation_rate"] == 0.0
    np.testing.assert_array_equal(first["mean"], second["mean"])
    np.testing.assert_array_equal(first["last"], second["last"])
    assert not np.array_equal(first["mean"][0], first["mean"][1])


def test_serialized_text_excludes_target_apr_and_post_stay_provenance() -> None:
    row = _row(1, "Skilled Nursing Home", "aval_institu")

    for style in ("structured", "fluent"):
        text = ENCODING.serialize_rows([row], style=style)[0]
        assert row["disposition_raw"] not in text
        assert row["target_disposition"] not in text
        assert str(row["length_of_stay"]) not in text
        assert str(row["total_charges"]) not in text
        assert "Severity:" not in text
        assert "Mortality risk:" not in text


def test_cli_has_no_apr_option() -> None:
    options = {option for action in ENCODING.build_parser()._actions for option in action.option_strings}

    assert "--include-apr" not in options


def test_end_to_end_toy_outputs_align_metadata_embeddings_and_manifests(tmp_path: Path) -> None:
    canonical, index_dir = _pipeline_fixture(tmp_path)
    output = tmp_path / "out"

    result = ENCODING.encode_frozen(
        input_path=canonical,
        output_dir=output,
        index_dir=index_dir,
        config=ENCODING.EncodingConfig(
            model="toy",
            batch_size=3,
            max_length=8,
            seed=42,
            toy_encoder=True,
        ),
        include_fluent=True,
        pooling="both",
    )

    for view, expected_rows in (("hard_case_stratified", 8), ("hard_case_matched", 6)):
        metadata = pd.read_parquet(output / view / "metadata.parquet")
        for filename in ("structured_mean.npy", "structured_last.npy", "fluent_mean.npy"):
            matrix = np.load(output / view / filename)
            assert len(metadata) == matrix.shape[0] == expected_rows
            assert matrix.shape[1] > 0
            assert matrix.dtype == np.float16
        assert "label_aval_institu" in metadata.columns
        assert set(metadata["serialization_style_available"]) == {"structured,fluent"}

    manifest = result["embedding_manifest"]
    prereg = json.loads((index_dir / "eval_preregistration.json").read_text())
    assert manifest["training_performed"] is False
    assert manifest["frozen_encoder"] is True
    assert manifest["no_metrics_computed"] is True
    assert manifest["primary_lift_view"] == prereg["primary_lift_view"] == "hard_case_stratified"
    assert (
        manifest["confound_control_view"]
        == prereg["confound_control_view"]
        == "hard_case_matched"
    )
    assert result["encoding_stats"]["serialization_stats"]["structured"]["n_truncated"] > 0


def test_pipeline_toy_seed_is_byte_deterministic_for_embeddings(tmp_path: Path) -> None:
    canonical, index_dir = _pipeline_fixture(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    kwargs = {
        "input_path": canonical,
        "index_dir": index_dir,
        "config": ENCODING.EncodingConfig(model="toy", seed=42, toy_encoder=True),
        "limit": 5,
        "pooling": "both",
    }

    ENCODING.encode_frozen(output_dir=first, **kwargs)
    ENCODING.encode_frozen(output_dir=second, **kwargs)

    for view in ("hard_case_stratified", "hard_case_matched"):
        for filename in ("structured_mean.npy", "structured_last.npy"):
            assert (first / view / filename).read_bytes() == (second / view / filename).read_bytes()


def test_checked_in_smoke_manifest_matches_committed_preregistration() -> None:
    manifest = json.loads(
        (ROOT / "runs" / "embeddings" / "qwen3_1_7b_smoke" / "embedding_manifest.json")
        .read_text(encoding="utf-8")
    )
    prereg = json.loads(
        (ROOT / "runs" / "serialize" / "eval_preregistration.json").read_text(encoding="utf-8")
    )

    assert manifest["primary_lift_view"] == prereg["primary_lift_view"]
    assert manifest["confound_control_view"] == prereg["confound_control_view"]
    assert manifest["views_encoded"] == ["hard_case_stratified", "hard_case_matched"]
    assert manifest["training_performed"] is False
    assert manifest["no_metrics_computed"] is True


def _pipeline_fixture(tmp_path: Path) -> tuple[Path, Path]:
    canonical = pd.DataFrame(
        [_row(index, "Skilled Nursing Home" if index % 2 else "Home or Self Care", "aval_institu" if index % 2 else "domicile") for index in range(10)]
    )
    canonical_path = tmp_path / "canonical.parquet"
    canonical.to_parquet(canonical_path, index=False)
    index_dir = tmp_path / "indexes"
    index_dir.mkdir()
    (index_dir / "hard_case_stratified_index.json").write_text(
        json.dumps({"stay_ids": list(range(8))}), encoding="utf-8"
    )
    (index_dir / "hard_case_matched_index.json").write_text(
        json.dumps({"stay_ids": list(range(2, 8))}), encoding="utf-8"
    )
    (index_dir / "eval_preregistration.json").write_text(
        json.dumps(
            {
                "primary_lift_view": "hard_case_stratified",
                "confound_control_view": "hard_case_matched",
            }
        ),
        encoding="utf-8",
    )
    return canonical_path, index_dir


def _row(stay_id: int, disposition: str, target: str) -> dict[str, object]:
    return {
        "stay_id": stay_id,
        "age_group": "70 or Older",
        "gender": "F",
        "type_admission": "Emergency",
        "ed_indicator": "Y",
        "apr_drg": f"DRG {stay_id}",
        "apr_medsurg": "Medical",
        "ccsr_diagnosis": f"Diagnosis family {stay_id}",
        "health_service_area": "New York City",
        "payment_typology": "Medicare",
        "apr_severity": "Extreme",
        "apr_risk_mortality": "Major",
        "length_of_stay": 991 + stay_id,
        "total_charges": 999991 + stay_id,
        "disposition_raw": disposition,
        "target_disposition": target,
    }
