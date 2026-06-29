#!/usr/bin/env python3
"""Frozen text-embedding pipeline for Gate 1-B, with no predictive evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

GATE_ROOT = Path(__file__).resolve().parents[1]
if str(GATE_ROOT) not in sys.path:
    sys.path.insert(0, str(GATE_ROOT))

from loaders.serialize import (  # noqa: E402
    serialize_fluent,
    serialize_structured,
    serialized_field_names,
)

DEFAULT_MODEL = "Qwen/Qwen3-1.7B-Base"
DEFAULT_INDEX_DIR = GATE_ROOT / "runs" / "serialize"
EXPECTED_PRIMARY_VIEW = "hard_case_stratified"
EXPECTED_CONTROL_VIEW = "hard_case_matched"
VIEW_NAMES = (EXPECTED_PRIMARY_VIEW, EXPECTED_CONTROL_VIEW)
TOY_EMBEDDING_DIM = 32
FORBIDDEN_SERIALIZED_FIELDS = {
    "apr_severity",
    "apr_risk_mortality",
    "length_of_stay",
    "total_charges",
    "total_costs",
    "disposition_raw",
    "target_disposition",
    "aval_institu",
    "target",
    "label",
    "mapped_class",
}
TARGET_PROVENANCE_FIELDS = {
    "disposition_raw",
    "target_disposition",
    "aval_institu",
    "target",
    "label",
    "mapped_class",
}


@dataclass(frozen=True, slots=True)
class EncodingConfig:
    """Runtime-only options for frozen embedding extraction."""

    model: str = DEFAULT_MODEL
    batch_size: int = 8
    max_length: int = 1024
    device: str = "auto"
    dtype: str = "auto"
    seed: int = 42
    toy_encoder: bool = False


def mean_pooling(hidden: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    """Mean-pool non-padding token states only."""
    _validate_pooling_inputs(hidden, attention_mask)
    weights = attention_mask.astype(np.float32)[..., None]
    denominator = weights.sum(axis=1)
    if np.any(denominator == 0):
        raise ValueError("cannot pool a sequence containing only padding")
    return (hidden.astype(np.float32) * weights).sum(axis=1) / denominator


def last_token_pooling(hidden: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    """Select the final non-padding token state for each sequence."""
    _validate_pooling_inputs(hidden, attention_mask)
    if np.any(attention_mask.sum(axis=1) == 0):
        raise ValueError("cannot pool a sequence containing only padding")
    positions = np.arange(attention_mask.shape[1], dtype=np.int64)[None, :]
    last_positions = np.where(attention_mask.astype(bool), positions, -1).max(axis=1)
    return hidden[np.arange(hidden.shape[0]), last_positions].astype(np.float32)


def serialize_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    style: str,
) -> list[str]:
    """Serialize canonical rows under the fixed no-APR contract."""
    fields = set(serialized_field_names(include_apr=False))
    leaked = fields.intersection(FORBIDDEN_SERIALIZED_FIELDS)
    if leaked:
        raise AssertionError(f"forbidden fields entered frozen encoding: {sorted(leaked)}")
    serializer = {
        "structured": serialize_structured,
        "fluent": serialize_fluent,
    }.get(style)
    if serializer is None:
        raise ValueError(f"unsupported serialization style: {style}")
    texts = [serializer(row, include_apr=False) for row in rows]
    for row, text in zip(rows, texts, strict=True):
        _assert_no_forbidden_provenance(row, text)
    return texts


def toy_encode_texts(
    texts: Sequence[str],
    *,
    batch_size: int,
    max_length: int,
    seed: int,
    poolings: Sequence[str],
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Deterministic local encoder used only to validate pipeline plumbing."""
    pooled: dict[str, list[np.ndarray]] = {pooling: [] for pooling in poolings}
    lengths: list[int] = []
    truncated = 0
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        tokenized = [_toy_tokens(text) for text in batch]
        lengths.extend(len(tokens) for tokens in tokenized)
        truncated += sum(len(tokens) > max_length for tokens in tokenized)
        clipped = [tokens[:max_length] for tokens in tokenized]
        width = max(len(tokens) for tokens in clipped)
        hidden = np.zeros((len(batch), width, TOY_EMBEDDING_DIM), dtype=np.float32)
        mask = np.zeros((len(batch), width), dtype=np.int8)
        for row_index, tokens in enumerate(clipped):
            for token_index, token in enumerate(tokens):
                hidden[row_index, token_index] = _toy_token_vector(
                    token,
                    token_index=token_index,
                    seed=seed,
                )
                mask[row_index, token_index] = 1
        if "mean" in pooled:
            pooled["mean"].append(mean_pooling(hidden, mask))
        if "last" in pooled:
            pooled["last"].append(last_token_pooling(hidden, mask))
    arrays = {
        pooling: np.concatenate(parts, axis=0).astype(np.float16)
        for pooling, parts in pooled.items()
    }
    return arrays, _length_stats(lengths, truncated, max_length)


