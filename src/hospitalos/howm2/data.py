"""Light origin extraction: the same cohorts, labels, masks and windows as howm.dataset.build,
without the hourly graph tables (NORM A addendum 1.5; equality tested)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import numpy as np

from hospitalos.howm.dataset import (
    ITEM_DIM,
    N_HOURS,
    OriginData,
    _arrivals_known,
    _end_index,
    _window,
    hazard_label,
    item_features,
)
from hospitalos.howm.history import PublicStream


def origins(ep: Any, hs: list[int]) -> Iterator[tuple[int, OriginData, PublicStream]]:
    obs = ep.observations
    idx = _end_index(obs)
    arrivals_true = np.zeros((2, N_HOURS), np.int64)
    care_true: dict[str, dict[int, tuple[float, float]]] = {}
    presence: dict[str, bool] = {}
    for ev, _av, kind, subj, un, v in obs:
        if kind == "request_arrival":
            arrivals_true["AB".index(un), ev // 60] += 1
        elif kind == "care_due":
            care_true.setdefault(subj, {})[v["hour"]] = (v["ide"], v["as_"])
        elif kind in ("offer_present", "offer_absent"):
            presence[subj] = kind == "offer_present"
    ps = PublicStream(obs)
    for H in sorted(set(hs)):
        t = H * 60
        ps.advance(t)
        items: dict[str, list[dict[str, Any]]] = {}
        for fam, lst in ps.cohort(t).items():
            rows = []
            for it in lst:
                it = dict(it)
                it["x"] = item_features(fam, it, t)
                if fam == "presence":
                    it["label"] = presence.get(it["ref"])
                else:
                    it["end_avail"] = hazard_label(fam, it, idx)
                rows.append(it)
            items[fam] = rows
        arr = np.full((2, 24), -1, np.int64)
        for k in range(24):
            if H + k < N_HOURS:
                arr[:, k] = arrivals_true[:, H + k]
        stays = ps.present_stays()
        care_ref = sorted(stays)
        n = len(care_ref)
        care = np.zeros((n, 24, 2), np.float32)
        mask = np.zeros((n, 24), bool)
        cx = np.zeros((n, ITEM_DIM), np.float32)
        for i, sid in enumerate(care_ref):
            st = stays[sid]
            cx[i] = item_features(
                "care",
                {
                    "unit": st["unit"],
                    "acuity": st["acuity"],
                    "iso": st["iso"],
                    "transport": st["transport"],
                    "start": st["placed"],
                },
                t,
            )
            for k in range(24):
                val = care_true.get(sid, {}).get(H + k)
                if val is not None:
                    care[i, k] = val
                    mask[i, k] = True
        od = OriginData(
            H,
            items,
            arr,
            care_ref,
            cx,
            care,
            mask,
            _window(ps, t, arrivals_obs=_arrivals_known(ps, t)),
        )
        yield H, od, ps
