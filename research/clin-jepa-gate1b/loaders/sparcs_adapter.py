"""SPARCS 2024 adapter and admission-time feature audit for Gate 1-B."""

from __future__ import annotations

import json
import logging
import re
import warnings
from pathlib import Path
from typing import Any

import pandas as pd

LOGGER = logging.getLogger(__name__)

CLASSES = ("domicile", "aval_institu", "autre")
TARGET_CLASS = "aval_institu"
MAJOR_UNMAPPED_PREVALENCE = 0.005

COLUMN_CANDIDATES: dict[str, tuple[str, ...]] = {
    "age_group": ("Age Group", "age_group"),
    "gender": ("Gender", "gender"),
    "race": ("Race", "race"),
    "ethnicity": ("Ethnicity", "ethnicity"),
    "apr_drg": ("APR DRG Description", "APR DRG Code", "apr_drg_description", "apr_drg_code"),
    "apr_severity": (
        "APR Severity of Illness Description",
        "APR Severity of Illness Code",
        "apr_severity_of_illness",
        "apr_severity_of_illness_code",
    ),
    "apr_risk_mortality": ("APR Risk of Mortality", "apr_risk_of_mortality"),
    "apr_medsurg": ("APR Medical Surgical Description", "apr_medical_surgical"),
    "ccsr_diagnosis": (
        "CCSR Diagnosis Description",
        "CCS Diagnosis Description",
        "ccsr_diagnosis_description",
    ),
    "type_admission": ("Type of Admission", "type_of_admission"),
    "ed_indicator": ("Emergency Department Indicator", "emergency_department_indicator"),
    "health_service_area": ("Health Service Area", "health_service_area"),
    "payment_typology": ("Payment Typology 1", "payment_typology_1"),
    "length_of_stay": ("Length of Stay", "length_of_stay"),
    "disposition_raw": ("Patient Disposition", "patient_disposition"),
}

# Every observed 2024 disposition is explicit. Unknown values remain unmapped.
DISPOSITION_MAP: dict[str, str] = {
    "Home or Self Care": "domicile",
    "Home w/ Home Health Services": "domicile",
    "Skilled Nursing Home": "aval_institu",
    "Inpatient Rehabilitation Facility": "aval_institu",
    "Hospice - Home": "aval_institu",
    "Psychiatric Hospital or Unit of Hosp": "aval_institu",
    "Hospice - Medical Facility": "aval_institu",
    "Facility w/ Custodial/Supportive Care": "aval_institu",
    "Medicare Cert Long Term Care Hospital": "aval_institu",
    "Medicaid Cert Nursing Facility": "aval_institu",
    "Cancer Center or Childrens Hospital": "aval_institu",
    "Hosp Basd Medicare Approved Swing Bed": "aval_institu",
    "Left Against Medical Advice": "autre",
    "Expired": "autre",
    "Short-term Hospital": "autre",
    "Another Type Not Listed": "autre",
    "Court/Law Enforcement": "autre",
    "Federal Health Care Facility": "autre",
    "Critical Access Hospital": "autre",
}

TABULAR_FEATURES_NO_APR = (
    "age_group",
    "gender",
    "race",
    "ethnicity",
    "apr_drg",
    "apr_medsurg",
    "ccsr_diagnosis",
    "type_admission",
    "ed_indicator",
    "health_service_area",
    "payment_typology",
)
APR_FEATURES = ("apr_severity", "apr_risk_mortality")
TABULAR_FEATURES = TABULAR_FEATURES_NO_APR

LEAK_PRONE_COLUMNS: dict[str, str] = {
    "length_of_stay": "post-stay outcome",
    "total_charges": "post-stay financial outcome",
    "total_costs": "post-stay financial outcome",
    "discharge_year": "discharge-dependent field",
    "patient_disposition": "prediction target only",
    "disposition_raw": "prediction target only",
    "target_disposition": "derived prediction target only",
    "aval_institu": "derived prediction target only",
    "target": "derived prediction target only",
    "label": "derived prediction target only",
    "mapped_class": "derived prediction target only",
    "discharge_date": "discharge-dependent field",
    "discharge_status": "discharge-dependent field",
}
LEAK_PRONE_PATTERNS = (
    re.compile(r"(^|_)length_of_stay($|_)"),
    re.compile(r"(^|_)(total_)?charges?($|_)"),
    re.compile(r"(^|_)(total_)?costs?($|_)"),
    re.compile(r"(^|_)discharge_(date|status|destination|year)($|_)"),
)
FORBIDDEN_CANONICAL_FEATURES = {
    "length_of_stay",
    "total_charges",
    "total_costs",
    "disposition_raw",
    "target_disposition",
}


