"""Build preregistered, proxy-controlled evaluation indexes without encoding data."""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from loaders.sparcs_adapter import TARGET_CLASS, load_canonical

THRESHOLDS = (5, 10, 20)
POSITIVE_LOSS_LIMIT = 0.50
MATCH_NEGATIVES_PER_POSITIVE = 3
MATCH_SEED = 42
MISSING_DIAG_FAMILY = "MISSING_DIAG_FAMILY"
PSYCH_PATTERN = re.compile(r"psych|self[- ]?harm|suicid|mental|substance", re.IGNORECASE)
BLOCKING_WARNING = (
    "hard-case stratification drops more than 50% of aval_institu at every threshold; "
    "stop and review diagnosis-family granularity before encoding"
)


def build_eval_views(
    canonical: pd.DataFrame,
    *,
    baseline_prevalence: float,
    drg_rule_floor: float,
) -> dict[str, dict[str, Any]]:
    """Build threshold sweep, stratified/matched indexes, and fixed evaluation policy."""
    frame = _prepare_frame(canonical)
    sweep_rows = [_threshold_summary(frame, threshold) for threshold in THRESHOLDS]
    selected, blocked = _select_threshold(sweep_rows)
    if blocked:
        warnings.warn(BLOCKING_WARNING, RuntimeWarning, stacklevel=2)

    eligible = _eligible_strata(frame, selected)
    stratified = frame.merge(eligible, on=["age_bucket", "diagnosis_family"], how="inner")
    matched = _matched_sample(stratified)
    warning = BLOCKING_WARNING if blocked else None

    sweep = {
        "thresholds": sweep_rows,
        "min_per_class_selected": selected,
        "selection_rule": (
            "smallest threshold with loss_rate_positive <= 0.50; fallback to 5 with "
            "blocking warning"
        ),
        "blocking_warning": warning,
    }
    stratified_payload = _view_payload(
        view="hard_case_stratified",
        role="primary_lift_reading",
        before=frame,
        after=stratified,
        selected=selected,
        warning=warning,
    )
    stratified_payload["stratum_key"] = "age_bucket x diagnosis_family"
    stratified_payload["auprc_comparable_to_natural_floor"] = True
    stratified_payload["observed_prevalence_shift"] = float(
        stratified_payload["positive_prevalence_after"]
        - stratified_payload["positive_prevalence_before"]
    )
    stratified_payload["comparability_note"] = (
        "No within-stratum downsampling is applied. Because eligibility filtering can "
        "still shift prevalence, Step 3 must report the floor recomputed on this view "
        "alongside the preregistered natural-population floor."
    )

    matched_payload = _view_payload(
        view="hard_case_matched",
        role="confound_control",
        before=frame,
        after=matched,
        selected=selected,
        warning=warning,
    )
    matched_payload.update(
        {
            "matching": "within age_bucket x diagnosis_family",
            "k_neg_per_pos": MATCH_NEGATIVES_PER_POSITIVE,
            "seed": MATCH_SEED,
            "baselines_must_be_recomputed_on_this_prevalence": True,
        }
    )

    preregistration = {
        "primary_lift_view": "hard_case_stratified",
        "confound_control_view": "hard_case_matched",
        "sanity_view": "full_structured",
        "no_drg_view": "no_drg_structured",
        "view_roles": {
            "full_structured": "upper_bound_only",
            "no_drg_structured": "lower_bound_only",
            "hard_case_stratified": "primary_lift_reading_natural_prevalence",
            "hard_case_matched": "confound_control_delta_at_matched_prevalence",
        },
        "style_primary": "structured",
        "style_ablation": "fluent",
        "baseline_prevalence": float(baseline_prevalence),
        "drg_rule_floor": float(drg_rule_floor),
        "decision_locked_before_encoding": True,
        "matched_metric_rule": (
            "on matched view, recompute ALL baselines and drg floor at matched "
            "prevalence; verdict is delta, never absolute AUPRC compared across prevalences"
        ),
        "stratified_metric_caveat": (
            "stratified applies no within-stratum downsampling, but eligibility filtering "
            "may shift prevalence; report a floor recomputed on the stratified view "
            "alongside the natural-population floor"
        ),
        "hard_case_loss_rate_rule": {
            "continue_if_positive_loss_rate_lte": POSITIVE_LOSS_LIMIT,
            "stop_and_review_if_positive_loss_rate_gt": POSITIVE_LOSS_LIMIT,
        },
        "min_per_class_selected": selected,
        "blocking_warning": warning,
    }
    return {
        "threshold_sweep": sweep,
        "hard_case_stratified_index": stratified_payload,
        "hard_case_matched_index": matched_payload,
        "eval_preregistration": preregistration,
    }


