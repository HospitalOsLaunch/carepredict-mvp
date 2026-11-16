#!/usr/bin/env python3
"""HOWM-1 R1 evaluation (frozen at F1). Run under scripts/howm_budget_run.py.

f1                                   freeze code, B0, scales, selected checkpoints, rules (F1.json)
run --partition P --start --stop     per-establishment results (DEVTEST/DIAG_DEV read once, after F1;
                                     VAL allowed for development checks with --dev)
analyse                              aggregates, cluster bootstrap, verdict labels (A1 / NORM)
probes                               post-F1 privileged probes on VAL (diagnostic only)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from hospitalos.howm import ckpt, g0check  # noqa: E402
from hospitalos.howm import corpus as C  # noqa: E402
from hospitalos.howm.b0 import B0Params  # noqa: E402
from hospitalos.howm.controllers import evaluate_instant, model_choice  # noqa: E402
from hospitalos.howm.generator import EVAL_DAY, INSTANT_HOURS, PARTITION_SIZES  # noqa: E402
from hospitalos.howm.history import PublicStream  # noqa: E402
from hospitalos.howm.nets import B2, H1, predict_many  # noqa: E402
from hospitalos.howm.predict import HORIZONS, b0_predict, ensemble_logscores, item_set_fingerprint  # noqa: E402
from hospitalos.howm.rollout import (
    TARGET_NAMES,
    ModelProvider,
    NewProfileFreq,
    crps_samples,
    rollout,
    rollout_key,
    target_vector,
    truth_vector,
)  # noqa: E402
from hospitalos.howm.world import TPH, candidates  # noqa: E402

EVID = C.EVID
F1 = EVID / "F1.json"
OUT = EVID / "eval"
SYSTEMS = ("B0-pool", "B0-local", "B2", "H1")
M = 16
torch.set_num_threads(4)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def pilot_state() -> dict:
    return json.loads((EVID / "PILOT.json").read_text())["state"]


def cmd_f1() -> None:
    if F1.exists():
        raise SystemExit("F1 already written")
    body = freeze_body()
    F1.write_text(json.dumps(body, indent=1) + "\n")
    print(json.dumps({"F1_sha256": sha(F1), "members": body["members"]}))


def freeze_body() -> dict:
    g0check.check()
    sel = json.loads((EVID / "SELECTION.json").read_text())
    st = pilot_state()
    seeds = list(range(3 if st["runs"] == 4 else 2))
    members = {}
    for kind in ("B2", "H1"):
        lr = sel[kind]["chosen_lr"]
        members[kind] = []
        for s in seeds:
            d = EVID / "train" / f"{kind}_lr{lr:g}_s{s}"
            meta = json.loads((d / "state.json").read_text())
            if sha(d / "best.pt") != meta["best_sha256"]:
                raise SystemExit(f"checkpoint hash mismatch {d}")
            members[kind].append(
                {
                    "run": d.name,
                    "best_sha256": meta["best_sha256"],
                    "best_epoch": json.loads(
                        ckpt.load_verified(d / "best.pt", meta["best_sha256"])["state_json"]
                    )["best_epoch"],
                }
            )
    body = {
        "schema": "HOWM1_F1_1",
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "code": C.code_hashes(),
        "g0_sha256": sha(EVID / "COMMITMENT_G0.json"),
        "b0_params_sha256": sha(EVID / "B0_PARAMS.json"),
        "loss_scales_sha256": sha(EVID / "LOSS_SCALES.json"),
        "crps_scales_sha256": sha(EVID / "CRPS_SCALES.json"),
        "selection": sel,
        "members": members,
        "pilot_state": st,
        "decision_instants_local": list(INSTANT_HOURS[: st["instants"]]),
        "M_prediction": M,
        "M_decision": st["m_dec"],
        "targets": {
            "primary": "Delta_LS(h)=mean_e[L(B0-local)-L(H1)] nats; 95% cluster-bootstrap lower bound > 0 at h=6 AND h=24",
            "secondary": "R(h)=1-sum_e Cbar(H1)/sum_e Cbar(B0-local) on normalised CRPS; ambition R(6)>=0.10 and R(24)>=0.10 (point); lower bound > 0",
            "decision": "D_dec=mean[U(B0-local choice)-U(H1 choice)] (precheck informative: margin 54.2 >= 15); ambition >= 5 (point); lower bound > 0",
        },
        "bootstrap": {
            "B": 2000,
            "seed": json.loads((EVID / "COMMITMENT_G0.json").read_text())["bootstrap_seed"],
            "unit": "establishment",
        },
        "rule": "no selection, tuning or generator change after reading DEVTEST/DIAG_DEV; DIAG_DEV never used to choose a model",
    }
    return body


def load_members(f1: dict, p: B0Params) -> dict[str, list[torch.nn.Module]]:
    out = {}
    for kind, mem in f1["members"].items():
        out[kind] = []
        for m in mem:
            obj = ckpt.load_verified(EVID / "train" / m["run"] / "best.pt", m["best_sha256"])
            net = B2(p) if kind == "B2" else H1(p)
            net.load_state_dict(obj["model"])
            net.eval()
            out[kind].append(net)
    return out


def freq(p: B0Params) -> NewProfileFreq:
    f = p.new_profile_freq
    return NewProfileFreq(
        f["p_iso"], (f["p_acuity_1"], f["p_acuity_2"], f["p_acuity_3"]), f["p_transport"]
    )


def providers(
    preds: list, od, origin_tick: int, base_key: int, m_total: int, fr: NewProfileFreq
) -> list[ModelProvider]:
    """M total per system; ensemble members share it (8/8 for 2 members), sample keys never reused."""
    k = len(preds)
    return [ModelProvider(preds[m % k], od, origin_tick, m, base_key, fr) for m in range(m_total)]


def strengthened_rule(eng) -> int:
    """Simple public business rule: coordinate + compatibility cleaning + pool IDE to the unit with the
    largest public nursing pressure at tau (acuity-weighted stays minus roster)."""
    best, best_u = None, -1e9
    h = eng.tick // TPH
    for un in ("A", "B"):
        load = (
            sum(
                {1: 8, 2: 12, 3: 20}[s.acuity]
                for s in eng.stays.values()
                if s.unit == un and s.departed is None
            )
            / 60.0
        )
        p = load - eng.units[un].roster["IDE"][h]
        if p > best_u:
            best, best_u = un, p
    target = f"pool_IDE_{best}"
    return next(
        i
        for i, c in enumerate(candidates())
        if c.coordinate and c.cleaning == "compat" and c.reinforcement == target
    )


def cmd_run(partition: str, start: int, stop: int, dev: bool) -> None:
    g0check.check()
    f1 = freeze_body() if dev else json.loads(F1.read_text())
    if not dev and f1["code"] != C.code_hashes():
        raise SystemExit("code differs from F1: refused")
    if partition in C.GUARDED and dev:
        raise SystemExit("--dev is for VAL only")
    if partition == "VAL" and not dev:
        raise SystemExit("VAL evaluation is a development check: use --dev")
    p = B0Params.from_json(json.loads((EVID / "B0_PARAMS.json").read_text()))
    nets = load_members(f1, p)
    fr = freq(p)
    _ = f1["pilot_state"]
    inst_hours = f1["decision_instants_local"]
    m_dec = f1["M_decision"]
    s_c = json.loads((EVID / "CRPS_SCALES.json").read_text())["s_c"]
    outdir = OUT / (partition + ("_dev" if dev else ""))
    outdir.mkdir(parents=True, exist_ok=True)
    origins_all = C.ORIGINS[partition]
    for idx in range(start, min(stop, PARTITION_SIZES[partition])):
        f = outdir / f"{idx:03d}.json"
        if f.exists():
            continue
        t0 = time.time()
        d = C.load(partition, idx, allow_guarded=not dev)
        ep, est = d["episode"], d["data"]
        origins = origins_all if not dev else origins_all[::10]
        tm = {s: 0.0 for s in SYSTEMS}
        preds = {}
        t1 = time.time()
        preds["B0-pool"] = {H: [b0_predict(p, est.origins[H], est, False)] for H in origins}
        tm["B0-pool"] += time.time() - t1
        t1 = time.time()
        preds["B0-local"] = {H: [b0_predict(p, est.origins[H], est, True)] for H in origins}
        tm["B0-local"] += time.time() - t1
        for kind in ("B2", "H1"):
            t1 = time.time()
            per = [predict_many(net, est, origins) for net in nets[kind]]
            preds[kind] = {H: [per[j][i] for j in range(len(per))] for i, H in enumerate(origins)}
            tm[kind] += time.time() - t1
        ls = {s: {str(h): {} for h in HORIZONS} for s in SYSTEMS}
        crps = {s: {str(h): np.zeros(len(TARGET_NAMES)) for h in HORIZONS} for s in SYSTEMS}
        cover = {
            s: {
                str(h): {"50": np.zeros(len(TARGET_NAMES)), "90": np.zeros(len(TARGET_NAMES))}
                for h in HORIZONS
            }
            for s in SYSTEMS
        }
        spread = {s: {str(h): np.zeros(len(TARGET_NAMES)) for h in HORIZONS} for s in SYSTEMS}
        n_crps = {str(h): 0 for h in HORIZONS}
        rejected = {s: 0 for s in SYSTEMS}
        fps = set()
        ps = PublicStream(ep.observations)
        for H in origins:
            od = est.origins[H]
            fps.add(item_set_fingerprint(od))
            ps.advance(H * 60)
            eng = ps.to_engine(H * 60)
            truths = {h: truth_vector(ep, H, h) for h in HORIZONS}
            for s in SYSTEMS:
                t1 = time.time()
                for h in HORIZONS:
                    sc = ensemble_logscores(preds[s][H], od, h)
                    for fam, v in sc.items():
                        a = ls[s][str(h)].setdefault(fam, [0.0, 0])
                        a[0] += float(-np.sum(v))
                        a[1] += len(v)
                res = [
                    rollout(eng, pv, None)
                    for pv in providers(
                        preds[s][H], od, 4 * H, rollout_key(partition, idx, H), M, fr
                    )
                ]
                rejected[s] += sum(r["rejected"] for r in res)
                for h in HORIZONS:
                    if truths[h] is None:
                        continue
                    y = np.array(truths[h])
                    samp = np.array([target_vector(r, h) for r in res])
                    crps[s][str(h)] += crps_samples(samp, y)
                    for q, (lo, hi) in (("50", (0.25, 0.75)), ("90", (0.05, 0.95))):
                        ql, qh = np.quantile(samp, lo, axis=0), np.quantile(samp, hi, axis=0)
                        cover[s][str(h)][q] += (y >= ql) & (y <= qh)
                    spread[s][str(h)] += samp.std(axis=0)
                tm[s] += time.time() - t1
            for h in HORIZONS:
                n_crps[str(h)] += truths[h] is not None
        # decision diagnostic (instants of day 5, ladder-reduced)
        decisions = []
        for hh in inst_hours:
            tau = EVAL_DAY * 96 + hh * TPH
            ps2 = PublicStream(ep.observations)
            ps2.advance(tau * 15)
            peng = ps2.to_engine(tau * 15)
            H = tau // TPH
            od = est.origins[H]
            choosers, model_u = {}, {}
            for s in SYSTEMS:
                if s.startswith("B0"):
                    pr = [b0_predict(p, od, est, s == "B0-local")]
                else:
                    pr = [predict_many(net, est, [H])[0] for net in nets[s]]
                t1 = time.time()
                c, mean_u, us = model_choice(
                    peng, providers(pr, od, tau, rollout_key(partition, idx, H) ^ 0xD, m_dec, fr)
                )
                tm[s] += time.time() - t1
                choosers[s] = lambda c=c: c
                model_u[s] = {
                    "choice": c,
                    "mean_u": mean_u,
                    "spread": list(np.std(np.array(us), axis=0)),
                    "u_samples": us,
                }
            choosers["strengthened_rule"] = lambda e=peng: strengthened_rule(e)
            out = evaluate_instant(ep, tau, peng, choosers, controllers=("C_full", "C_param"))
            out["models"] = model_u
            decisions.append(out)
        res = {
            "partition": partition,
            "index": idx,
            "population": ep.spec.population,
            "mech": ep.spec.mech,
            "origins": len(origins),
            "logscore": ls,
            "crps_norm": {
                s: {
                    h: {
                        n: (
                            float(crps[s][h][j] / max(n_crps[h], 1) / s_c[n])
                            if s_c[n] > 0
                            else None
                        )
                        for j, n in enumerate(TARGET_NAMES)
                    }
                    for h in crps[s]
                }
                for s in SYSTEMS
            },
            "crps_raw": {
                s: {h: (crps[s][h] / max(n_crps[h], 1)).tolist() for h in crps[s]} for s in SYSTEMS
            },
            "coverage": {
                s: {
                    h: {q: (cover[s][h][q] / max(n_crps[h], 1)).tolist() for q in cover[s][h]}
                    for h in cover[s]
                }
                for s in SYSTEMS
            },
            "spread": {
                s: {h: (spread[s][h] / max(n_crps[h], 1)).tolist() for h in spread[s]}
                for s in SYSTEMS
            },
            "rejected_events": rejected,
            "item_set_fingerprints": len(fps),
            "decisions": decisions,
            "seconds_per_system": tm,
            "seconds_total": time.time() - t0,
        }
        f.write_text(json.dumps(res) + "\n")
        print(idx, round(time.time() - t0, 1), "s", flush=True)


def _boot(vals: np.ndarray, seed: int, B: int = 2000, stat=np.mean) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    n = len(vals)
    bs = [stat(vals[rng.integers(0, n, n)]) for _ in range(B)]
    return float(stat(vals)), float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))


def _L(r: dict, s: str, h: str) -> float:
    fam = r["logscore"][s][h]
    vals = [v[0] / v[1] for f, v in fam.items() if f != "auth" and v[1] > 0]
    return float(np.mean(vals))


def cmd_analyse(partition: str) -> dict:
    f1 = json.loads(F1.read_text()) if F1.exists() else freeze_body()
    seed = f1["bootstrap"]["seed"]
    files = sorted((OUT / partition).glob("*.json"))
    rs = [json.loads(f.read_text()) for f in files]
    out: dict = {"partition": partition, "establishments": len(rs)}
    # primary: paired log-score difference
    for h in ("1", "6", "24"):
        pairs = {
            "B0-local - H1": ("B0-local", "H1"),
            "B2 - H1": ("B2", "H1"),
            "B0-pool - B0-local": ("B0-pool", "B0-local"),
            "B0-local - B2": ("B0-local", "B2"),
        }
        out[f"delta_LS_h{h}"] = {
            k: _boot(np.array([_L(r, a, h) - _L(r, b, h) for r in rs]), seed)
            for k, (a, b) in pairs.items()
        }
        out[f"LS_mean_h{h}"] = {s: float(np.mean([_L(r, s, h) for r in rs])) for s in SYSTEMS}
        out[f"LS_by_family_h{h}"] = {
            s: {
                fam: float(
                    sum(r["logscore"][s][h].get(fam, [0, 0])[0] for r in rs)
                    / max(1, sum(r["logscore"][s][h].get(fam, [0, 0])[1] for r in rs))
                )
                for fam in (
                    "auth",
                    "ready",
                    "transport",
                    "cleaning",
                    "confirmation",
                    "presence",
                    "arrivals",
                    "care",
                )
            }
            for s in SYSTEMS
        }

        def cbar(r: dict, s: str) -> float:
            v = [x for x in r["crps_norm"][s][h].values() if x is not None]
            return float(np.mean(v))

        rng = np.random.default_rng(seed)
        ch1 = np.array([cbar(r, "H1") for r in rs])
        cb0 = np.array([cbar(r, "B0-local") for r in rs])
        point = 1 - ch1.sum() / cb0.sum() if cb0.sum() > 0 else None
        bs = []
        for _ in range(2000):
            i = rng.integers(0, len(rs), len(rs))
            if cb0[i].sum() > 0:
                bs.append(1 - ch1[i].sum() / cb0[i].sum())
        out[f"R_h{h}"] = {
            "point": point,
            "ci95": [float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))],
        }
        out[f"CRPS_norm_mean_h{h}"] = {s: float(np.mean([cbar(r, s) for r in rs])) for s in SYSTEMS}
        out[f"coverage_h{h}"] = {
            s: {
                q: float(np.mean([np.mean(r["coverage"][s][h][q]) for r in rs]))
                for q in ("50", "90")
            }
            for s in SYSTEMS
        }
        out[f"spread_h{h}"] = {
            s: float(np.mean([np.mean(r["spread"][s][h]) for r in rs])) for s in SYSTEMS
        }
    # decisions
    rows = []
    for r in rs:
        for d in r["decisions"]:
            v = d["value"]
            ev = np.array(d["eval_u"])
            row = {
                "idx": r["index"],
                "tau": d["tau"],
                **{k: v[k] for k in v},
                "oracle": d["oracle_U_star"],
            }
            for s in SYSTEMS:
                mu = np.array(d["models"][s]["mean_u"])
                true_delta = ev.mean(0) - ev[:, 0].mean()
                pred_delta = mu - mu[0]
                row[f"{s}:delta_mae"] = float(np.mean(np.abs(pred_delta[1:] - true_delta[1:])))
                row[f"{s}:sign_acc"] = float(
                    np.mean(np.sign(pred_delta[1:]) == np.sign(true_delta[1:]))
                )
                null = np.abs(true_delta[1:]) < 15
                row[f"{s}:null_recognised"] = (
                    float(np.mean(np.abs(pred_delta[1:][null]) < 15)) if null.any() else None
                )
                sp = np.array(d["models"][s]["spread"])
                order = np.argsort(mu)
                row[f"{s}:does_not_know"] = bool(
                    mu[order[1]] - mu[order[0]] < sp[order[0]] / math.sqrt(f1["M_decision"])
                )
                row[f"{s}:wrong"] = bool(v[s] > v["habitual"])
            rows.append(row)
    if rows:

        def per_est(key_fn) -> np.ndarray:
            by = {}
            for row in rows:
                by.setdefault(row["idx"], []).append(key_fn(row))
            return np.array([np.mean(v) for v in by.values()])

        out["D_dec"] = _boot(per_est(lambda r: r["B0-local"] - r["H1"]), seed)
        out["decision_means"] = {
            k: float(np.mean([r[k] for r in rows]))
            for k in (*SYSTEMS, "strengthened_rule", "C_param", "C_full", "habitual", "oracle")
        }
        out["regret_vs_C_full"] = {
            s: float(np.mean([r[s] - r["C_full"] for r in rows]))
            for s in (*SYSTEMS, "strengthened_rule", "C_param")
        }
        out["gain_vs_habitual"] = {
            s: float(np.mean([r["habitual"] - r[s] for r in rows]))
            for s in (*SYSTEMS, "strengthened_rule", "C_param", "C_full")
        }
        out["intervention_effects"] = {
            s: {
                m: float(
                    np.nanmean(
                        [r[f"{s}:{m}"] if r[f"{s}:{m}"] is not None else np.nan for r in rows]
                    )
                )
                for m in ("delta_mae", "sign_acc", "null_recognised", "does_not_know", "wrong")
            }
            for s in SYSTEMS
        }
        out["n_instants"] = len(rows)
    out["rejected_events"] = {s: int(sum(r["rejected_events"][s] for r in rs)) for s in SYSTEMS}
    out["seconds_per_system"] = {
        s: float(sum(r["seconds_per_system"][s] for r in rs)) for s in SYSTEMS
    }
    out["strata"] = {}
    for name, cond in (
        ("simple(m2 off,m3 off)", lambda r: r["mech"].get("simple")),
        ("m2 on", lambda r: r["mech"].get("m2")),
        ("m2 off, m3 on", lambda r: (not r["mech"].get("m2")) and not r["mech"].get("simple")),
    ):
        sub = [r for r in rs if cond(r)]
        if sub:
            out["strata"][name] = {
                "n": len(sub),
                **{
                    f"delta_LS_B0local_minus_H1_h{h}": float(
                        np.mean([_L(r, "B0-local", h) - _L(r, "H1", h) for r in sub])
                    )
                    for h in ("6", "24")
                },
            }
    p6, p24 = out["delta_LS_h6"]["B0-local - H1"], out["delta_LS_h24"]["B0-local - H1"]
    out["verdicts"] = {
        "primary_DeltaLS": "met (lower bounds > 0 at h=6 and h=24)"
        if (p6[1] > 0 and p24[1] > 0)
        else "not met",
        "secondary_CRPS_ambition_point": "ambition atteinte (estimation ponctuelle)"
        if all((out[f"R_h{h}"]["point"] or -1) >= 0.10 for h in ("6", "24"))
        else "ambition non atteinte",
        "secondary_CRPS_positive": "gain positif (borne basse > 0)"
        if all(out[f"R_h{h}"]["ci95"][0] > 0 for h in ("6", "24"))
        else "gain positif non établi",
        "decision": (
            "ambition atteinte (estimation ponctuelle)"
            if out.get("D_dec", (0,))[0] >= 5
            else "ambition non atteinte"
        )
        + "; "
        + (
            "gain positif (borne basse > 0)"
            if out.get("D_dec", (0, 0))[1] > 0
            else "gain positif non établi"
        ),
    }
    (EVID / f"RESULTS_R1_{partition}.json").write_text(json.dumps(out, indent=1) + "\n")
    print(
        json.dumps(
            {k: out[k] for k in ("verdicts", "delta_LS_h6", "delta_LS_h24", "R_h6", "R_h24")},
            indent=1,
        )
    )
    return out


def cmd_probes() -> None:
    """Post-F1 diagnostic on VAL: linear probe of the hidden team-slowdown regime from frozen z_t."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score

    f1 = json.loads(F1.read_text())
    p = B0Params.from_json(json.loads((EVID / "B0_PARAMS.json").read_text()))
    nets = load_members(f1, p)
    from hospitalos.howm.nets import make_batch

    out = {}
    for kind in ("B2", "H1"):
        X, y, g = [], [], []
        for i in range(PARTITION_SIZES["VAL"]):
            d = C.load("VAL", i)
            ep, est = d["episode"], d["data"]
            if not ep.spec.mech["m2"]:
                continue
            hs = list(range(24, 144, 4))
            with torch.no_grad():
                z, _ = nets[kind][0].encode(
                    make_batch([(est, H) for H in hs], kind, with_labels=False)
                )
            X += z.numpy().tolist()
            y += [ep.regimes["cleaning"][H - 1] for H in hs]
            g += [i] * len(hs)
        X, y, g = np.array(X), np.array(y), np.array(g)
        aucs = []
        for test in sorted(set(g)):
            tr, te = g != test, g == test
            if len(set(y[tr])) < 2 or len(set(y[te])) < 2:
                continue
            clf = LogisticRegression(max_iter=1000).fit(X[tr], y[tr])
            aucs.append(roc_auc_score(y[te], clf.predict_proba(X[te])[:, 1]))
        out[kind] = {
            "auc_leave_one_establishment_out": float(np.mean(aucs)) if aucs else None,
            "folds": len(aucs),
            "positives": int(y.sum()),
            "n": int(len(y)),
        }
    out["note"] = (
        "privileged label (true regime) used only for this post-freeze diagnostic; never an input"
    )
    (EVID / "PROBES_R1.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--partition", default="DEVTEST")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--stop", type=int, default=10**6)
    ap.add_argument("--dev", action="store_true")
    a = ap.parse_args()
    if a.cmd == "f1":
        cmd_f1()
    elif a.cmd == "run":
        cmd_run(a.partition, a.start, a.stop, a.dev)
    elif a.cmd == "analyse":
        cmd_analyse(a.partition)
    elif a.cmd == "probes":
        cmd_probes()
    else:
        raise SystemExit(a.cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