class MajorDispositionUnmappedError(ValueError):
    """Raised when a material disposition is absent from the explicit map."""


def read_extract(path: str | Path) -> pd.DataFrame:
    """Read a SPARCS CSV or Parquet extract without coercing categorical values."""
    source = Path(path)
    if source.suffix.lower() == ".csv":
        return pd.read_csv(source, dtype=str, low_memory=False)
    if source.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(source)
    raise ValueError(f"unsupported SPARCS format: {source.suffix}")


def tabular_features(*, include_apr: bool = False) -> tuple[str, ...]:
    """Return the admission-time feature contract, excluding APR risk by default."""
    features = TABULAR_FEATURES_NO_APR + (APR_FEATURES if include_apr else ())
    leaked = FORBIDDEN_CANONICAL_FEATURES.intersection(features)
    if leaked:
        raise AssertionError(f"leak-prone fields entered feature contract: {sorted(leaked)}")
    return features


def disposition_value_counts(df: pd.DataFrame) -> pd.DataFrame:
    """Return real disposition counts before mapping, including null values."""
    column = _pick_column(df, COLUMN_CANDIDATES["disposition_raw"])
    if column is None:
        raise ValueError("Patient Disposition column is missing from SPARCS extract")
    raw_counts = df[column].value_counts(dropna=False)
    total = int(raw_counts.sum())
    rows: list[dict[str, Any]] = []
    for raw_value, count in raw_counts.items():
        value = _display_disposition(raw_value)
        mapped_class = DISPOSITION_MAP.get(value)
        rows.append(
            {
                "patient_disposition": value,
                "count": int(count),
                "prevalence": float(count / total) if total else 0.0,
                "mapped": mapped_class is not None,
                "mapped_class": mapped_class,
            }
        )
    return pd.DataFrame(rows).sort_values("count", ascending=False).reset_index(drop=True)


def mapping_audit_from_counts(counts: pd.DataFrame) -> dict[str, Any]:
    """Audit explicit mapping and identify material unknown dispositions."""
    total = int(counts["count"].sum())
    unmapped = counts.loc[~counts["mapped"]].copy()
    major = unmapped.loc[unmapped["prevalence"] >= MAJOR_UNMAPPED_PREVALENCE].copy()
    payload = {
        "total_count": total,
        "mapped_count": int(total - unmapped["count"].sum()),
        "unmapped_count": int(unmapped["count"].sum()),
        "unmapped_rate": float(unmapped["count"].sum() / total) if total else 0.0,
        "material_prevalence_threshold": MAJOR_UNMAPPED_PREVALENCE,
        "decision": "PASS" if major.empty else "FAIL",
        "unmapped_values": _records(unmapped),
        "material_unmapped_values": _records(major),
    }
    if not unmapped.empty:
        details = ", ".join(
            f"{row.patient_disposition}={row.prevalence:.2%}"
            for row in unmapped.itertuples()
        )
        warnings.warn(
            f"UNMAPPED SPARCS DISPOSITIONS: {details}; values remain unmapped",
            stacklevel=2,
        )
    return payload


def assert_material_dispositions_mapped(audit: dict[str, Any]) -> None:
    """Fail when any unknown disposition represents at least 0.5% of admissions."""
    material = audit["material_unmapped_values"]
    if material:
        details = ", ".join(
            f"{item['patient_disposition']}={item['prevalence']:.2%}" for item in material
        )
        raise MajorDispositionUnmappedError(
            "material SPARCS dispositions missing from DISPOSITION_MAP: " + details
        )


