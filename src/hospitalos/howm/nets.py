"""B2 (aggregate latent memory) and H1 (entity memory + typed-graph messages), same heads.

Inputs are ONLY the public tables built by history/dataset (window W = 24 h before the origin).
Interfaces present but disabled in R1 (DESIGN 3; T-CFG-01..04): context=off, contrast=0,
jepa=off, stochastic_latent=off — none of them creates a parameter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import torch
from torch import nn

from .b0 import B0Params, day_period
from .dataset import (
    HAZARD_FAMILIES,
    ITEM_DIM,
    TYPED_RELATIONS,
    EstablishmentData,
    item_features,
)
from .heads import NB
from .history import B2_DIM, NODE_DIMS, NODE_TYPES, SHARED_FEATS
from .predict import N_PROFILES, Prediction

W = 24
Z = 64
HN = 48
CLOCK_COLS = [2 * 22 + SHARED_FEATS.index(c) for c in ("hsin", "hcos", "weekday")]
FAMS_ALL = (*HAZARD_FAMILIES, "presence", "arrivals", "care")


@dataclass(frozen=True)
class NetConfig:
    kind: str  # "B2" | "H1"
    context: str = "off"
    contrast_weight: float = 0.0
    jepa: str = "off"
    stochastic_latent: str = "off"

    def __post_init__(self) -> None:
        if (self.context, self.contrast_weight, self.jepa, self.stochastic_latent) != (
            "off",
            0.0,
            "off",
            "off",
        ):
            raise ValueError(
                "R1: context/contrast/JEPA/stochastic latent interfaces stay disabled (one variation at a time, R2)"
            )


def clock(hour: int) -> list[float]:
    lh = hour % 24
    return [
        math.sin(2 * math.pi * lh / 24),
        math.cos(2 * math.pi * lh / 24),
        float((hour // 24) % 7 < 5),
    ]


class Heads(nn.Module):
    def __init__(self, ent: int, b0: B0Params):
        super().__init__()
        self.ent = ent
        self.base = nn.ParameterDict(
            {
                f: nn.Parameter(torch.tensor(b0.base[f], dtype=torch.float32))
                for f in HAZARD_FAMILIES
            }
        )
        self.tod = nn.ParameterDict(
            {f: nn.Parameter(torch.tensor(b0.tod[f], dtype=torch.float32)) for f in HAZARD_FAMILIES}
        )
        d_in = Z + ent + ITEM_DIM
        self.haz = nn.Sequential(nn.Linear(d_in, 32), nn.ReLU(), nn.Linear(32, 1))
        self.arr_a = nn.Parameter(torch.tensor(b0.arr_a, dtype=torch.float32))
        self.arr_tod = nn.Parameter(torch.tensor(b0.arr_tod, dtype=torch.float32))
        self.arr_logr = nn.Parameter(torch.tensor(math.log(b0.arr_r), dtype=torch.float32))
        self.arr = nn.Sequential(nn.Linear(Z + 1, 32), nn.ReLU(), nn.Linear(32, 1))
        self.care_base = nn.Parameter(torch.tensor(b0.care_mu, dtype=torch.float32))  # [2,3,2]
        self.care_logsig = nn.Parameter(torch.tensor(np.log(b0.care_sigma), dtype=torch.float32))
        self.care = nn.Sequential(nn.Linear(Z + ent + ITEM_DIM, 32), nn.ReLU(), nn.Linear(32, 2))
        self.pres0 = nn.Parameter(
            torch.tensor(math.log(b0.presence_p / (1 - b0.presence_p)), dtype=torch.float32)
        )
        self.pres = nn.Sequential(nn.Linear(Z + ent + ITEM_DIM, 32), nn.ReLU(), nn.Linear(32, 1))
        for m in (
            self.haz,
            self.arr,
            self.care,
            self.pres,
        ):  # start at B0 (zero correction), declared
            nn.init.zeros_(m[-1].weight)
            nn.init.zeros_(m[-1].bias)


class Prop(nn.Module):
    """Latent propagation without observation (mode 2): z_{k+1} = GRUCell([clock, 0-mask], z_k)."""

    def __init__(self) -> None:
        super().__init__()
        self.cell = nn.GRUCell(4, Z)

    def forward(
        self, z: torch.Tensor, hours: torch.Tensor
    ) -> torch.Tensor:  # hours [B] origin hour H
        out = []
        for k in range(24):
            h = hours + k
            lh = torch.remainder(h, 24).float()
            inp = torch.stack(
                [
                    torch.sin(2 * math.pi * lh / 24),
                    torch.cos(2 * math.pi * lh / 24),
                    (torch.remainder(torch.div(h, 24, rounding_mode="floor"), 7) < 5).float(),
                    torch.zeros_like(lh),
                ],
                1,
            )
            z = self.cell(inp, z)
            out.append(z)
        return torch.stack(out, 1)  # [B, 24, Z]


class B2(nn.Module):
    def __init__(self, b0: B0Params, cfg: NetConfig = NetConfig("B2")):
        super().__init__()
        self.cfg = cfg
        self.inp = nn.Sequential(nn.Linear(B2_DIM + 1, Z), nn.ReLU())
        self.gru = nn.GRU(Z, Z, batch_first=True)
        self.prop = Prop()
        self.heads = Heads(0, b0)

    def encode(self, batch: dict[str, Any]) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        x = torch.cat([batch["b2"], torch.ones_like(batch["b2"][..., :1])], -1)
        _, h = self.gru(self.inp(x))
        return h[0], {}


class H1(nn.Module):
    def __init__(self, b0: B0Params, cfg: NetConfig = NetConfig("H1")):
        super().__init__()
        self.cfg = cfg
        self.enc = nn.ModuleDict(
            {t: nn.Sequential(nn.Linear(NODE_DIMS[t], HN), nn.ReLU()) for t in NODE_TYPES}
        )
        self.type_emb = nn.Embedding(len(NODE_TYPES), HN)
        # one Linear(2*HN -> HN)+ReLU per typed relation and direction, stored as grouped weights:
        # ReLU(W_r [h_s; h_d] + b_r) = ReLU(h_s W_r^s + h_d W_r^d + b_r)  (identical function)
        R = len(TYPED_RELATIONS)

        def lin() -> nn.Parameter:
            return nn.Parameter(torch.randn(HN, R * HN) * (1.0 / math.sqrt(2 * HN)))

        self.wf_s, self.wf_d, self.wr_s, self.wr_d = lin(), lin(), lin(), lin()
        self.bf = nn.Parameter(torch.zeros(R, HN))
        self.br = nn.Parameter(torch.zeros(R, HN))
        self.cell = nn.GRUCell(2 * HN, HN)
        self.att = nn.Linear(HN, 1)
        self.read = nn.Sequential(nn.Linear(3 * HN, Z), nn.Tanh())
        self.prop = Prop()
        self.heads = Heads(HN, b0)

    def _w(self) -> tuple[torch.Tensor, ...]:
        """Per-relation weights [R, HN, HN] views of the grouped parameters (same function)."""
        R = len(TYPED_RELATIONS)
        return tuple(
            x.view(HN, R, HN).permute(1, 0, 2) for x in (self.wf_s, self.wf_d, self.wr_s, self.wr_d)
        )

    def _mp(self, h: torch.Tensor, e: tuple, w: tuple[torch.Tensor, ...]) -> torch.Tensor:
        src, dst, rel, deg, psrc, pdst, _pvalid = e
        if src.numel() == 0:
            return torch.zeros_like(h)
        R, E = psrc.shape
        n = h.shape[0]
        hp = torch.cat([h, torch.zeros(1, HN)])  # padding row n (padded edges point to it)
        hs = hp.index_select(0, psrc.reshape(-1)).view(R, E, HN)
        hd = hp.index_select(0, pdst.reshape(-1)).view(R, E, HN)
        mf = torch.relu(torch.bmm(hs, w[0]) + torch.bmm(hd, w[1]) + self.bf[:, None, :])
        mr = torch.relu(torch.bmm(hd, w[2]) + torch.bmm(hs, w[3]) + self.br[:, None, :])
        m = torch.zeros(n + 1, HN)
        m.index_add_(0, pdst.reshape(-1), mf.reshape(-1, HN))
        m.index_add_(0, psrc.reshape(-1), mr.reshape(-1, HN))
        return m[:n] / deg

    def _mp_reference(self, h: torch.Tensor, e: tuple) -> torch.Tensor:
        """Former formulation (kept for the equality test)."""
        src, dst, rel, deg = e[:4]
        R = len(TYPED_RELATIONS)
        n = h.shape[0]
        allp = (h @ torch.cat([self.wf_s, self.wf_d, self.wr_s, self.wr_d], 1)).view(n, 4, R, HN)
        af, bf_, ar, br_ = allp[:, 0], allp[:, 1], allp[:, 2], allp[:, 3]
        m = torch.zeros_like(h)
        m.index_add_(0, dst, torch.relu(af[src, rel] + bf_[dst, rel] + self.bf[rel]))
        m.index_add_(0, src, torch.relu(ar[dst, rel] + br_[src, rel] + self.br[rel]))
        return m / deg

    def encode(self, batch: dict[str, Any]) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        g = batch["graph"]
        n = g["n"]
        h = torch.zeros(n, HN)
        temb = self.type_emb(g["type_id"])
        xs = torch.zeros(
            W, n, HN
        )  # all hours encoded at once per node type (same per-type encoders)
        for t in NODE_TYPES:
            idx = g["type_idx"][t]
            if idx.numel():
                xs[:, idx] = self.enc[t](torch.stack([g["feats"][k][t] for k in range(W)]))
        xs = xs + temb[None]
        w = self._w()
        for k in range(W):
            x = xs[k]
            pres = g["present"][k]
            m1 = self._mp(h, g["edges"][k], w)
            m2 = self._mp(h + m1, g["edges"][k], w)
            hn = self.cell(torch.cat([x, m2], 1), h)
            h = torch.where(pres[:, None], hn, h)
        a = self.att(h).squeeze(1)
        a = (
            a
            - torch.zeros(g["n_origins"]).index_reduce_(
                0, g["origin"], a, "amax", include_self=False
            )[g["origin"]]
        )
        w = torch.exp(a)
        den = torch.zeros(g["n_origins"]).index_add_(0, g["origin"], w)
        pooled = (
            torch.zeros(g["n_origins"], HN).index_add_(0, g["origin"], w[:, None] * h)
            / den[:, None]
        )
        z = self.read(torch.cat([h[g["unit_A"]], h[g["unit_B"]], pooled], 1))
        return z, {"h": h}


# ------------------------------------------------------------------------------ batches
def b2_window(est: EstablishmentData, H: int) -> np.ndarray:
    return est.b2[H - W : H]


def graph_batch(pairs: list[tuple[EstablishmentData, int]]) -> dict[str, Any]:
    """Union of nodes present in each window; edges remapped to batch indices."""
    type_id_of = {t: i for i, t in enumerate(NODE_TYPES)}
    offsets: list[
        dict[str, np.ndarray]
    ] = []  # per origin: type -> global-local -> batch index (-1 if absent)
    n = 0
    origin_of, type_ids, type_lists = [], [], {t: [] for t in NODE_TYPES}
    sel_per: list[dict[str, np.ndarray]] = []
    for oi, (est, H) in enumerate(pairs):
        maps, sels = {}, {}
        for t in NODE_TYPES:
            pres = est.present[t][H - W : H].any(0)
            sel = np.nonzero(pres)[0]
            mp = np.full(est.present[t].shape[1], -1, np.int64)
            mp[sel] = np.arange(n, n + len(sel))
            type_lists[t].extend(range(n, n + len(sel)))
            n += len(sel)
            origin_of += [oi] * len(sel)
            type_ids += [type_id_of[t]] * len(sel)
            maps[t], sels[t] = mp, sel
        offsets.append(maps)
        sel_per.append(sels)
    feats = []
    present = []
    edges = []
    for k in range(W):
        fk = {t: [] for t in NODE_TYPES}
        pk = np.zeros(n, bool)
        ek: dict[str, tuple[list[np.ndarray], list[np.ndarray]]] = {}
        for oi, (est, H) in enumerate(pairs):
            hh = H - W + k
            for t in NODE_TYPES:
                sel = sel_per[oi][t]
                fk[t].append(est.nodes[t][hh, sel])
                pk[offsets[oi][t][sel]] = est.present[t][hh, sel]
            for rel, arr in est.edges[hh].items():
                ts, _, td = rel.split("|")
                s = offsets[oi][ts][arr[:, 0]]
                d = offsets[oi][td][arr[:, 1]]
                ok = (s >= 0) & (d >= 0)
                ek.setdefault(rel, ([], []))
                ek[rel][0].append(s[ok])
                ek[rel][1].append(d[ok])
        feats.append(
            {
                t: torch.tensor(
                    np.concatenate(fk[t]) if fk[t] else np.zeros((0, NODE_DIMS[t])),
                    dtype=torch.float32,
                )
                for t in NODE_TYPES
            }
        )
        present.append(torch.tensor(pk))
        rel_id = {"|".join(r): i for i, r in enumerate(TYPED_RELATIONS)}
        ss, dd, rr = [], [], []
        for rel, (s_, d_) in ek.items():
            a, b = np.concatenate(s_), np.concatenate(d_)
            ss.append(a)
            dd.append(b)
            rr.append(np.full(len(a), rel_id[rel]))
        src = torch.tensor(np.concatenate(ss) if ss else np.zeros(0, np.int64), dtype=torch.long)
        dst = torch.tensor(np.concatenate(dd) if dd else np.zeros(0, np.int64), dtype=torch.long)
        relt = torch.tensor(np.concatenate(rr) if rr else np.zeros(0, np.int64), dtype=torch.long)
        deg = torch.ones(n, 1)
        if src.numel():
            deg = torch.clamp(
                torch.bincount(dst, minlength=n).float() + torch.bincount(src, minlength=n).float(),
                min=1.0,
            )[:, None]
        R = len(TYPED_RELATIONS)
        counts = (
            torch.bincount(relt, minlength=R) if relt.numel() else torch.zeros(R, dtype=torch.long)
        )
        emax = max(1, int(counts.max()))
        psrc = torch.full((R, emax), n, dtype=torch.long)
        pdst = torch.full((R, emax), n, dtype=torch.long)
        pvalid = torch.zeros((R, emax), dtype=torch.bool)
        if relt.numel():
            order = torch.argsort(relt, stable=True)
            r_sorted = relt[order]
            starts = torch.cumsum(counts, 0) - counts
            pos = torch.arange(len(order)) - starts[r_sorted]
            psrc[r_sorted, pos] = src[order]
            pdst[r_sorted, pos] = dst[order]
            pvalid[r_sorted, pos] = True
        edges.append((src, dst, relt, deg, psrc, pdst, pvalid))
    unit_a = [offsets[oi]["unit"][pairs[oi][0].refs["unit"].index("A")] for oi in range(len(pairs))]
    unit_b = [offsets[oi]["unit"][pairs[oi][0].refs["unit"].index("B")] for oi in range(len(pairs))]
    return {
        "n": n,
        "type_id": torch.tensor(type_ids),
        "type_idx": {t: torch.tensor(v, dtype=torch.long) for t, v in type_lists.items()},
        "feats": feats,
        "present": present,
        "edges": edges,
        "origin": torch.tensor(origin_of, dtype=torch.long),
        "n_origins": len(pairs),
        "unit_A": torch.tensor(unit_a),
        "unit_B": torch.tensor(unit_b),
        "offsets": offsets,
    }


def entity_of(fam: str, it: dict[str, Any]) -> tuple[str, str] | None:
    ref = it["ref"]
    if fam in ("auth", "ready", "transport"):
        return "stay", ref
    if fam == "cleaning":
        return "bed", ref
    if fam == "confirmation":
        kind, r = ref.split(":", 1)
        return ("stay", r) if kind == "T" else ("offer", r)
    if fam == "presence":
        return "offer", ref
    return None


def make_batch(
    pairs: list[tuple[EstablishmentData, int]], kind: str, with_labels: bool = True
) -> dict[str, Any]:
    from .b0 import to_bins
    from .dataset import DATA_END_MIN
    from .heads import BIN_MIN

    batch: dict[str, Any] = {"hours": torch.tensor([H for _, H in pairs])}
    if kind == "B2":
        batch["b2"] = torch.tensor(
            np.stack([b2_window(e, H) for e, H in pairs]), dtype=torch.float32
        )
        offsets = None
    else:
        batch["graph"] = graph_batch(pairs)
        offsets = batch["graph"]["offsets"]
    items: dict[str, dict[str, Any]] = {}
    for fam in (*HAZARD_FAMILIES, "presence"):
        xs, oi_, q, e, b, ev, ent, lab = [], [], [], [], [], [], [], []
        for oi, (est, H) in enumerate(pairs):
            od = est.origins[H]
            t = H * 60
            for it in od.items.get(fam, []):
                if fam == "presence" and with_labels and it.get("label") is None:
                    continue
                xs.append(it["x"])
                oi_.append(oi)
                if fam != "presence":
                    qq, ee, evv, bb = to_bins(
                        it["start"], t, it.get("end_avail"), DATA_END_MIN, BIN_MIN[fam]
                    )
                    q.append(qq), e.append(ee), ev.append(evv), b.append(bb)
                else:
                    lab.append(bool(it.get("label")))
                en = entity_of(fam, it)
                gi = -1
                if offsets is not None and en is not None and en[1] in est.refs[en[0]]:
                    gi = int(offsets[oi][en[0]][est.refs[en[0]].index(en[1])])
                ent.append(gi)
        items[fam] = {
            "x": torch.tensor(np.asarray(xs, np.float32).reshape(-1, ITEM_DIM)),
            "o": torch.tensor(oi_, dtype=torch.long),
            "q": torch.tensor(q, dtype=torch.long),
            "e": torch.tensor(e, dtype=torch.long),
            "b": torch.tensor(b, dtype=torch.long),
            "ev": torch.tensor(ev, dtype=torch.bool),
            "ent": torch.tensor(ent, dtype=torch.long),
            "y": torch.tensor(lab, dtype=torch.bool),
        }
    batch["items"] = items
    arr = np.stack([e.origins[H].arrivals for e, H in pairs])  # [B,2,24]
    batch["arr"] = torch.tensor(arr, dtype=torch.float32)
    batch["lognb"] = torch.tensor(
        [[math.log(e.n_beds["A"]), math.log(e.n_beds["B"])] for e, _ in pairs], dtype=torch.float32
    )
    cx, cv, cm, co, ca, cent = [], [], [], [], [], []
    for oi, (est, H) in enumerate(pairs):
        od = est.origins[H]
        for i, sid in enumerate(od.care_ref):
            cx.append(od.care_x[i])
            cv.append(od.care[i])
            cm.append(od.care_mask[i])
            co.append(oi)
            ca.append(int(np.argmax(od.care_x[i][7:10])))
            gi = -1
            if offsets is not None and sid in est.refs["stay"]:
                gi = int(offsets[oi]["stay"][est.refs["stay"].index(sid)])
            cent.append(gi)
    batch["care"] = {
        "x": torch.tensor(np.asarray(cx, np.float32).reshape(-1, ITEM_DIM)),
        "v": torch.tensor(np.asarray(cv, np.float32).reshape(-1, 24, 2)),
        "m": torch.tensor(np.asarray(cm, bool).reshape(-1, 24)),
        "o": torch.tensor(co, dtype=torch.long),
        "a": torch.tensor(ca, dtype=torch.long),
        "ent": torch.tensor(cent, dtype=torch.long),
    }
    return batch


def _ent(model: nn.Module, enc: dict[str, torch.Tensor], idx: torch.Tensor) -> torch.Tensor:
    if isinstance(model, B2):
        return torch.zeros(idx.shape[0], 0)
    h = enc["h"]
    out = torch.zeros(idx.shape[0], HN)
    ok = idx >= 0
    out[ok] = h[idx[ok]]
    return out


def forward_losses(model: nn.Module, batch: dict[str, Any]) -> dict[str, tuple[torch.Tensor, int]]:
    """Sum of NLL and count per family (discrete supports only)."""
    from .heads import BIN_MIN, t_bernoulli_logprob, t_care_logprob, t_hazard_logprob, t_nb_logpmf

    hd: Heads = model.heads  # type: ignore[assignment]
    z, enc = model.encode(batch)
    zk = model.prop(z, batch["hours"])  # [B,24,Z]
    out: dict[str, tuple[torch.Tensor, int]] = {}
    for fam in HAZARD_FAMILIES:
        it = batch["items"][fam]
        n = it["x"].shape[0]
        if n == 0:
            continue
        inp = torch.cat([z[it["o"]], _ent(model, enc, it["ent"]), it["x"]], 1)
        delta = hd.haz(inp).squeeze(1)
        step = BIN_MIN[fam] // 15
        bins = torch.arange(NB)
        logits = (
            hd.base[fam][None, :]
            + hd.tod[fam][torch.remainder(it["q"][:, None] + step * bins[None, :], 96)]
            + delta[:, None]
        )
        lp = t_hazard_logprob(logits, it["e"], it["b"], it["ev"])
        out[fam] = (-lp.sum(), n)
    it = batch["items"]["presence"]
    if it["x"].shape[0]:
        logit = hd.pres0 + hd.pres(
            torch.cat([z[it["o"]], _ent(model, enc, it["ent"]), it["x"]], 1)
        ).squeeze(1)
        out["presence"] = (-t_bernoulli_logprob(it["y"], logit).sum(), it["x"].shape[0])
    # arrivals
    B = z.shape[0]
    hours = batch["hours"][:, None] + torch.arange(24)[None, :]
    lt = []
    for ui in range(2):
        d = hd.arr(torch.cat([zk, torch.full((B, 24, 1), float(ui))], -1)).squeeze(-1)
        lt.append(
            hd.arr_a + batch["lognb"][:, ui : ui + 1] + hd.arr_tod[torch.remainder(hours, 24)] + d
        )
    logmu = torch.stack(lt, 1)
    ok = batch["arr"] >= 0
    lp = t_nb_logpmf(batch["arr"][ok], torch.exp(logmu[ok]), torch.exp(hd.arr_logr))
    out["arrivals"] = (-lp.sum(), int(ok.sum()))
    # care (masked: truly present stays only; labels only)
    c = batch["care"]
    if c["x"].shape[0]:
        zc = zk[c["o"]]  # [n,24,Z]
        ent = _ent(model, enc, c["ent"])[:, None, :].expand(-1, 24, -1)
        xc = c["x"][:, None, :].expand(-1, 24, -1)
        d = hd.care(torch.cat([zc, ent, xc], -1))  # [n,24,2]
        per = torch.tensor(
            [[day_period(int(h0) + k) for k in range(24)] for h0 in batch["hours"][c["o"]].tolist()]
        )
        base = hd.care_base.permute(1, 2, 0)[c["a"][:, None].expand(-1, 24), per]  # [n,24,2]
        mu = base + d
        sig = torch.exp(hd.care_logsig)[None, None, :].expand_as(mu)
        lp = t_care_logprob(c["v"], mu, sig)
        m = c["m"][:, :, None].expand_as(lp)
        out["care"] = (-lp[m].sum(), int(m.sum()))
    return out


EXCLUDED_NO_TRAIN_ITEMS = {
    "presence"
}  # no TRAIN item -> s_f undefined -> excluded (NORM N1, ledger #42)


def total_loss(
    parts: dict[str, tuple[torch.Tensor, int]], scales: dict[str, float]
) -> torch.Tensor:
    from .heads import check_scales

    check_scales(scales)
    out = 0.0
    for f, (s_, n) in parts.items():
        if f not in scales:
            if f not in EXCLUDED_NO_TRAIN_ITEMS:
                raise KeyError(f"family {f} has no loss scale and is not a declared exclusion")
            continue
        out = out + (s_ / max(n, 1)) / scales[f]
    return out  # type: ignore[return-value]


# ------------------------------------------------------------------------------ predictions
@torch.no_grad()
def predict(model: nn.Module, est: EstablishmentData, H: int) -> Prediction:
    return predict_many(model, est, [H])[0]


@torch.no_grad()
def predict_many(
    model: nn.Module, est: EstablishmentData, hs: list[int], chunk: int = 16
) -> list[Prediction]:
    """Batched predictions for several origins of one establishment (same results as one by one)."""
    kind = "B2" if isinstance(model, B2) else "H1"
    out: list[Prediction] = []
    for i in range(0, len(hs), chunk):
        part = hs[i : i + chunk]
        batch = make_batch([(est, H) for H in part], kind, with_labels=False)
        z_all, enc = model.encode(batch)
        zk_all = model.prop(z_all, batch["hours"])
        for oi, H in enumerate(part):
            out.append(_assemble(model, kind, est, H, oi, batch, z_all, enc, zk_all))
    return out


def _sel(it: dict[str, Any], oi: int) -> dict[str, Any]:
    m = it["o"] == oi
    return {
        k: (v[m] if isinstance(v, torch.Tensor) and v.shape[:1] == m.shape else v)
        for k, v in it.items()
    }


def _assemble(
    model: nn.Module,
    kind: str,
    est: EstablishmentData,
    H: int,
    oi: int,
    batch: dict[str, Any],
    z_all: torch.Tensor,
    enc: dict[str, torch.Tensor],
    zk_all: torch.Tensor,
) -> Prediction:
    hd: Heads = model.heads  # type: ignore[assignment]
    z = z_all[oi : oi + 1]
    zk = zk_all[oi : oi + 1]
    od = est.origins[H]
    t = H * 60
    delta_items = {}
    for fam in HAZARD_FAMILIES:
        it = _sel(batch["items"][fam], oi)
        if it["x"].shape[0] == 0:
            delta_items[fam] = np.zeros(0)
            continue
        delta_items[fam] = (
            hd.haz(
                torch.cat([z[torch.zeros_like(it["o"])], _ent(model, enc, it["ent"]), it["x"]], 1)
            )
            .squeeze(1)
            .numpy()
            .astype(float)
        )
    # existing entities: future items (ready/transport/confirmation for stays, cleaning for beds)
    delta_entity: dict[str, dict[str, float]] = {f: {} for f in HAZARD_FAMILIES}
    offsets = [batch["graph"]["offsets"][oi]] if kind == "H1" else None
    stays = {}
    for i, sid in enumerate(od.care_ref):
        stays[sid] = od.care_x[i]
    rows, keys = [], []
    for sid, x in stays.items():
        for fam in ("ready", "transport", "confirmation"):
            fx = np.array(x, np.float32).copy()
            fx[:6] = 0.0
            fx[("auth", "ready", "transport", "cleaning", "confirmation").index(fam)] = 1.0
            fx[12] = 0.0  # elapsed 0 at the future start
            gi = (
                int(offsets[0]["stay"][est.refs["stay"].index(sid)])
                if offsets is not None and sid in est.refs["stay"]
                else -1
            )
            rows.append((fx, gi))
            keys.append((fam, sid))
    for bed in est.refs["bed"]:
        fx = np.array(
            item_features("cleaning", {"unit": est.bed_unit[bed], "start": t}, t), np.float32
        )
        gi = int(offsets[0]["bed"][est.refs["bed"].index(bed)]) if offsets is not None else -1
        rows.append((fx, gi))
        keys.append(("cleaning", bed))
    if rows:
        xs = torch.tensor(np.stack([r[0] for r in rows]))
        ents = torch.tensor([r[1] for r in rows], dtype=torch.long)
        dd = (
            hd.haz(
                torch.cat(
                    [z[torch.zeros(len(rows), dtype=torch.long)], _ent(model, enc, ents), xs], 1
                )
            )
            .squeeze(1)
            .numpy()
        )
        for (fam, ref), v in zip(keys, dd, strict=True):
            delta_entity[fam][ref] = float(v)
    # new stays (profiles), entity state zero
    prof_x = []
    for un in "AB":
        for a in (1, 2, 3):
            for iso in (False, True):
                for tr in (False, True):
                    prof_x.append(
                        {"unit": un, "acuity": a, "iso": iso, "transport": tr, "start": t}
                    )
    delta_new = {}
    for fam in HAZARD_FAMILIES:
        xs = torch.tensor(np.array([item_features(fam, p, t) for p in prof_x], np.float32))
        delta_new[fam] = (
            hd.haz(
                torch.cat(
                    [z.expand(N_PROFILES, -1), torch.zeros(N_PROFILES, model.heads.ent), xs], 1
                )
            )
            .squeeze(1)
            .numpy()
            .astype(float)
        )
    # arrivals
    hours = H + torch.arange(24)
    mu = []
    for ui in range(2):
        d = hd.arr(torch.cat([zk[0], torch.full((24, 1), float(ui))], -1)).squeeze(-1)
        mu.append(
            torch.exp(
                hd.arr_a + batch["lognb"][oi, ui] + hd.arr_tod[torch.remainder(hours, 24)] + d
            )
        )
    arr_mu = torch.stack(mu).numpy().astype(float)
    # care
    sig = torch.exp(hd.care_logsig).numpy().astype(float)
    per = torch.tensor([day_period(H + k) for k in range(24)])
    c = _sel(batch["care"], oi)
    if c["x"].shape[0]:
        ent = _ent(model, enc, c["ent"])[:, None, :].expand(-1, 24, -1)
        d = hd.care(
            torch.cat(
                [zk[torch.zeros_like(c["o"])], ent, c["x"][:, None, :].expand(-1, 24, -1)], -1
            )
        )
        base = hd.care_base.permute(1, 2, 0)[
            c["a"][:, None].expand(-1, 24), per[None, :].expand(c["x"].shape[0], -1)
        ]
        care_mu = (base + d).numpy().astype(float)
    else:
        care_mu = np.zeros((0, 24, 2))
    care_new = np.zeros((2, 3, 24, 2))
    for ui, un in enumerate("AB"):
        for a in (1, 2, 3):
            x = torch.tensor(
                np.array(
                    item_features("care", {"unit": un, "acuity": a, "start": t}, t), np.float32
                )
            )
            d = hd.care(
                torch.cat([zk[0], torch.zeros(24, model.heads.ent), x[None, :].expand(24, -1)], -1)
            )
            base = hd.care_base.permute(1, 2, 0)[torch.full((24,), a - 1), per]
            care_new[ui, a - 1] = (base + d).numpy()
    it = _sel(batch["items"]["presence"], oi)
    if it["x"].shape[0]:
        pl = hd.pres0 + hd.pres(
            torch.cat([z[torch.zeros_like(it["o"])], _ent(model, enc, it["ent"]), it["x"]], 1)
        ).squeeze(1)
        pres = torch.sigmoid(pl).numpy().astype(float)
    else:
        pres = np.zeros(0)
    xo = torch.tensor(
        np.array(
            [
                item_features(
                    "presence",
                    {"unit": "A", "skill": "IDE", "source": "pool", "slot_start": t + 60},
                    t,
                )
            ],
            np.float32,
        )
    )
    p_new = float(
        torch.sigmoid(
            hd.pres0 + hd.pres(torch.cat([z, torch.zeros(1, model.heads.ent), xo], 1))
        ).item()
    )
    xc = torch.tensor(
        np.array(
            [item_features("confirmation", {"unit": "A", "kind": "offer", "start": t}, t)],
            np.float32,
        )
    )
    conf_new = float(hd.haz(torch.cat([z, torch.zeros(1, model.heads.ent), xc], 1)).item())
    return Prediction(
        {f: hd.base[f].detach().numpy().astype(float) for f in HAZARD_FAMILIES},
        {f: hd.tod[f].detach().numpy().astype(float) for f in HAZARD_FAMILIES},
        delta_items,
        delta_entity,
        delta_new,
        arr_mu,
        float(torch.exp(hd.arr_logr)),
        care_mu,
        sig,
        care_new,
        pres,
        p_new,
        conf_new,
        {"system": kind, "t": t},
    )


def n_params(model: nn.Module) -> dict[str, int]:
    out = {name: sum(p.numel() for p in mod.parameters()) for name, mod in model.named_children()}
    out["total"] = sum(p.numel() for p in model.parameters())
    return out
