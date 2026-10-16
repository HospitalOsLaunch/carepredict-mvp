"""Site-specific snapshot receipts, with event-local RNG independent of physics."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

import numpy as np

from .config import HospitalConfig
from .v041 import observation

_OBS: Any = observation


class SiteObservationStream:
    def __init__(self, config: HospitalConfig):
        self.config = config
        self.profile = config.observation
        start = dt.datetime.combine(
            config.start - dt.timedelta(days=config.warmup_days),
            dt.time(),
            dt.timezone(dt.timedelta(hours=1)),
        )
        self.windows = {
            unit.unit_id: sorted(
                (
                    (o.starts_at - start).total_seconds() / 3600,
                    (o.ends_at - start).total_seconds() / 3600,
                )
                for o in self.profile.outages
                if not o.unit_ids or unit.unit_id in o.unit_ids
            )
            for unit in config.units
        }

    def release(self, hour: float, unit: str) -> float:
        # Deferred backlog keeps its original event/source clock. Adjacent windows chain.
        for start, end in self.windows[unit]:
            if start <= hour < end:
                hour = end
        return hour

    def observe(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        if event["type"] != "ETAT_UNITE":
            raise ValueError("Site observation profiles accept unit snapshots only")
        unit, hour = event["unite"], float(event["h"])
        # Stable across batch/online IDs, ordering and future schedule changes.
        key = json.dumps([self.config.seed, unit, hour, "site_observation_v1"])
        seed = int.from_bytes(hashlib.sha256(key.encode()).digest()[:16], "big")
        rng = np.random.Generator(np.random.PCG64(seed))
        p = self.profile
        payload = dict(event["payload"])
        loaded = payload.get("minutes_non_couvertes_h", 0) > 0
        missing = p.missing_probability * (p.load_missing_multiplier if loaded else 1.0)
        if rng.random() < min(1.0, missing):
            return []
        median = p.recording_delay_median_minutes
        lag = float(rng.lognormal(np.log(median), p.recording_delay_sigma)) if median else 0.0
        recorded = hour + lag * (p.load_delay_multiplier if loaded else 1.0) / 60
        ingested = (
            recorded
            + float(rng.uniform(p.ingestion_delay_min_minutes, p.ingestion_delay_max_minutes)) / 60
        )
        for name, probability in (
            ("sortants_medicaux_presents", p.ready_documented_probability),
            ("en_attente_aval", p.downstream_documented_probability),
        ):
            payload[name] = int(rng.binomial(payload[name], probability))
        payload["charge_soins_min_h"] = float(payload["charge_soins_min_h"]) * float(
            rng.lognormal(0, p.charge_noise_sigma)
        )
        correct = dict(payload)
        revised = rng.random() < p.revision_probability
        if revised:
            payload["lits_occupes"] = max(0, payload["lits_occupes"] + int(rng.choice([-1, 1])))
        base = {
            "event_id": event["event_id"],
            "event_version": 1,
            "type": "ETAT_UNITE",
            "unite": unit,
            "source": "GESTION_LITS",
            "t_evenement": hour,
            "t_saisie": recorded,
            "t_ingestion": ingested,
            "remplace_version": None,
            "payload": payload,
        }
        rows = [base]
        if revised:
            revision_h = recorded + float(
                rng.uniform(p.revision_delay_min_h, p.revision_delay_max_h)
            )
            rows.append(
                {
                    **base,
                    "event_version": 2,
                    "remplace_version": 1,
                    "t_saisie": revision_h,
                    "t_ingestion": revision_h + 1 / 60,
                    "payload": correct,
                }
            )
        if rng.random() < p.duplicate_probability:
            rows.append({**base, "t_ingestion": ingested + 2 / 60})
        for row in rows:
            row["t_ingestion"] = self.release(row["t_ingestion"], unit)
            row["t_disponible"] = self.release(
                row["t_ingestion"] + p.availability_delay_minutes / 60, unit
            )
        return rows


def observation_stream(config: HospitalConfig, calendar: Any) -> Any:
    if config.observation.mode == "v041":
        return _OBS.ObservationStream(calendar, config.seed)
    return SiteObservationStream(config)