def encode_frozen(
    *,
    input_path: str | Path,
    output_dir: str | Path,
    index_dir: str | Path = DEFAULT_INDEX_DIR,
    config: EncodingConfig = EncodingConfig(),
    limit: int | None = None,
    include_fluent: bool = False,
    pooling: str = "both",
    resume: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Encode both preregistered views with one frozen encoder and no labels in text."""
    _seed_everything(config.seed)
    if pooling not in {"mean", "both"}:
        raise ValueError("pooling must be 'mean' or 'both'")
    canonical = _read_canonical(input_path)
    index_root = Path(index_dir)
    preregistration = _read_json(index_root / "eval_preregistration.json")
    _assert_preregistered_roles(preregistration)
    view_ids = {
        view: _limited_ids(
            _read_json(index_root / f"{view}_index.json")["stay_ids"],
            limit,
        )
        for view in VIEW_NAMES
    }
    print(
        "admissions_to_encode="
        + ", ".join(f"{view}:{len(ids)}" for view, ids in view_ids.items())
    )
    union_ids = sorted({stay_id for ids in view_ids.values() for stay_id in ids})
    canonical_by_id = _canonical_by_stay_id(canonical)
    missing_ids = sorted(set(union_ids).difference(canonical_by_id.index))
    if missing_ids:
        raise ValueError(f"hard-case indexes reference missing stay_id values: {missing_ids[:5]}")
    rows = [canonical_by_id.loc[stay_id].to_dict() for stay_id in union_ids]
    styles = ["structured"] + (["fluent"] if include_fluent else [])
    output = Path(output_dir)
    variants = _variant_names(styles, pooling)
    expected_outputs = _expected_output_paths(output, variants)

    if dry_run:
        return {
            "dry_run": True,
            "n_unique_admissions": len(union_ids),
            "views": {view: len(ids) for view, ids in view_ids.items()},
            "variants": variants,
        }
    if resume and _all_outputs_exist(output, expected_outputs):
        print("resume=all requested files already exist; no encoding performed")
        return {
            "embedding_manifest": _read_json(output / "embedding_manifest.json"),
            "encoding_stats": _read_json(output / "encoding_stats.json"),
            "resumed_without_encoding": True,
        }

    output.mkdir(parents=True, exist_ok=True)
    id_to_position = {stay_id: position for position, stay_id in enumerate(union_ids)}
    stats_by_style: dict[str, Any] = {}
    embedding_dim: int | None = None
    for style in styles:
        texts = serialize_rows(rows, style=style)
        requested_poolings = ["mean"] if style == "fluent" or pooling == "mean" else ["mean", "last"]
        if config.toy_encoder:
            embeddings, token_stats = toy_encode_texts(
                texts,
                batch_size=config.batch_size,
                max_length=config.max_length,
                seed=config.seed,
                poolings=requested_poolings,
            )
            resolved_device = "cpu"
            resolved_dtype = "float16-output"
        else:
            embeddings, token_stats, resolved_device, resolved_dtype = _hf_encode_texts(
                texts,
                config=config,
                poolings=requested_poolings,
            )
        embedding_dim = int(next(iter(embeddings.values())).shape[1])
        stats_by_style[style] = {
            **token_stats,
            "n_encoded_unique": len(union_ids),
            "embedding_dim": embedding_dim,
            "device": resolved_device,
            "dtype": resolved_dtype,
            "poolings": requested_poolings,
        }
        for view, ids in view_ids.items():
            positions = np.asarray([id_to_position[stay_id] for stay_id in ids], dtype=np.int64)
            for pooling_name, matrix in embeddings.items():
                destination = output / view / f"{style}_{pooling_name}.npy"
                if resume and destination.exists():
                    print(f"resume=skip existing {destination}")
                    continue
                _atomic_save_npy(destination, matrix[positions].astype(np.float16, copy=False))

    for view, ids in view_ids.items():
        metadata = _metadata_for_view(
            canonical_by_id,
            ids,
            view=view,
            include_fluent=include_fluent,
        )
        _atomic_write_parquet(output / view / "metadata.parquet", metadata)

    timestamp = datetime.now(timezone.utc).isoformat()
    manifest = {
        "model": config.model,
        "frozen_encoder": True,
        "training_performed": False,
        "primary_pooling": "mean_pooling",
        "ablation_pooling": "last_token_pooling",
        "primary_style": "structured",
        "ablation_style": "fluent",
        "apr": "excluded",
        "target_excluded_from_text": True,
        "views_encoded": list(VIEW_NAMES),
        "primary_lift_view": preregistration["primary_lift_view"],
        "confound_control_view": preregistration["confound_control_view"],
        "no_metrics_computed": True,
        "toy_encoder": config.toy_encoder,
        "seed": config.seed,
        "created_at_utc": timestamp,
    }
    encoding_stats = {
        "model": config.model,
        "max_length": config.max_length,
        "seed": config.seed,
        "n_unique_admissions": len(union_ids),
        "embedding_dim": embedding_dim,
        "union_id_checksum_sha256": _id_checksum(union_ids),
        "view_stats": {
            view: {
                "n_admissions": len(ids),
                "id_checksum_sha256": _id_checksum(ids),
            }
            for view, ids in view_ids.items()
        },
        "serialization_stats": stats_by_style,
        "variants": variants,
        "created_at_utc": timestamp,
    }
    _atomic_write_json(output / "embedding_manifest.json", manifest)
    _atomic_write_json(output / "encoding_stats.json", encoding_stats)
    return {"embedding_manifest": manifest, "encoding_stats": encoding_stats}


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI without any APR or predictive-evaluation option."""
    parser = argparse.ArgumentParser(description="Frozen Gate 1-B text embedding")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--index-dir", default=str(DEFAULT_INDEX_DIR))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--dtype", default="auto")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--include-fluent", action="store_true")
    parser.add_argument("--pooling", choices=("mean", "both"), default="both")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--toy-encoder", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = encode_frozen(
        input_path=args.input,
        output_dir=args.out,
        index_dir=args.index_dir,
        config=EncodingConfig(
            model=args.model,
            batch_size=args.batch_size,
            max_length=args.max_length,
            device=args.device,
            dtype=args.dtype,
            seed=args.seed,
            toy_encoder=args.toy_encoder,
        ),
        limit=args.limit,
        include_fluent=args.include_fluent,
        pooling=args.pooling,
        resume=args.resume,
        dry_run=args.dry_run,
    )
    if result.get("dry_run"):
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    stats = result["encoding_stats"]
    print(f"n_encoded={stats['n_unique_admissions']}")
    print(f"embedding_dim={stats['embedding_dim']}")
    print(f"pooling={','.join(stats['variants'])}")
    for style, style_stats in stats["serialization_stats"].items():
        print(f"truncation_rate[{style}]={style_stats['truncation_rate']:.6f}")
    print(f"manifest={Path(args.out) / 'embedding_manifest.json'}")


