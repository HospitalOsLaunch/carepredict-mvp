"""Private realisations for P5 (evaluation only; never given to the product planner).

Keyed innovations: u = H(commitment, partition, structure, parent, replicate, primitive, entity).
The regime is NOT in the key of the base uniforms: R1 and R2 share them and only the
transformation differs (P5-PROTO-2 § 3, "R1 et R2 partagent les innovations uniformes"); R2's
extra shifts use their own primitive names. The twin is not in the key either: both twins share
the innovations of a same entity (stay_id, bed_id, request_id, offer_key).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any

from hospitalos.decision_support.contracts import Distribution
from hospitalos.decision_support.reference_forecaster import PrivateTruth

from .generator import Episode, u01

REGIMES = ("R1", "R2")
R2_PARAMS = {
    "transport_lead_plus_1h_prob": 0.3,
    "cleaning_plus_1h_prob": 0.2,
    "requested_present_prob": 0.5,
    "within_pool_rho": 0.5,
}
_N = NormalDist()


@dataclass(frozen=True)
class Realisation:
    regime: str
    replicate: int
    truth: PrivateTruth
    presence: Mapping[str, int]  # offer_key -> 0/1


def inverse(dist: Distribution, u: float) -> int:
    total = sum(dist.weights)
    acc = 0
    for value, weight in zip(dist.support, dist.weights, strict=True):
        acc += weight
        if u < acc / total:
            return int(value)
    return int(dist.support[-1])


def _phi_inv(u: float) -> float:
    return _N.inv_cdf(min(max(u, 1e-12), 1 - 1e-12))


def presence_draw(
    regime: str, p_pub: float, confirmed: bool, u_offer: float, u_pool: float
) -> int:
    if confirmed:
        return 1
    if regime == "R1":
        return int(u_offer < p_pub)
    rho = R2_PARAMS["within_pool_rho"]
    z = rho**0.5 * _phi_inv(u_pool) + (1 - rho) ** 0.5 * _phi_inv(u_offer)
    return int(z < _phi_inv(R2_PARAMS["requested_present_prob"]))


def realise(
    episode: Episode, regime: str, replicate: int, commitment: str
) -> Realisation:
    if regime not in REGIMES:
        raise ValueError(regime)
    spec, snap = episode.spec, episode.snapshot
    base = (commitment, spec.partition, spec.structure_seed, spec.parent_index, replicate)
    values: dict[str, dict[str, int]] = {
        "readiness": {},
        "transport_lead": {},
        "cleaning": {},
        "cleaning_remaining": {},
        "arrival": {},
    }
    r2 = regime == "R2"
    for s in snap.stays:
        if s.ready_delay is not None:
            values["readiness"][s.stay_id] = inverse(s.ready_delay, u01(*base, "readiness", s.stay_id))
        if s.transport_lead is not None and s.transport_need in {"seated", "stretcher"}:
            lead = inverse(s.transport_lead, u01(*base, "transport_lead", s.stay_id))
            if r2 and u01(*base, "r2_transport", s.stay_id) < R2_PARAMS["transport_lead_plus_1h_prob"]:
                lead += 1
            values["transport_lead"][s.stay_id] = lead
    beds = {b.bed_id: b for b in snap.beds}

    def clean(bed: str, cause: str, primitive: str) -> int:
        dist = beds[bed].cleaning
        assert dist is not None
        entity = f"{bed}|{cause}" if primitive == "cleaning" else bed
        v = inverse(dist, u01(*base, primitive, entity))
        if r2 and u01(*base, "r2_" + primitive, entity) < R2_PARAMS["cleaning_plus_1h_prob"]:
            v += 1
        return v

    for s in snap.stays:
        if s.bed_id is not None:
            values["cleaning"][f"{s.bed_id}|{s.stay_id}"] = clean(s.bed_id, s.stay_id, "cleaning")
    for b in snap.beds:
        if b.status == "dirty":
            values["cleaning"][f"{b.bed_id}|initial"] = clean(b.bed_id, "initial", "cleaning")
        elif b.status == "cleaning":
            values["cleaning_remaining"][b.bed_id] = clean(b.bed_id, "", "cleaning_remaining")
    for a in snap.admissions:
        values["arrival"][a.request_id] = inverse(a.arrival_delay, u01(*base, "arrival", a.request_id))
    presence = {}
    for key, pub in episode.sidecar.items():
        presence[key] = presence_draw(
            regime,
            float(pub["p_pub"]),
            float(pub["p_pub"]) >= 1.0,
            u01(*base, "presence", key),
            u01(*base, "presence_pool", pub["pool_key"]),
        )
    return Realisation(regime, replicate, PrivateTruth(values=values), presence)


def realisations(
    episode: Episode, regimes: tuple[str, ...], k: int, commitment: str
) -> dict[tuple[str, int], Realisation]:
    return {(r, i): realise(episode, r, i, commitment) for r in regimes for i in range(1, k + 1)}


def describe() -> dict[str, Any]:
    return {"regimes": list(REGIMES), "R2": R2_PARAMS, "R1": "public declared distributions, independent presences"}
