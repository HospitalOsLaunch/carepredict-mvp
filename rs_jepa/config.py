"""Configuration dataclasses for the RS-JEPA pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Stage1Config:
    latent_dim: int = 128
    encoder_model_dim: int = 128
    encoder_depth: int = 2
    encoder_heads: int = 4
    encoder_ff_dim: int = 256
    encoder_dropout: float = 0.0
    encoder_max_steps: int = 512
    rssm_deter_dim: int = 256
    rssm_stoch_dim: int = 32
    rssm_min_std: float = 0.1
    rssm_layer_norm: bool = True
    predictor_hidden_dim: int = 256
    predictor_depth: int = 2
    context_steps: int = 168
    horizons: tuple[int, ...] = (6, 24, 72, 168)
    batch_size: int = 64
    lr: float = 3e-4
    weight_decay: float = 1e-4
    grad_clip: float = 1.0
    ema_start: float = 0.996
    ema_end: float = 0.9999
    ema_ramp_steps: int = 10_000
    mixed_precision: bool = True
    deterministic: bool = True
    w_pred: float = 1.0
    w_var: float = 1.0
    w_cov: float = 0.04
    aux_decoder_enabled: bool = False
    aux_decoder_weight: float = 0.1
    block_mask_min_frac: float = 0.15
    block_mask_max_frac: float = 0.40
    channel_mask_prob: float = 0.20


@dataclass(frozen=True)
class Stage2Config:
    k_levels: int = 4
    freeze_backbone: bool = True
    light_finetune: bool = False
    siips_calibration_enabled: bool = False


@dataclass(frozen=True)
class SplitConfig:
    temporal_holdout_weeks: int = 8
    cross_site_val_fraction: float = 0.20
    seed: int = 42


@dataclass(frozen=True)
class SyntheticConfig:
    n_sites: int = 24
    total_days: int = 180
    step_hours: int = 1
    seed: int = 42
    min_capacity: int = 80
    max_capacity: int = 520
    min_base_saturation: float = 0.55
    max_base_saturation: float = 0.92
    min_case_mix: float = 0.7
    max_case_mix: float = 1.4
    min_staffing_ratio: float = 0.78
    max_staffing_ratio: float = 1.18
    surge_event_rate_per_30d: float = 1.25
    surge_min_duration_h: int = 18
    surge_max_duration_h: int = 96
    noise_std: float = 0.06


@dataclass(frozen=True)
class TrainingConfig:
    max_epochs: int = 3
    steps_per_epoch: int = 8
    probe_every_epochs: int = 1
    early_collapse_rank_threshold: float = 4.0
    probe_rank_threshold: float = 4.0
    probe_stride: int = 24
    probe_max_samples: int = 2_000
    checkpoint_path: str = "runs/phaseA/encoder.pt"


@dataclass(frozen=True)
class RSJEPAConfig:
    seed: int = 42
    phase: str = "A"
    stage1: Stage1Config = field(default_factory=Stage1Config)
    stage2: Stage2Config = field(default_factory=Stage2Config)
    split: SplitConfig = field(default_factory=SplitConfig)
    synthetic: SyntheticConfig = field(default_factory=SyntheticConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)


def _coerce_dataclass(cls: type[Any], value: dict[str, Any] | None) -> Any:
    value = dict(value or {})
    kwargs: dict[str, Any] = {}
    field_map = {f.name: f for f in fields(cls)}
    for name, raw in value.items():
        if name not in field_map:
            raise ValueError(f"Clé de configuration inconnue pour {cls.__name__}: {name}")
        typ = field_map[name].type
        if name == "horizons" and isinstance(raw, list):
            raw = tuple(int(v) for v in raw)
        if is_dataclass(typ):
            raw = _coerce_dataclass(typ, raw)
        kwargs[name] = raw
    return cls(**kwargs)


def config_from_dict(raw: dict[str, Any]) -> RSJEPAConfig:
    """Build a typed config from a raw mapping."""

    if not isinstance(raw, dict):
        raise ValueError("La configuration doit être un mapping YAML.")
    nested = {
        "stage1": Stage1Config,
        "stage2": Stage2Config,
        "split": SplitConfig,
        "synthetic": SyntheticConfig,
        "training": TrainingConfig,
    }
    raw = dict(raw)
    for name, cls in nested.items():
        if name in raw:
            raw[name] = _coerce_dataclass(cls, raw[name])
    return _coerce_dataclass(RSJEPAConfig, raw)


def load_config(path: str | Path) -> RSJEPAConfig:
    """Charge une configuration YAML et valide les clés déclarées."""

    with Path(path).open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return config_from_dict(raw)