def class_distribution_from_counts(counts: pd.DataFrame) -> dict[str, Any]:
    """Compute mapped class prevalence and the no-skill AUPRC reference."""
    total = int(counts["count"].sum())
    mapped = counts.dropna(subset=["mapped_class"])
    grouped = mapped.groupby("mapped_class", dropna=False)["count"].sum().to_dict()
    class_counts = {label: int(grouped.get(label, 0)) for label in CLASSES}
    class_rates = {
        label: float(class_counts[label] / total) if total else 0.0 for label in CLASSES
    }
    prevalence = class_rates[TARGET_CLASS]
    warning_message: str | None = None
    if prevalence < 0.02:
        warning_message = "positive class too rare for stable Gate 1 decision"
        warnings.warn(warning_message, RuntimeWarning, stacklevel=2)
    elif prevalence < 0.10:
        warning_message = "AUPRC likely unstable; bootstrap CI required"
        warnings.warn(warning_message, RuntimeWarning, stacklevel=2)
    return {
        "total_count": total,
        "mapped_count": int(mapped["count"].sum()),
        "unmapped_count": int(total - mapped["count"].sum()),
        "class_counts": class_counts,
        "class_rates": class_rates,
        "aval_institu_rate": prevalence,
        "baseline_auprc_prevalence": prevalence,
        "warning": warning_message,
    }


def feature_audit(df: pd.DataFrame, *, include_apr: bool = False) -> dict[str, Any]:
    """Describe admitted features and every leak-prone source column excluded."""
    excluded = []
    for column in df.columns:
        normalized = _normalize_column(column)
        reason = LEAK_PRONE_COLUMNS.get(normalized)
        if reason is None and any(pattern.search(normalized) for pattern in LEAK_PRONE_PATTERNS):
            reason = "leak-prone post-stay field"
        if reason is not None:
            excluded.append({"source_column": str(column), "reason": reason})
    features = tabular_features(include_apr=include_apr)
    LOGGER.warning("excluded leak-prone columns: %s", excluded)
    if not include_apr:
        LOGGER.warning("conservative no_apr mode excludes: %s", APR_FEATURES)
    return {
        "active_configuration": "with_apr" if include_apr else "no_apr",
        "active_features": list(features),
        "configurations": {
            "no_apr": list(tabular_features(include_apr=False)),
            "with_apr": list(tabular_features(include_apr=True)),
        },
        "apr_fields_excluded_by_default": list(APR_FEATURES),
        "excluded_source_columns": excluded,
        "leak_blacklist": LEAK_PRONE_COLUMNS,
    }


def load_canonical(path: str | Path, *, include_apr: bool = False) -> pd.DataFrame:
    """Map a SPARCS extract to the Gate 1-B canonical stay schema."""
    raw = read_extract(path)
    counts = disposition_value_counts(raw)
    audit = mapping_audit_from_counts(counts)
    assert_material_dispositions_mapped(audit)

    output = pd.DataFrame(index=raw.index)
    output["stay_id"] = range(len(raw))
    disposition_column = _required_column(raw, COLUMN_CANDIDATES["disposition_raw"])
    normalized_disposition = raw[disposition_column].map(_display_disposition)
    output["target_disposition"] = normalized_disposition.map(DISPOSITION_MAP).astype("string")

    for canonical, candidates in COLUMN_CANDIDATES.items():
        if canonical == "disposition_raw":
            continue
        source = _pick_column(raw, candidates)
        if source is None:
            output[canonical] = "Unknown"
        else:
            output[canonical] = raw[source].astype("string").str.strip().fillna("Unknown")

    output["length_of_stay"] = pd.to_numeric(
        output["length_of_stay"].str.replace("+", "", regex=False),
        errors="coerce",
    )
    output.attrs["tabular_features"] = tabular_features(include_apr=include_apr)
    output.attrs["feature_configuration"] = "with_apr" if include_apr else "no_apr"
    return output