def write_eval_view_artifacts(
    source_path: str | Path,
    proxy_audit_path: str | Path,
    output_dir: str | Path,
) -> dict[str, dict[str, Any]]:
    """Build all Step-2.4.2 artifacts from the existing canonical adapter."""
    proxy = json.loads(Path(proxy_audit_path).read_text(encoding="utf-8"))
    payloads = build_eval_views(
        load_canonical(source_path, include_apr=False),
        baseline_prevalence=float(proxy["baseline_prevalence"]),
        drg_rule_floor=float(proxy["drg_rule_auprc_floor"]),
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (output / f"{name}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    (output / "hard_case_audit.md").write_text(
        render_hard_case_audit(payloads),
        encoding="utf-8",
    )
    return payloads


def render_hard_case_audit(payloads: dict[str, dict[str, Any]]) -> str:
    """Render loss, population, psych, and metric-comparability guardrails."""
    sweep = payloads["threshold_sweep"]
    stratified = payloads["hard_case_stratified_index"]
    matched = payloads["hard_case_matched_index"]
    rows = [
        "| min/class | N after | Positives | Negatives | Positive loss | Prevalence | Strata |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in sweep["thresholds"]:
        rows.append(
            f"| {item['min_per_class']} | {item['n_after']} | "
            f"{item['class_counts_after'][TARGET_CLASS]} | "
            f"{item['class_counts_after']['non_aval']} | "
            f"{item['loss_rate_positive']:.2%} | "
            f"{item['positive_prevalence_after']:.2%} | {item['n_strata_after']} |"
        )

    lines = [
        "# Gate 1-B hard-case population audit",
        "",
        "## Threshold sweep",
        "",
        *rows,
        "",
        f"Selected `min_per_class={sweep['min_per_class_selected']}`.",
        "",
    ]
    if sweep["blocking_warning"]:
        lines.extend([f"**BLOCKING WARNING:** {sweep['blocking_warning']}", ""])
    lines.extend(_view_markdown("Stratified primary lift view", stratified))
    lines.extend(_view_markdown("Matched confound-control view", matched))
    lines.extend(
        [
            "## Top retained strata by positive volume",
            "",
            *_strata_markdown(stratified["top_retained_positive_strata"]),
            "",
            "## Top dropped positive strata",
            "",
            *_strata_markdown(stratified["top_dropped_positive_strata"]),
            "",
            "## Age distribution after stratification",
            "",
            *[
                f"- {bucket}: {count}"
                for bucket, count in stratified["age_bucket_distribution_after"].items()
            ],
            "",
            "## Psych / self-harm check",
            "",
            f"Detected admissions: {stratified['psych_self_harm_check']['count']}; "
            f"aval rate: {stratified['psych_self_harm_check']['aval_rate']:.2%}; "
            f"share of retained positives: "
            f"{stratified['psych_self_harm_check']['share_of_positive_after']:.2%}.",
        ]
    )
    if stratified["psych_self_harm_check"]["warning"]:
        lines.extend([f"**WARNING:** {stratified['psych_self_harm_check']['warning']}", ""])
    else:
        lines.append("")
    lines.extend(
        [
            "## Interpretation guardrail",
            "",
            "- `loss_rate_positive <= 0.50`: view usable for Step 3.",
            "- If every threshold has `loss_rate_positive > 0.50`, do not encode before "
            "human review of a coarser diagnosis family.",
            "- If the retained population is mostly 70+, interpret the result as "
            "institutional downstream care among older patients with comparable diagnoses, "
            "not general downstream disposition.",
            "",
            "## AUPRC comparability",
            "",
            "The stratified view retains all rows in eligible strata and is the primary "
            "lift reading without within-stratum downsampling. Eligibility filtering changed "
            f"prevalence by {stratified['observed_prevalence_shift']:+.2%}; Step 3 must "
            "therefore report a floor recomputed on this view alongside the preregistered "
            "natural-population floor. The matched view changes prevalence by design: "
            "Step 3 must recompute every trivial baseline and the DRG floor on that matched "
            "population. Its verdict is a same-prevalence delta, never an absolute AUPRC "
            "comparison with the natural-population floor.",
            "",
        ]
    )
    return "\n".join(lines)


def _prepare_frame(canonical: pd.DataFrame) -> pd.DataFrame:
    required = {"stay_id", "age_group", "ccsr_diagnosis", "target_disposition"}
    missing = required.difference(canonical.columns)
    if missing:
        raise ValueError(f"hard-case input missing canonical columns: {sorted(missing)}")
    frame = pd.DataFrame(index=canonical.index)
    frame["stay_id"] = canonical["stay_id"].astype(int)
    frame["age_bucket"] = canonical["age_group"].map(_normalize_age)
    frame["diagnosis_family"] = canonical["ccsr_diagnosis"].map(_normalize_diagnosis)
    frame["is_positive"] = canonical["target_disposition"].eq(TARGET_CLASS)
    if frame["stay_id"].duplicated().any():
        raise ValueError("stay_id must be unique for stable hard-case indexes")
    return frame


def _normalize_age(value: object) -> str:
    if pd.isna(value) or not str(value).strip() or str(value).strip().casefold() == "unknown":
        return "MISSING_AGE_BUCKET"
    return " ".join(str(value).strip().split()).upper()


def _normalize_diagnosis(value: object) -> str:
    if pd.isna(value) or not str(value).strip() or str(value).strip().casefold() == "unknown":
        return MISSING_DIAG_FAMILY
    return " ".join(str(value).strip().split()).upper()


def _stratum_counts(frame: pd.DataFrame) -> pd.DataFrame:
    counts = (
        frame.groupby(["age_bucket", "diagnosis_family"], dropna=False)["is_positive"]
        .agg(["count", "sum"])
        .reset_index()
        .rename(columns={"sum": "positive_count"})
    )
    counts["negative_count"] = counts["count"] - counts["positive_count"]
    return counts


def _eligible_strata(frame: pd.DataFrame, threshold: int) -> pd.DataFrame:
    counts = _stratum_counts(frame)
    return counts.loc[
        (counts["positive_count"] >= threshold)
        & (counts["negative_count"] >= threshold),
        ["age_bucket", "diagnosis_family"],
    ]


def _threshold_summary(frame: pd.DataFrame, threshold: int) -> dict[str, Any]:
    eligible = _eligible_strata(frame, threshold)
    after = frame.merge(eligible, on=["age_bucket", "diagnosis_family"], how="inner")
    positive_before = int(frame["is_positive"].sum())
    negative_before = int(len(frame) - positive_before)
    positive_after = int(after["is_positive"].sum())
    negative_after = int(len(after) - positive_after)
    return {
        "min_per_class": threshold,
        "n_after": int(len(after)),
        "class_counts_after": {
            TARGET_CLASS: positive_after,
            "non_aval": negative_after,
        },
        "loss_rate_positive": _loss_rate(positive_before, positive_after),
        "loss_rate_negative": _loss_rate(negative_before, negative_after),
        "positive_prevalence_after": _ratio(positive_after, len(after)),
        "n_strata_after": int(len(eligible)),
    }


def _select_threshold(rows: list[dict[str, Any]]) -> tuple[int, bool]:
    passing = [
        int(row["min_per_class"])
        for row in rows
        if float(row["loss_rate_positive"]) <= POSITIVE_LOSS_LIMIT
    ]
    return (min(passing), False) if passing else (min(THRESHOLDS), True)


def _matched_sample(stratified: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(MATCH_SEED)
    selected: list[int] = []
    groups = stratified.groupby(["age_bucket", "diagnosis_family"], sort=True)
    for _, group in groups:
        positives = group.loc[group["is_positive"], "stay_id"].to_numpy(dtype=int)
        negatives = group.loc[~group["is_positive"], "stay_id"].to_numpy(dtype=int)
        take = min(len(negatives), MATCH_NEGATIVES_PER_POSITIVE * len(positives))
        sampled_negatives = rng.choice(negatives, size=take, replace=False)
        selected.extend(positives.tolist())
        selected.extend(sampled_negatives.tolist())
    selected_ids = set(int(stay_id) for stay_id in selected)
    return stratified.loc[stratified["stay_id"].isin(selected_ids)].copy()


def _view_payload(
    *,
    view: str,
    role: str,
    before: pd.DataFrame,
    after: pd.DataFrame,
    selected: int,
    warning: str | None,
) -> dict[str, Any]:
    positive_before = int(before["is_positive"].sum())
    negative_before = int(len(before) - positive_before)
    positive_after = int(after["is_positive"].sum())
    negative_after = int(len(after) - positive_after)
    counts = _stratum_counts(before)
    eligible = (counts["positive_count"] >= selected) & (counts["negative_count"] >= selected)
    dropped = counts.loc[~eligible].sort_values(
        ["positive_count", "count", "age_bucket", "diagnosis_family"],
        ascending=[False, False, True, True],
    )
    retained = counts.loc[eligible].sort_values(
        ["positive_count", "count", "age_bucket", "diagnosis_family"],
        ascending=[False, False, True, True],
    )
    psych = _psych_check(after, positive_after)
    return {
        "view": view,
        "role": role,
        "min_per_class_selected": selected,
        "index_contract": "stable stay_id only; target and source disposition are not serialized",
        "stay_ids": sorted(int(stay_id) for stay_id in after["stay_id"].tolist()),
        "n_total_before": int(len(before)),
        "n_total_after": int(len(after)),
        "class_counts_before": {
            TARGET_CLASS: positive_before,
            "non_aval": negative_before,
        },
        "class_counts_after": {
            TARGET_CLASS: positive_after,
            "non_aval": negative_after,
        },
        "loss_rate_total": _loss_rate(len(before), len(after)),
        "loss_rate_positive": _loss_rate(positive_before, positive_after),
        "loss_rate_negative": _loss_rate(negative_before, negative_after),
        "positive_prevalence_before": _ratio(positive_before, len(before)),
        "positive_prevalence_after": _ratio(positive_after, len(after)),
        "n_strata_before": int(len(counts)),
        "n_strata_after": int(after.groupby(["age_bucket", "diagnosis_family"]).ngroups),
        "top_dropped_positive_strata": _strata_records(dropped.head(20)),
        "top_retained_positive_strata": _strata_records(retained.head(20)),
        "age_bucket_distribution_after": _value_counts(after["age_bucket"]),
        "diagnosis_family_distribution_after_top20": _value_counts(
            after["diagnosis_family"], limit=20
        ),
        "psych_self_harm_check": psych,
        "blocking_warning": warning,
    }


def _psych_check(frame: pd.DataFrame, positive_after: int) -> dict[str, Any]:
    mask = frame["diagnosis_family"].str.contains(PSYCH_PATTERN, na=False)
    selected = frame.loc[mask, "is_positive"]
    count = int(len(selected))
    positive = int(selected.sum())
    share = _ratio(positive, positive_after)
    warning = None
    if share > 0.10:
        warning = (
            "Psych/self-harm represents a non-trivial share of positives; product "
            "interpretation may differ from SSR/rehab-oriented aval."
        )
    return {
        "count": count,
        "aval_count": positive,
        "aval_rate": _ratio(positive, count),
        "share_of_positive_after": share,
        "warning": warning,
        "automatic_exclusion": False,
    }


def _strata_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "age_bucket": str(row.age_bucket),
            "diagnosis_family": str(row.diagnosis_family),
            "count": int(row.count),
            "positive_count": int(row.positive_count),
            "negative_count": int(row.negative_count),
        }
        for row in frame.itertuples()
    ]


def _value_counts(series: pd.Series, limit: int | None = None) -> dict[str, int]:
    counts = series.value_counts().sort_values(ascending=False)
    if limit is not None:
        counts = counts.head(limit)
    return {str(key): int(value) for key, value in counts.items()}


def _view_markdown(title: str, payload: dict[str, Any]) -> list[str]:
    return [
        f"## {title}",
        "",
        f"- N: {payload['n_total_before']} -> {payload['n_total_after']}",
        f"- Classes before: {payload['class_counts_before']}",
        f"- Classes after: {payload['class_counts_after']}",
        f"- Loss total: {payload['loss_rate_total']:.2%}",
        f"- Loss positive: {payload['loss_rate_positive']:.2%}",
        f"- Loss negative: {payload['loss_rate_negative']:.2%}",
        f"- Positive prevalence: {payload['positive_prevalence_before']:.2%} -> "
        f"{payload['positive_prevalence_after']:.2%}",
        f"- Strata: {payload['n_strata_before']} -> {payload['n_strata_after']}",
        "",
    ]


def _strata_markdown(records: list[dict[str, Any]]) -> list[str]:
    rows = [
        "| Age | Diagnosis family | Total | Positive | Negative |",
        "|---|---|---:|---:|---:|",
    ]
    rows.extend(
        f"| {row['age_bucket']} | {row['diagnosis_family']} | {row['count']} | "
        f"{row['positive_count']} | {row['negative_count']} |"
        for row in records
    )
    return rows


def _loss_rate(before: int, after: int) -> float:
    return float(1.0 - after / before) if before else 0.0


def _ratio(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0