def _hf_encode_texts(
    texts: Sequence[str],
    *,
    config: EncodingConfig,
    poolings: Sequence[str],
) -> tuple[dict[str, np.ndarray], dict[str, Any], str, str]:
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError(
            "real frozen encoding requires torch and transformers; use --toy-encoder "
            "for the offline smoke test"
        ) from exc

    device = _resolve_device(torch, config.device)
    if device == "cpu":
        warnings.warn("CUDA/MPS unavailable or not selected; frozen encoding runs on CPU")
    tokenizer = AutoTokenizer.from_pretrained(config.model)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model_kwargs: dict[str, Any] = {}
    if config.dtype != "auto":
        dtype = getattr(torch, config.dtype, None)
        if dtype is None:
            raise ValueError(f"unsupported torch dtype: {config.dtype}")
        model_kwargs["torch_dtype"] = dtype
    else:
        model_kwargs["torch_dtype"] = "auto"
    model = AutoModel.from_pretrained(config.model, **model_kwargs).to(device)
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)

    pooled: dict[str, list[np.ndarray]] = {pooling: [] for pooling in poolings}
    lengths: list[int] = []
    truncated = 0
    for start in range(0, len(texts), config.batch_size):
        batch = list(texts[start : start + config.batch_size])
        raw = tokenizer(batch, add_special_tokens=True, truncation=False)
        batch_lengths = [len(token_ids) for token_ids in raw["input_ids"]]
        lengths.extend(batch_lengths)
        truncated += sum(length > config.max_length for length in batch_lengths)
        encoded = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=config.max_length,
            return_tensors="pt",
        )
        encoded = {name: tensor.to(device) for name, tensor in encoded.items()}
        with torch.inference_mode():
            hidden = model(**encoded).last_hidden_state.float().cpu().numpy()
        mask = encoded["attention_mask"].cpu().numpy()
        if "mean" in pooled:
            pooled["mean"].append(mean_pooling(hidden, mask))
        if "last" in pooled:
            pooled["last"].append(last_token_pooling(hidden, mask))
    arrays = {
        pooling_name: np.concatenate(parts, axis=0).astype(np.float16)
        for pooling_name, parts in pooled.items()
    }
    resolved_dtype = str(next(model.parameters()).dtype).replace("torch.", "")
    return arrays, _length_stats(lengths, truncated, config.max_length), device, resolved_dtype