def write_audit_artifacts(
    *,
    source_path: str | Path,
    disposition_path: str | Path | None,
    output_dir: str | Path,
    include_apr: bool = False,
) -> dict[str, Any]:
    """Run mapping and feature audits and write all Step-1 artifacts."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    source = read_extract(source_path)
    disposition_source = read_extract(disposition_path) if disposition_path else source

    counts = disposition_value_counts(disposition_source)
    counts.to_csv(output / "disposition_value_counts.csv", index=False)
    mapping_audit = mapping_audit_from_counts(counts)
    _write_json(output / "mapping_audit.json", mapping_audit)

    class_distribution = class_distribution_from_counts(counts)
    _write_json(output / "class_distribution.json", class_distribution)

    features = feature_audit(source, include_apr=include_apr)
    features["source_rows"] = len(source)
    features["source_columns"] = [str(column) for column in source.columns]
    _write_json(output / "feature_audit.json", features)

    canonical = load_canonical(source_path, include_apr=include_apr)
    disposition_markdown = _disposition_markdown(counts, mapping_audit)
    (output / "disposition_audit.md").write_text(disposition_markdown, encoding="utf-8")
    summary = _summary_markdown(
        source_path=source_path,
        disposition_path=disposition_path,
        source_rows=len(source),
        canonical_rows=len(canonical),
        mapping_audit=mapping_audit,
        class_distribution=class_distribution,
        feature_audit_payload=features,
    )
    (output / "summary.md").write_text(summary, encoding="utf-8")

    assert_material_dispositions_mapped(mapping_audit)
    return {
        "mapping_audit": mapping_audit,
        "class_distribution": class_distribution,
        "feature_audit": features,
        "canonical_rows": len(canonical),
    }


def _pick_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    return next((candidate for candidate in candidates if candidate in df.columns), None)


def _required_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str:
    column = _pick_column(df, candidates)
    if column is None:
        raise ValueError(f"required SPARCS column missing; expected one of {candidates}")
    return column


def _display_disposition(value: object) -> str:
    if pd.isna(value):
        return "<NULL>"
    text = str(value).strip()
    return text if text else "<BLANK>"


def _normalize_column(column: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(column).strip().lower()).strip("_")


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "patient_disposition": str(row.patient_disposition),
            "count": int(row.count),
            "prevalence": float(row.prevalence),
        }
        for row in frame.itertuples()
    ]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _disposition_markdown(counts: pd.DataFrame, audit: dict[str, Any]) -> str:
    rows = ["| Disposition | Count | Prevalence | Mapping |", "|---|---:|---:|---|"]
    for row in counts.itertuples():
        rows.append(
            f"| {row.patient_disposition} | {row.count} | {row.prevalence:.3%} | "
            f"{row.mapped_class or 'UNMAPPED'} |"
        )
    return "\n".join(
        [
            "# SPARCS 2024 disposition audit",
            "",
            f"Decision: **{audit['decision']}**",
            f"Unmapped: {audit['unmapped_count']} ({audit['unmapped_rate']:.3%})",
            "Gate: every disposition with prevalence >= 0.5% must be explicit in DISPOSITION_MAP.",
            "",
            *rows,
            "",
        ]
    )


def _summary_markdown(
    *,
    source_path: str | Path,
    disposition_path: str | Path | None,
    source_rows: int,
    canonical_rows: int,
    mapping_audit: dict[str, Any],
    class_distribution: dict[str, Any],
    feature_audit_payload: dict[str, Any],
) -> str:
    return "\n".join(
        [
            "# SPARCS adapter Step 1 summary",
            "",
            f"- Feature extract: `{source_path}` ({source_rows} rows)",
            f"- Disposition audit source: `{disposition_path or source_path}`",
            f"- Canonical rows: {canonical_rows}",
            f"- Mapping decision: **{mapping_audit['decision']}**",
            f"- Unmapped: {mapping_audit['unmapped_count']} ({mapping_audit['unmapped_rate']:.3%})",
            f"- aval_institu: {class_distribution['aval_institu_rate']:.3%}",
            f"- No-skill AUPRC reference: {class_distribution['baseline_auprc_prevalence']:.4f}",
            f"- Active feature configuration: `{feature_audit_payload['active_configuration']}`",
            "",
            "## APR sensitivity",
            "",
            "`no_apr` is the primary conservative configuration. `with_apr` adds APR Severity "
            "and APR Risk of Mortality only when `--include-apr` is explicit.",
            "Predictive AUPRC comparison and bootstrap are deferred to Step 5.",
            "A future gain from `with_apr` must be treated as potentially dependent on "
            "information unavailable at admission.",
            "",
            "## Scope",
            "",
            "This step audits mapping, class prevalence, and feature leakage only. It does not "
            "train a predictor, compute model AUPRC, or bootstrap predictive metrics.",
            "",
        ]
    )
