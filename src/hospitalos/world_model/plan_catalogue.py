"""As-of-noon case list, named staff, and shared resources on the three synthetic sites."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, cast

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field

from . import engine
from .contracts import PlanAction, PlanKind
from .joint_physics import JointAction, JointCase, Mode
from .physics import DATA, ModelUnavailable, verified
from .resources import Inventory, nurse_margin


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PatientSlot(Record):
    id: str = Field(min_length=1)
    ward: int = Field(ge=1)
    kind: Literal["discharge", "admission"]
    known_hour: int = Field(ge=0)
    available_hour: int = Field(ge=12, lt=16)
    scheduled_hour: int = Field(ge=12, le=16)
    authorized: bool
    logistics_confirmed: bool
    source: Literal["census", "registered_direct_arrival"] = "census"


class Replacement(Record):
    ward: int = Field(ge=1)
    absence_confirmed: bool
    staff_confirmed: bool
    staff_id: str = Field(min_length=1)
    cost_eur: int = Field(ge=0)


class Redeployment(Record):
    from_ward: int = Field(ge=1)
    to_ward: int = Field(ge=1)
    staff_confirmed: bool
    staff_id: str = Field(min_length=1)


class Registry(Record):
    example_action_ids: list[str] = Field(default_factory=list)
    as_of_hour: Literal[12]
    cases: list[PatientSlot]
    replacement: Replacement
    redeployment: Redeployment


@dataclass(frozen=True)
class Item:
    description: PlanAction
    action: JointAction
    claim: str


@dataclass
class Catalogue:
    items: dict[str, Item]
    cases: tuple[JointCase, ...]
    data: dict[str, np.ndarray]
    budget: int
    example: tuple[str, ...]
    census_admissions: NDArray[np.int64]
    direct_arrivals: NDArray[np.int64]
    kernel: str


def reconcile_noon_intake(
    initial: NDArray[np.float64],
    census_admissions: NDArray[np.int64],
    direct_arrivals: NDArray[np.int64],
) -> NDArray[np.float64]:
    """Reconcile two noon sources before choosing or replaying any plan.

    Named people already in the census establish a lower bound on the aggregate queue.
    Registered direct arrivals are a separate source and enter the queue once.
    """
    reconciled = initial.copy()
    reconciled[:, 0] = np.maximum(initial[:, 0], census_admissions) + direct_arrivals
    return reconciled


@lru_cache(maxsize=8)
def catalogue(context: str) -> Catalogue:
    case = engine.cases()[context]
    info = engine.manifest()
    data = engine.public_projection(context).data
    verified(DATA.parent / "joint_kernel.cpp", info["joint_kernel_sha256"])
    try:
        reg_path = verified(DATA / "noon_cases.json", info["joint_registry_sha256"])
        reg = Registry.model_validate(json.loads(reg_path.read_bytes())[context])
        inv_path = verified(DATA / "noon_offers.json", info["noon_offer_sha256"])
        budget = Inventory.model_validate(json.loads(inv_path.read_bytes())[context]).budget_eur
        units = [p.ward for p in reg.cases] + [
            reg.replacement.ward,
            reg.redeployment.from_ward,
            reg.redeployment.to_ward,
        ]
        if max(units) > len(case.wards) or reg.redeployment.from_ward == reg.redeployment.to_ward:
            raise ValueError("Unavailable ward in register")
        if any(
            p.source == "registered_direct_arrival" and p.kind != "admission" for p in reg.cases
        ):
            raise ValueError("Direct arrival must be an admission")
        if any(p.scheduled_hour < p.available_hour for p in reg.cases):
            raise ValueError("Contradictory authorization times")
    except (KeyError, OSError, ValueError, TypeError) as exc:
        raise ModelUnavailable(
            "Registre des patients et des équipes de midi indisponible."
        ) from exc

    items: dict[str, Item] = {}
    cases = []
    census_admissions = np.zeros(len(case.wards), dtype=np.int64)
    direct_arrivals = np.zeros(len(case.wards), dtype=np.int64)

    def add(
        action: JointAction,
        kind: PlanKind,
        label: str,
        unit: str,
        claim: str,
        condition: str,
        *,
        cost: int = 0,
        eligible: bool = True,
        start: int = 12,
    ) -> None:
        if action.id in items:
            raise ModelUnavailable("Identifiant d’intervention dupliqué.")
        if cost > budget:
            eligible = False
            condition = f"Budget restant {budget} €, coût de cette affectation {cost} €."
        public = PlanAction(
            id=action.id,
            kind=kind,
            label=label,
            quantity=1,
            unit=unit,
            ward_id=f"u{action.ward + 1}",
            start_hour=start,
            end_hour=16,
            cost_eur=cost,
            eligible=eligible,
            constraint=condition,
        )
        items[action.id] = Item(public, action, claim)

    for p in reg.cases:
        if p.known_hour > 12:
            continue
        w = p.ward - 1
        discharge = p.kind == "discharge"
        eligible = p.authorized and p.logistics_confirmed
        if p.source == "registered_direct_arrival" and eligible:
            direct_arrivals[w] += 1
        if p.source == "census" and p.kind == "admission":
            census_admissions[w] += 1
        if eligible or p.source == "census":
            cases.append(
                JointCase(
                    id=p.id,
                    direction=p.kind,
                    ward=w,
                    available_hour=p.available_hour,
                    scheduled_hour=p.scheduled_hour if eligible else 16,
                )
            )
        prefix = (
            "Coordonner la sortie"
            if discharge
            else "Avancer l’entrée programmée"
            if p.source == "registered_direct_arrival"
            else "Avancer l’entrée"
        )
        condition = (
            f"{'Sortie autorisée' if discharge else 'Demande acceptée'}, "
            f"créneau habituel {p.scheduled_hour} h. "
            + (
                "Transport et soins de sortie requis."
                if discharge
                else "Accueil sous réserve de lit propre et de disponibilité soignante."
            )
        )
        add(
            JointAction(p.id, p.kind, w, patient_id=p.id),
            p.kind,
            f"{prefix} {p.id} · {case.wards[w]}",
            "patient",
            "patient:" + p.id,
            condition if eligible else "Autorisation ou accord logistique manquant à midi.",
            eligible=eligible,
            start=p.available_hour,
        )

    replacement = reg.replacement
    w = replacement.ward - 1
    confirmed = replacement.absence_confirmed and replacement.staff_confirmed
    add(
        JointAction("replacement-ide", "replacement", w),
        "replacement",
        f"Remplacer l’IDE absente · {case.wards[w]}",
        "personne",
        "staff:" + replacement.staff_id,
        "Absence comptée dans le planning. Remplaçant IDE confirmé pour 12–16 h."
        if confirmed
        else "Le remplacement IDE n’a pas de confirmation à midi.",
        cost=replacement.cost_eur,
        eligible=confirmed,
    )
    red = reg.redeployment
    src, dst = red.from_ward - 1, red.to_ward - 1
    add(
        JointAction("redeploy-as", "redeploy", dst, donor=src),
        "redeployment",
        f"Réaffecter une AS · {case.wards[src]} → {case.wards[dst]}",
        "personne",
        "staff:" + red.staff_id,
        "AS identifiée. Le plan doit couvrir les soins dans l’unité prêteuse."
        if red.staff_confirmed
        else "Aide-soignante indisponible.",
        eligible=red.staff_confirmed,
    )

    for k, dest, _ in data["actions"]:
        if not k:
            continue
        kind: Literal["transport", "cleaning"] = "transport" if int(k) == 4 else "cleaning"
        w = int(dest)
        key = f"{kind}-u{w + 1}"
        add(
            JointAction(key, kind, w, start_hour=14),
            kind,
            engine.shift_label(int(k), w, -1, case.wards),
            "équipe",
            "crew:" + kind,
            "Équipe partagée. Une seule unité peut être priorisée sur ce créneau.",
            start=14,
        )

    for offer in engine.public_projection(context).offers:
        if offer.mode in ("ide", "as"):
            group: PlanKind = "reinforcement"
            claim, unit = "staff:" + offer.mode.upper() + "-VIVIER", "personne"
            condition = "Renfort qualifié de 12 à 16 h, pour une seule unité."
        elif offer.mode == "loan":
            group, claim, unit = "redeployment", "staff:IDE-PRET", "personne"
            condition = "Prêt IDE autorisé sous réserve de la couverture de l’unité prêteuse."
        elif offer.mode == "bed":
            group, claim, unit = "beds", "bed:" + str(offer.ward), "lit"
            condition = "Lit de réserve équipé. Couverture IDE et AS vérifiée à l’échelle du plan."
        elif offer.mode == "smr":
            group, claim, unit = "smr", "seat:SMR", "place"
            condition = "Une place SMR partagée sur 12–16 h, avec transport disponible."
        else:
            raise ModelUnavailable("Famille d’offre de midi inconnue.")
        add(
            JointAction(offer.id, cast(Mode, offer.mode), offer.ward, donor=offer.donor),
            group,
            offer.label,
            unit,
            claim,
            condition,
            cost=offer.cost,
        )
    example_ids = set(reg.example_action_ids)
    known_ids = items.keys() | {p.id for p in reg.cases}
    if len(example_ids) != len(reg.example_action_ids) or not example_ids <= known_ids:
        raise ModelUnavailable("L’exemple de composition contient une intervention inconnue.")
    example = (
        tuple(reg.example_action_ids)
        if all(k in items and items[k].description.eligible for k in example_ids)
        else ()
    )
    initial = reconcile_noon_intake(data["initial"], census_admissions, direct_arrivals)
    return Catalogue(
        items,
        tuple(cases),
        {**data, "initial": initial},
        budget,
        example,
        census_admissions,
        direct_arrivals,
        info["kernel_sha256"],
    )


def conflicts(c: Catalogue, ids: tuple[str, ...]) -> list[str]:
    """Reserve named people, cases and equipment together before checking staffing margins."""
    selected = [c.items[k] for k in ids]
    errors = [
        f"{item.description.label} · {item.description.constraint}"
        for item in selected
        if not item.description.eligible
    ]
    cost = sum(item.description.cost_eur for item in selected)
    if cost > c.budget:
        errors.append(
            f"Budget dépassé de {cost - c.budget} € ({cost} € pour {c.budget} € disponibles)."
        )
    holders: dict[str, str] = {}
    for item in selected:
        if item.claim in holders:
            first = holders[item.claim]
            errors.append(f"Ressource engagée deux fois · {first} et {item.description.label}.")
        else:
            holders[item.claim] = item.description.label
    if errors:
        return errors
    moves = [item.action for item in selected if item.action.mode in ("loan", "redeploy")]
    opening = [item.action.ward for item in selected if item.action.mode == "bed"]
    if not moves and not opening:
        return []
    # Current staffing already excludes declared absences. Apply booked external shifts only once.
    d = c.data["drivers"][0]
    state = c.data["initial"]
    ide = nurse_margin(d, state)
    census = state[:, 1] + state[:, 2] + state[:, 4]
    aide = d[:, 8] - (9.0 + d[:, 10] * census)
    headroom = {"IDE": ide, "AS": aide}
    absolute = {"IDE": d[:, 7].copy(), "AS": d[:, 8].copy()}
    for item in selected:
        a = item.action
        if a.mode in ("ide", "as", "replacement"):
            role = "AS" if a.mode == "as" else "IDE"
            headroom[role][a.ward] += 60
            absolute[role][a.ward] += 60
    # Net incoming loans cannot be re-lent to finance a circular staffing plan.
    for a in moves:
        role = "AS" if a.mode == "redeploy" else "IDE"
        headroom[role][a.donor] -= 60
        absolute[role][a.donor] -= 60
        if headroom[role][a.donor] < -1e-7 or absolute[role][a.donor] < 60 - 1e-7:
            errors.append(
                f"{c.items[a.id].description.label} · marge {role} insuffisante chez le donneur."
            )
    for a in moves:
        headroom["AS" if a.mode == "redeploy" else "IDE"][a.ward] += 60
    for w in opening:
        if ide[w] < 14 - 1e-7 or aide[w] < 9 - 1e-7:
            errors.append(
                f"Lit en unité {w + 1} · couverture IDE ou AS insuffisante après réaffectation."
            )
    return errors
