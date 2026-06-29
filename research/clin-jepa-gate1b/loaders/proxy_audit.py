"""Audit obvious age and diagnosis proxies before Gate 1-B model evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from loaders.sparcs_adapter import TARGET_CLASS, load_canonical

DRG_RULE_RATE_THRESHOLD = 0.5
OLDER_AGE_BUCKET = "70 or Older"
TOP_GROUPS = 20
TOP_SHARE_GROUPS = 10


def compute_proxy_audit(frame: pd.DataFrame) -> dict[str, Any]:
    """Compute descriptive proxy strength without fitting a predictive model."""
    required = {"age_group", "apr_drg", "ccsr_diagnosis", "target_disposition"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"proxy audit missing canonical columns: {sorted(missing)}")

    work = frame.loc[:, sorted(required)].copy()
    work["is_aval_institu"] = work["target_disposition"].eq(TARGET_CLASS)
    target = work["is_aval_institu"].astype(int)
    positive_count = int(target.sum())
    total = int(len(work))
    prevalence = float(positive_count / total) if total else 0.0

    age_distribution = _rate_table(work, "age_group")
    older = work["age_group"].astype(str).str.strip().eq(OLDER_AGE_BUCKET)
    older_stats = _binary_group_stats(work, older)
    other_stats = _binary_group_stats(work, ~older)

    drg_audit = _diagnosis_audit(work, "apr_drg", positive_count)
    diagnosis_audit = _diagnosis_audit(work, "ccsr_diagnosis", positive_count)

    drg_rates = work.groupby("apr_drg", dropna=False)["is_aval_institu"].mean()
    drg_rule_scores = work["apr_drg"].map(drg_rates).gt(DRG_RULE_RATE_THRESHOLD).astype(int)
    rule_metrics = _binary_rule_metrics(target, drg_rule_scores)

    return {
        "schema_version": 1,
        "source_rows": total,
        "target_class": TARGET_CLASS,
        "positive_count": positive_count,
        "baseline_prevalence": prevalence,
        "age_proxy": {
            "distribution": age_distribution,
            "seventy_plus": older_stats,
            "other_ages": other_stats,
            "rate_gap": float(older_stats["aval_rate"] - other_stats["aval_rate"]),
        },
        "diagnosis_proxies": {
            "apr_drg": drg_audit,
            "ccsr_diagnosis": diagnosis_audit,
        },
        "top10_drg_positive_share": drg_audit["top10_positive_volume_share"],
        "drg_rule": {
            "definition": "predict aval_institu when empirical APR-DRG aval rate > 0.5",
            "rate_threshold": DRG_RULE_RATE_THRESHOLD,
            **rule_metrics,
        },
        "drg_rule_auprc_floor": rule_metrics["auprc"],
        "interpretation_policy": {
            "technical_leak": False,
            "reason": (
                "Age and diagnosis are admissible source fields, but can be "
                "quasi-deterministic proxies for discharge destination."
            ),
            "gate_question": (
                "Does the embedding add lift beyond obvious age and diagnosis proxies?"
            ),
            "hard_case_evaluation_required": True,
        },
    }


def write_proxy_audit(
    source_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Compute the audit on a real extract and write JSON plus human-readable Markdown."""
    audit = compute_proxy_audit(load_canonical(source_path, include_apr=False))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "proxy_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output / "proxy_audit.md").write_text(
        render_proxy_audit_markdown(audit),
        encoding="utf-8",
    )
    return audit


def render_proxy_audit_markdown(audit: dict[str, Any]) -> str:
    """Render the preregistration-facing interpretation of proxy strength."""
    age = audit["age_proxy"]
    drg = audit["diagnosis_proxies"]["apr_drg"]
    quasi = [row for row in drg["top20_by_rate"] if row["aval_rate"] > 0.5]
    quasi_lines = [
        f"- {row['group']}: {row['aval_rate']:.1%} aval "
        f"({row['aval_count']}/{row['count']})"
        for row in quasi
    ] or ["- Aucun APR-DRG au-dessus de 50% dans cet extract."]
    age_rows = [
        "| Age bucket | Admissions | aval_institu | Taux aval |",
        "|---|---:|---:|---:|",
    ]
    age_rows.extend(
        f"| {row['group']} | {row['count']} | {row['aval_count']} | {row['aval_rate']:.2%} |"
        for row in age["distribution"]
    )
    volume_rows = [
        "| APR-DRG | Admissions | aval_institu | Taux aval |",
        "|---|---:|---:|---:|",
    ]
    volume_rows.extend(
        f"| {row['group']} | {row['count']} | {row['aval_count']} | {row['aval_rate']:.2%} |"
        for row in drg["top20_by_positive_volume"]
    )

    return "\n".join(
        [
            "# Gate 1-B proxy audit",
            "",
            "## Question preregistree",
            "",
            "Gate 1-B ne demande plus seulement si `aval_institu` est previsible. "
            "Il demande si l'embedding apporte un lift au-dela des proxies evidents age + DRG.",
            "",
            f"Extract reel: **{audit['source_rows']}** admissions; prevalence aval: "
            f"**{audit['baseline_prevalence']:.2%}**.",
            "",
            "## Proxy age",
            "",
            *age_rows,
            "",
            f"Les 70+ ont un taux aval de **{age['seventy_plus']['aval_rate']:.2%}** "
            f"contre **{age['other_ages']['aval_rate']:.2%}** pour les autres ages "
            f"(ecart {age['rate_gap']:+.2%}). L'age cree donc une separation forte "
            "qui devra figurer dans les baselines triviales.",
            "",
            "## Proxy APR-DRG",
            "",
            "APR-DRG quasi-deterministes observes (taux aval > 50%; aucun seuil de support "
            "n'est applique dans cette statistique descriptive):",
            "",
            *quasi_lines,
            "",
            f"Les 10 APR-DRG au plus fort volume positif expliquent **"
            f"{audit['top10_drg_positive_share']:.2%}** de la classe aval.",
            "",
            "Top 20 APR-DRG par volume aval:",
            "",
            *volume_rows,
            "",
            "## Plancher AUPRC de la regle DRG",
            "",
            f"La regle binaire sans modele (predire aval lorsque le taux empirique du DRG "
            f"depasse 50%) atteint une AUPRC de **{audit['drg_rule_auprc_floor']:.4f}**, "
            f"contre une prevalence de **{audit['baseline_prevalence']:.4f}**. "
            "Cette AUPRC est la barre proxy, pas la seule prevalence.",
            "",
            "## Portee",
            "",
            "Ce signal n'est **pas une fuite technique**: age et diagnostic sont des champs "
            "sources admissibles et distincts de la disposition. Il est toutefois "
            "quasi-deterministe pour certains profils. Un GO sur la vue complete serait "
            "donc ininterpretable: l'embedding pourrait seulement relire le DRG. Une "
            "evaluation hard-case, preregistree avant tout encodage, est necessaire pour "
            "mesurer un lift au-dela d'age + famille diagnostique.",
            "",
        ]
    )