def _resolve_device(torch_module: Any, requested: str) -> str:
    if requested != "auto":
        return requested
    if torch_module.cuda.is_available():
        return "cuda"
    if hasattr(torch_module.backends, "mps") and torch_module.backends.mps.is_available():
        return "mps"
    return "cpu"


def _toy_tokens(text: str) -> list[str]:
    tokens = re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE)
    return tokens or ["<EMPTY>"]


def _toy_token_vector(token: str, *, token_index: int, seed: int) -> np.ndarray:
    payload = f"{seed}:{token_index}:{token}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    values = np.frombuffer(digest, dtype=np.uint8).astype(np.float32)
    return values[:TOY_EMBEDDING_DIM] / 127.5 - 1.0


def _length_stats(lengths: Sequence[int], truncated: int, max_length: int) -> dict[str, Any]:
    values = np.asarray(lengths, dtype=np.float64)
    return {
        "max_length": max_length,
        "n_truncated": int(truncated),
        "truncation_rate": float(truncated / len(lengths)) if lengths else 0.0,
        "token_length_mean": float(values.mean()) if len(values) else 0.0,
        "token_length_p50": float(np.percentile(values, 50)) if len(values) else 0.0,
        "token_length_p95": float(np.percentile(values, 95)) if len(values) else 0.0,
        "token_length_p99": float(np.percentile(values, 99)) if len(values) else 0.0,
    }


