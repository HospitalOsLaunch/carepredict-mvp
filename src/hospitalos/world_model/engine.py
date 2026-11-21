"""Produce public noon forecasts on request and reveal only the confirmed synthetic outcome."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

import numpy as np

from .contracts import Context, Entry, Observation, Option, Session, Ward
from .physics import DATA, ModelUnavailable, learned_stocks, rollout, verified
from .projection import reconstruct


@dataclass(frozen=True)
class Case:
    context: Context
    wards: tuple[str, ...]
    publication: int
    public_sha: str
    events_sha: str


@lru_cache(maxsize=1)
def manifest() -> dict[str, Any]:
    try:
        metadata = json.loads((DATA / "manifest.json").read_text())
        if not isinstance(metadata, dict):
            raise ValueError("Invalid bundle")
        if not all(metadata[k] for k in ("version", "kernel_sha256", "weights_sha256", "cases")):
            raise ValueError("Incomplete bundle")
        return metadata
    except (KeyError, OSError, ValueError, TypeError) as exc:
        raise ModelUnavailable("Le manifeste de la démo est indisponible.") from exc


@lru_cache(maxsize=1)
def cases() -> dict[str, Case]:
    all_cases = {}
    try:
        for row in manifest()["cases"]:
            labels = tuple(row["wards"])
            context = Context(
                id=row["id"], label=row["label"], feed=row["feed"], ward_count=len(labels)
            )
            if (
                not 4 <= len(labels) <= 8
                or not all(isinstance(label, str) and label for label in labels)
                or len(set(labels)) != len(labels)
                or context.id in all_cases
                or not context.id.isascii()
                or not context.id.isalnum()
                or row["published_hour"] != (18 if context.feed == "delayed" else 16)
            ):
                raise ValueError("Incompatible context or publication time")
            all_cases[context.id] = Case(
                context, labels, row["published_hour"], row["public_sha"], row["events_sha"]
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise ModelUnavailable("Le catalogue des contextes est incohérent.") from exc
    return all_cases


def revision(case: Case) -> str:
    info = manifest()
    identity = [
        info["version"],
        info["kernel_sha256"],
        info["weights_sha256"],
        case.public_sha,
        case.events_sha,
        case.publication,
        case.wards,
        case.context.model_dump(mode="json"),
    ]
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def arrays(case: Case, scope: Literal["public", "events"]) -> dict[str, np.ndarray]:
    expected = case.public_sha if scope == "public" else case.events_sha
    path = verified(DATA / f"{case.context.id}_{scope}.npz", expected)
    try:
        with np.load(path, allow_pickle=False) as archive:
            return dict(archive)
    except (OSError, ValueError) as exc:
        raise ModelUnavailable("Le scénario de démonstration est illisible.") from exc


def queue(stocks: np.ndarray) -> np.ndarray:
    # Two different groups of patients: waiting for rehabilitation or for an internal transfer.
    return np.asarray(stocks[..., 2] + stocks[..., 4])


@lru_cache(maxsize=8)
def public_projection(context_id: str) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray]:
    data = arrays(cases()[context_id], "public")
    info = manifest()
    metrics, stocks = rollout(
        data, data["initial"], data["drivers"], data["schedules"], info["kernel_sha256"]
    )
    neural = learned_stocks(data, metrics, stocks, info["weights_sha256"])
    return data, stocks, neural


def shift_label(kind: int, dest: int, donor: int, wards: tuple[str, ...]) -> str:
    if kind == 6:
        return f"Prêt infirmier de {wards[donor]} à {wards[dest]}"
    family = {
        1: "Renfort infirmier",
        2: "Renfort aide-soignant",
        3: "Place en soins médicaux et de réadaptation",
        4: "Transport",
        5: "Bionettoyage",
    }
    return f"{family[kind]} · {wards[dest]}"


def open_session(identifier: str, case: Case) -> Session:
    data, physical, neural = public_projection(case.context.id)
    baseline = queue(physical)
    comparison = queue(neural)
    wards = [
        Ward(id=f"u{i + 1}", label=name, beds=int(data["beds"][i]))
        for i, name in enumerate(case.wards)
    ]
    options = []
    for i, (kind, dest, donor) in enumerate(data["actions"]):
        option_kind: Literal["reference", "transport", "cleaning"]
        if int(kind) == 0:
            option_kind, key, label, ward = (
                "reference",
                "reference",
                "Conserver le planning horaire",
                None,
            )
        else:
            option_kind = "transport" if int(kind) == 4 else "cleaning"
            ward = wards[dest].id
            key = f"{option_kind}-{ward}"
            label = shift_label(int(kind), int(dest), int(donor), case.wards)
        options.append(
            Option(
                id=key,
                label=label,
                kind=option_kind,
                ward_id=ward,
                forecast=float(baseline[i].sum()),
                jepa_forecast=float(comparison[i].sum()),
                by_ward=baseline[i].tolist(),
            )
        )
    morning = [shift_label(int(k), int(w), int(d), case.wards) for k, w, d in data["morning"] if k]
    return Session(
        id=identifier,
        context=case.context,
        phase="planning",
        hour=12,
        publication_hour=case.publication,
        model_version=manifest()["version"],
        morning_plan=morning,
        wards=wards,
        reference_id="reference",
        options=options,
        journal=[Entry(hour=12, event="opened")],
    )


def publish(session: Session, case: Case, now: int) -> None:
    if now < case.publication or session.selected_id is None:
        raise ValueError("Le relevé n’est pas disponible pour cette décision.")
    index = next(i for i, option in enumerate(session.options) if option.id == session.selected_id)
    data, forecasts, _ = public_projection(case.context.id)
    future = arrays(case, "events")
    # Simulate just the selected assignment, never return the simulator's counterfactual truth.
    _, actual = rollout(
        data,
        future["initial"],
        future["drivers"],
        data["schedules"][index : index + 1],
        manifest()["kernel_sha256"],
    )
    mask = future["mask"]
    reported = np.where(mask, actual[0], np.nan)
    estimated = reconstruct(
        forecasts, index, reported, mask, data["beds"], now=now, published=case.publication
    )
    for option, counts in zip(session.options, queue(estimated), strict=True):
        option.reconstruction = float(counts.sum())
        option.reconstructed_by_ward = counts.tolist()
    measured = queue(reported)
    ward_values = [float(x) if np.isfinite(x) else None for x in measured]
    session.observation = Observation(
        sample_hour=16,
        published_hour=case.publication,
        observed_stock=float(measured.sum()) if np.isfinite(measured).all() else None,
        by_ward=ward_values,
        visible_components=int(mask.sum()),
        total_components=mask.size,
    )