def _rate_table(frame: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    grouped = (
        frame.groupby(column, dropna=False)["is_aval_institu"]
        .agg(["count", "sum", "mean"])
        .reset_index()
        .rename(columns={column: "group", "sum": "aval_count", "mean": "aval_rate"})
        .sort_values(["count", "group"], ascending=[False, True])
    )
    return _records(grouped)


def _diagnosis_audit(
    frame: pd.DataFrame,
    column: str,
    total_positive_count: int,
) -> dict[str, Any]:
    grouped = (
        frame.groupby(column, dropna=False)["is_aval_institu"]
        .agg(["count", "sum", "mean"])
        .reset_index()
        .rename(columns={column: "group", "sum": "aval_count", "mean": "aval_rate"})
    )
    by_rate = grouped.sort_values(
        ["aval_rate", "aval_count", "count", "group"],
        ascending=[False, False, False, True],
    )
    by_volume = grouped.sort_values(
        ["aval_count", "aval_rate", "count", "group"],
        ascending=[False, False, False, True],
    )
    top_positive = int(by_volume.head(TOP_SHARE_GROUPS)["aval_count"].sum())
    return {
        "group_column": column,
        "group_count": int(len(grouped)),
        "top20_by_rate": _records(by_rate.head(TOP_GROUPS)),
        "top20_by_positive_volume": _records(by_volume.head(TOP_GROUPS)),
        "top10_positive_count": top_positive,
        "top10_positive_volume_share": (
            float(top_positive / total_positive_count) if total_positive_count else 0.0
        ),
    }


def _binary_group_stats(frame: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    selected = frame.loc[mask, "is_aval_institu"]
    count = int(len(selected))
    positive = int(selected.sum())
    return {
        "count": count,
        "aval_count": positive,
        "aval_rate": float(positive / count) if count else 0.0,
    }


def _binary_rule_metrics(target: pd.Series, scores: pd.Series) -> dict[str, Any]:
    y = target.astype(int).reset_index(drop=True)
    score = scores.astype(int).reset_index(drop=True)
    predicted = score.eq(1)
    tp = int((predicted & y.eq(1)).sum())
    fp = int((predicted & y.eq(0)).sum())
    fn = int((~predicted & y.eq(1)).sum())
    return {
        "auprc": _average_precision_binary(y.tolist(), score.tolist()),
        "predicted_positive_count": int(predicted.sum()),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": float(tp / (tp + fp)) if tp + fp else 0.0,
        "recall": float(tp / (tp + fn)) if tp + fn else 0.0,
    }


def _average_precision_binary(target: Iterable[int], scores: Iterable[int]) -> float:
    """Average precision with tie groups, equivalent to stepwise PR integration."""
    pairs = [(int(score), int(label)) for label, score in zip(target, scores, strict=True)]
    positives = sum(label for _, label in pairs)
    if positives == 0:
        return 0.0
    average_precision = 0.0
    previous_recall = 0.0
    for threshold in sorted({score for score, _ in pairs}, reverse=True):
        selected = [label for score, label in pairs if score >= threshold]
        true_positive = sum(selected)
        precision = true_positive / len(selected)
        recall = true_positive / positives
        average_precision += (recall - previous_recall) * precision
        previous_recall = recall
    return float(average_precision)


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "group": "<NULL>" if pd.isna(row.group) else str(row.group),
            "count": int(row.count),
            "aval_count": int(row.aval_count),
            "aval_rate": float(row.aval_rate),
        }
        for row in frame.itertuples()
    ]