def _read_canonical(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if source.suffix.lower() in {".parquet", ".pq"}:
        frame = pd.read_parquet(source)
    elif source.suffix.lower() == ".csv":
        frame = pd.read_csv(source, low_memory=False)
    else:
        raise ValueError(f"unsupported canonical format: {source.suffix}")
    required = {"stay_id", "target_disposition", "age_group", "ccsr_diagnosis"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"canonical input missing columns: {sorted(missing)}")
    return frame


def _canonical_by_stay_id(frame: pd.DataFrame) -> pd.DataFrame:
    if frame["stay_id"].duplicated().any():
        raise ValueError("canonical stay_id must be unique")
    return frame.set_index("stay_id", drop=False)


def _metadata_for_view(
    canonical_by_id: pd.DataFrame,
    ids: Sequence[int],
    *,
    view: str,
    include_fluent: bool,
) -> pd.DataFrame:
    selected = canonical_by_id.loc[list(ids)]
    return pd.DataFrame(
        {
            "admission_id": selected["stay_id"].astype(int).to_numpy(),
            "row_id": selected["stay_id"].astype(int).to_numpy(),
            "view": view,
            "label_aval_institu": selected["target_disposition"].eq("aval_institu").to_numpy(),
            "age_bucket": selected["age_group"].astype(str).to_numpy(),
            "diagnosis_family": selected["ccsr_diagnosis"].astype(str).to_numpy(),
            "serialization_style_available": (
                "structured,fluent" if include_fluent else "structured"
            ),
        }
    )


def _assert_no_forbidden_provenance(row: Mapping[str, object], text: str) -> None:
    normalized = {str(key).strip().lower().replace(" ", "_"): value for key, value in row.items()}
    for field in TARGET_PROVENANCE_FIELDS:
        value = normalized.get(field)
        if value is None or pd.isna(value):
            continue
        cleaned = str(value).strip()
        if cleaned and cleaned.casefold() not in {"unknown", "nan", "none", "<na>"}:
            if cleaned in text:
                raise ValueError(f"forbidden value from {field!r} reached serialized text")
    forbidden_labels = ("Length of Stay:", "Total Charges:", "Severity:", "Mortality risk:")
    if any(label in text for label in forbidden_labels):
        raise ValueError("post-stay or APR display label reached serialized text")


def _assert_preregistered_roles(preregistration: Mapping[str, Any]) -> None:
    if preregistration.get("primary_lift_view") != EXPECTED_PRIMARY_VIEW:
        raise ValueError("preregistration primary_lift_view drifted from hard_case_stratified")
    if preregistration.get("confound_control_view") != EXPECTED_CONTROL_VIEW:
        raise ValueError("preregistration confound_control_view drifted from hard_case_matched")


def _validate_pooling_inputs(hidden: np.ndarray, attention_mask: np.ndarray) -> None:
    if hidden.ndim != 3 or attention_mask.ndim != 2:
        raise ValueError("expected hidden [batch,tokens,dim] and mask [batch,tokens]")
    if hidden.shape[:2] != attention_mask.shape:
        raise ValueError("hidden and attention mask token axes do not align")


def _limited_ids(values: Iterable[object], limit: int | None) -> list[int]:
    ids = [int(value) for value in values]
    return ids if limit is None else ids[:limit]


def _variant_names(styles: Sequence[str], pooling: str) -> list[str]:
    variants = ["structured_mean"]
    if pooling == "both":
        variants.append("structured_last")
    if "fluent" in styles:
        variants.append("fluent_mean")
    return variants


def _expected_output_paths(output: Path, variants: Sequence[str]) -> list[Path]:
    return [output / view / f"{variant}.npy" for view in VIEW_NAMES for variant in variants]


def _all_outputs_exist(output: Path, expected: Sequence[Path]) -> bool:
    support = [output / "embedding_manifest.json", output / "encoding_stats.json"]
    support.extend(output / view / "metadata.parquet" for view in VIEW_NAMES)
    return all(path.exists() for path in [*expected, *support])


def _id_checksum(ids: Sequence[int]) -> str:
    payload = "\n".join(str(stay_id) for stay_id in ids).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_save_npy(path: Path, values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as handle:
        np.save(handle, values)
    temporary.replace(path)


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.{os.getpid()}.tmp.parquet")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)


if __name__ == "__main__":
    main()
