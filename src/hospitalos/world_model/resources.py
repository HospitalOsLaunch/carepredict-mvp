"""Additional offers declared at noon, applied on top of the morning commitments."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from .contracts import Kind
from .physics import DATA, HORIZON, START_OFFSET, ModelUnavailable, rollout, verified


class Inventory(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    as_of_hour: Literal[12]
    through_hour: Literal[16]
    budget_eur: int = Field(ge=0)
    ide: list[int]
    as_pool: list[int]
    smr: list[int]
    equipped_beds: list[int]
    loan_routes: list[list[int]]


@dataclass(frozen=True)
class Offer:
    id: str
    kind: Kind
    mode: str
    ward: int
    label: str
    cost: int
    constraint: str
    eligible: bool
    donor: int = -1


def nurse_margin(tape: np.ndarray, state: np.ndarray) -> np.ndarray:
    census = state[:, 1] + state[:, 2] + state[:, 4]
    return np.asarray(tape[:, 7] - (12.0 + tape[:, 9] * census))


def noon_offers(
    context: str, wards: tuple[str, ...], inputs: dict[str, np.ndarray], artifact_sha: str
) -> list[Offer]:
    try:
        raw = json.loads(verified(DATA / "noon_offers.json", artifact_sha).read_text())
        inv = Inventory.model_validate(raw[context])
        groups = (inv.ide, inv.as_pool, inv.smr, inv.equipped_beds)
        if (
            any(len(set(g)) != len(g) for g in groups)
            or any(len(r) != 2 or r[0] == r[1] for r in inv.loan_routes)
            or len({tuple(r) for r in inv.loan_routes}) != len(inv.loan_routes)
        ):
            raise ValueError("Duplicate or invalid offer")
        if any(not 1 <= i <= len(wards) for g in (*groups, *inv.loan_routes) for i in g):
            raise ValueError("Unknown ward")
    except (KeyError, TypeError, OSError, ValueError) as exc:
        raise ModelUnavailable("Les disponibilités de midi sont illisibles.") from exc

    d = inputs["drivers"][0]
    state = inputs["initial"]
    margin = nurse_margin(d, state)
    census = state[:, 1] + state[:, 2] + state[:, 4]
    as_margin = d[:, 8] - (9.0 + d[:, 10] * census)
    offers = []

    def add(
        key: str,
        kind: Kind,
        mode: str,
        unit: int,
        label: str,
        cost: int,
        reason: str,
        available: bool = True,
        donor: int = -1,
    ) -> None:
        if cost > inv.budget_eur:
            reason = f"Budget restant {inv.budget_eur} €, coût requis {cost} €."
            available = False
        offers.append(Offer(key, kind, mode, unit, label, cost, reason, available, donor))

    for credential, units, label, cost in (
        ("ide", inv.ide, "Renfort infirmier (IDE)", 190),
        ("as", inv.as_pool, "Renfort aide-soignant (AS)", 140),
    ):
        for u in units:
            add(
                f"staffing-{credential}-u{u}",
                "staffing",
                credential,
                u - 1,
                f"{label} · {wards[u - 1]}",
                cost,
                "Renfort qualifié confirmé de 12 à 16 h. "
                f"Budget restant {inv.budget_eur} €.",
            )
    for src, dst in inv.loan_routes:
        free = margin[src - 1] >= 60 and d[src - 1, 7] >= 120
        reason = (
            "La couverture du donneur est vérifiée chaque heure."
            if free
            else "Marge IDE estimée chez le donneur inférieure aux 60 minutes requises à midi."
        )
        add(
            f"staffing-loan-u{src}-u{dst}",
            "staffing",
            "loan",
            dst - 1,
            f"Prêt IDE · {wards[src - 1]} vers {wards[dst - 1]}",
            0,
            reason,
            bool(free),
            src - 1,
        )
    for u in inv.smr:
        add(
            f"smr-u{u}",
            "smr",
            "smr",
            u - 1,
            f"Mobiliser une place SMR · {wards[u - 1]}",
            85,
            "Une place confirmée de 12 à 16 h. Le départ nécessite un transport.",
        )
    for u in inv.equipped_beds:
        covered = margin[u - 1] >= 14 and as_margin[u - 1] >= 9
        reason = (
            "Lit équipé. Marge IDE et AS estimée suffisante à midi."
            if covered
            else "Lit équipé. Marge IDE ou AS estimée insuffisante pour une admission à midi."
        )
        add(
            f"beds-u{u}",
            "beds",
            "bed",
            u - 1,
            f"Ouvrir un lit de réserve · {wards[u - 1]}",
            0,
            reason,
            bool(covered),
        )
    return offers


def capacities(data: dict[str, np.ndarray], offer: Offer | None) -> np.ndarray:
    beds = data["beds"].copy()
    if offer is not None and offer.mode == "bed":
        beds[offer.ward] += 1
    return beds


def simulate_offer(
    data: dict[str, np.ndarray], initial: np.ndarray, drivers: np.ndarray, offer: Offer, kernel: str
) -> tuple[np.ndarray, np.ndarray]:
    """Keep the original calendar. A single extra SMR place is a stock shared across four hours."""
    site = {**data, "beds": capacities(data, offer)}
    baseline = data["schedules"][:1]
    tape = drivers.copy()
    w = offer.ward
    if offer.mode in ("bed", "ide", "as"):
        if offer.mode == "ide":
            tape[:, w, 7] += 60
        elif offer.mode == "as":
            tape[:, w, 8] += 60
        metrics, stocks = rollout(site, initial, tape, baseline, kernel)
        return metrics[0], stocks[0]

    remaining = 1.0
    state = initial
    cumulative = np.zeros((len(state), 14))
    for t in range(HORIZON):
        row = tape[t]
        if offer.mode == "smr":
            ordinary = row[w, 6]
            # The morning calendar can already provide a distinct block of SMR capacity.
            if 5 <= START_OFFSET + t < 18 and tuple(baseline[0, 0, 1, :2]) == (3, w):
                ordinary += row[w, 14]
            row[w, 6] += remaining
        elif offer.mode == "loan":
            src = offer.donor
            if nurse_margin(row, state)[src] >= 60 and row[src, 7] >= 120:
                row[src, 7] -= 60
                row[w, 7] += 60
                cumulative[src, 11] += 1
            else:
                cumulative[src, 12] += 1
        else:
            raise ModelUnavailable("Intervention de midi inconnue.")
        metrics, stocks = rollout(
            site, state, tape[t : t + 1], baseline, kernel, start_offset=START_OFFSET + t, hours=1
        )
        if offer.mode == "smr":
            remaining = max(0.0, remaining - max(0.0, metrics[0, w, 6] - ordinary))
        cumulative += metrics[0]
        state = stocks[0]
    return cumulative, state
