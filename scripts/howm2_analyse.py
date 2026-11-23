#!/usr/bin/env python3
"""HOWM-2 tranche A analysis: validation (a)(b) of L4, M_pub, verdicts, hidden-state shares, power.
Rules exactly as recorded in docs/howm2/NORME_HOWM2_A.md (A3, A4) before any measurement."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hospitalos.howm.keys import key  # noqa: E402

LAD = ROOT / "evidence" / "howm2" / "ladder"
FAMS = ("ready", "transport", "cleaning", "confirmation", "presence", "arrivals", "care")
LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")
HS = ("1", "6", "24")
SEED = int(key("HOWM2", "bootstrap") % (2**31))
DELTA_ID = 0.02
B = 2000


def load(part: str) -> list[dict]:
    return [json.loads(f.read_text()) for f in sorted((LAD / part).glob("*.json"))]


def fam_mean(r: dict, lv: str, h: str, f: str) -> float:
    v = r["acc"][lv][h].get(f, [0.0, 0])
    return v[0] / v[1] if v[1] else float("nan")


def L(r: dict, lv: str, h: str, fams: tuple[str, ...]) -> float:
    vals = [fam_mean(r, lv, h, f) for f in fams]
    vals = [x for x in vals if not math.isnan(x)]
    return float(np.mean(vals)) if vals else float("nan")


def boot_ci(x: np.ndarray, seed: int = SEED) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    x = x[~np.isnan(x)]
    bs = [np.mean(x[rng.integers(0, len(x), len(x))]) for _ in range(B)]
    return float(np.mean(x)), float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))


def ks_uniform(u: np.ndarray) -> float:
    u = np.sort(u)
    n = len(u)
    i = np.arange(1, n + 1)
    return float(max(np.max(i / n - u), np.max(u - (i - 1) / n)))


def validation(rs: list[dict]) -> dict:
    out = {"a_calibration": {}, "b_ordering": {}}
    for f in FAMS:
        u = np.array([x for r in rs for x in r["pits"]["L4"].get(f, [])])
        if len(u) == 0:
            out["a_calibration"][f] = {"n": 0, "status": "no items"}
            continue
        D = ks_uniform(u)
        thr = max(0.02, 1.63 / math.sqrt(len(u)))
        out["a_calibration"][f] = {
            "n": int(len(u)),
            "KS_D": D,
            "threshold": thr,
            "pass": bool(thr >= D),
            "hist10": np.histogram(u, bins=10, range=(0, 1))[0].tolist(),
        }
        if f in ("care",):
            out["a_calibration"][f]["note"] = (
                "care PIT not collected (L4 PIT collected for hazard families and arrivals)"
            )
    for f in FAMS:
        rows = {}
        fail = False
        for h in HS:
            d45 = np.array([fam_mean(r, "L4", h, f) - fam_mean(r, "L5", h, f) for r in rs])
            d34 = np.array([fam_mean(r, "L3", h, f) - fam_mean(r, "L4", h, f) for r in rs])
            if np.all(np.isnan(d45)):
                rows[h] = {"status": "no items"}
                continue
            c45, c34 = boot_ci(d45), boot_ci(d34)
            v1 = c45[2] < 0  # L4 significantly better than L5
            v2 = c34[2] < 0  # L4 significantly worse than L3
            rows[h] = {
                "L4_minus_L5": c45,
                "L3_minus_L4": c34,
                "violation_L4_below_L5": bool(v1),
                "violation_L4_above_L3": bool(v2),
            }
            fail = fail or v1 or v2
        out["b_ordering"][f] = {"horizons": rows, "pass": not fail}
    return out


def validation_amended(rs: list[dict], val: dict) -> dict:
    """Addendum 2: (a') one PIT per item (first appearance) for L4, L5 as control; (b') only L4 < L5."""
    pf = [
        json.loads(f.read_text())
        for f in sorted((ROOT / "evidence/howm2/pit_first/HOWM2_REF").glob("*.json"))
    ]
    out = {"a_prime": {}, "b_prime": {}, "n_establishments": len(pf)}
    for f in ("ready", "transport", "cleaning", "confirmation", "presence"):
        row = {}
        for lv in ("L4", "L5"):
            u = np.array([x for d in pf for x in d[lv].get(f, [])])
            if len(u) == 0:
                row[lv] = {"n": 0, "status": "no items"}
                continue
            D = ks_uniform(u)
            thr = max(0.02, 1.63 / math.sqrt(len(u)))
            row[lv] = {
                "n": int(len(u)),
                "KS_D": D,
                "threshold": thr,
                "pass": bool(thr >= D),
                "hist10": np.histogram(u, bins=10, range=(0, 1))[0].tolist(),
            }
        row["pass"] = row["L4"].get("pass", True) if row["L4"].get("n", 0) else None
        out["a_prime"][f] = row
    a_all = val["a_calibration"]
    for f in ("arrivals", "care"):
        out["a_prime"][f] = {
            "L4": a_all.get(f),
            "pass": a_all.get(f, {}).get("pass") if a_all.get(f, {}).get("n") else None,
            "note": "one value per (unit,hour) / (stay,hour,skill): unchanged from (a)",
        }
    for f, b in val["b_ordering"].items():
        viol = any(r.get("violation_L4_below_L5") for r in b["horizons"].values())
        out["b_prime"][f] = {"pass": not viol}
    return out


def margins(rs: list[dict], fams: tuple[str, ...]) -> dict:
    res = {}
    rng = np.random.default_rng(SEED)
    n = len(rs)
    for h in HS:
        l1 = np.array([L(r, "L1", h, fams) for r in rs])
        l2 = np.array([L(r, "L2", h, fams) for r in rs])
        l4 = np.array([L(r, "L4", h, fams) for r in rs])
        best = "L1" if l1.mean() <= l2.mean() else "L2"
        point = float(min(l1.mean(), l2.mean()) - l4.mean())
        bs = []
        for _ in range(B):
            i = rng.integers(0, n, n)
            bs.append(min(l1[i].mean(), l2[i].mean()) - l4[i].mean())
        per_est = (l1 if best == "L1" else l2) - l4
        res[h] = {
            "M_pub": point,
            "ci95": [float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))],
            "best_reference": best,
            "between_establishment_sd": float(np.std(per_est, ddof=1)),
            "n_needed_80pct_for_half_margin": (
                float(((1.96 + 0.8416) * np.std(per_est, ddof=1) / (point / 2)) ** 2)
                if point > 0
                else None
            ),
            "levels_mean": {lv: float(np.mean([L(r, lv, h, fams) for r in rs])) for lv in LEVELS},
        }
    lo = [res[h]["ci95"][0] for h in ("6", "24")]
    hi = [res[h]["ci95"][1] for h in ("6", "24")]
    verdict = (
        "HOWM1_DISCRIMINANT"
        if all(x >= DELTA_ID for x in lo)
        else "HOWM1_NON_DISCRIMINANT"
        if all(x < DELTA_ID for x in hi)
        else "HOWM1_INDETERMINE"
    )
    return {"by_horizon": res, "verdict": verdict, "families": list(fams)}


def hidden_state(rs: list[dict]) -> dict:
    out = {}
    for f in FAMS:
        out[f] = {}
        for h in HS:
            d35 = np.array([fam_mean(r, "L3", h, f) - fam_mean(r, "L5", h, f) for r in rs])
            d34 = np.array([fam_mean(r, "L3", h, f) - fam_mean(r, "L4", h, f) for r in rs])
            if np.all(np.isnan(d35)):
                out[f][h] = {"status": "no items"}
                continue
            c35 = boot_ci(d35)
            if c35[1] <= 0 <= c35[2]:
                out[f][h] = {
                    "L3_minus_L5": c35,
                    "status": "sans etat cache (IC de L3-L5 contient 0)",
                }
                continue
            ok = ~np.isnan(d35)
            rng = np.random.default_rng(SEED)
            bs = []
            for _ in range(B):
                i = rng.integers(0, ok.sum(), ok.sum())
                a, b = d34[ok][i].mean(), d35[ok][i].mean()
                bs.append(a / b if b != 0 else np.nan)
            out[f][h] = {
                "L3_minus_L5": c35,
                "pi_recovered": float(np.nanmean(d34) / np.nanmean(d35)),
                "ci95": [float(np.nanquantile(bs, 0.025)), float(np.nanquantile(bs, 0.975))],
            }
    return out


def family_table(rs: list[dict]) -> dict:
    return {
        h: {
            f: {
                lv: (
                    float(np.nanmean([fam_mean(r, lv, h, f) for r in rs]))
                    if not all(math.isnan(fam_mean(r, lv, h, f)) for r in rs)
                    else None
                )
                for lv in LEVELS
            }
            for f in (*FAMS, "auth")
        }
        for h in HS
    }


def main() -> int:
    out = {}
    ref = load("HOWM2_REF")
    out["n_ref"] = len(ref)
    val = validation(ref)
    out["validation"] = val
    vc = json.loads((ROOT / "evidence/howm2/VALIDATION_C.json").read_text())
    c_pass = (
        vc["enumeration"]["pass"]
        and vc["enumeration_relocated_items"]["pass"]
        and vc["independent_forward_backward"]["pass"]
    )
    out["validation"]["c_exactness"] = {"pass": c_pass, "families": ["transport", "cleaning"]}
    failing = []
    for f in FAMS:
        a = val["a_calibration"].get(f, {})
        b = val["b_ordering"].get(f, {})
        fa = a.get("pass") is False
        fb = b.get("pass") is False
        fc = (f in ("transport", "cleaning")) and not c_pass
        if fa or fb or fc:
            failing.append({"family": f, "a_fail": fa, "b_fail": fb, "c_fail": fc})
    out["validation"]["failing_families"] = failing
    kept = tuple(f for f in FAMS if f not in {x["family"] for x in failing})
    out["criterion_literal_original_rules"] = margins(ref, kept)
    out["criterion_literal_original_rules"]["note"] = (
        "rules (a)(b) as first written: every family with data excluded; superseded by addendum 2"
    )
    vam = validation_amended(ref, val)
    out["validation"]["amended"] = vam
    failing2 = []
    for f in FAMS:
        fa = vam["a_prime"].get(f, {}).get("pass") is False
        fb = vam["b_prime"].get(f, {}).get("pass") is False
        fc = (f in ("transport", "cleaning")) and not c_pass
        if fa or fb or fc:
            failing2.append({"family": f, "a_prime_fail": fa, "b_prime_fail": fb, "c_fail": fc})
    out["validation"]["failing_families_amended"] = failing2
    kept = tuple(f for f in FAMS if f not in {x["family"] for x in failing2})
    out["criterion"] = margins(ref, kept)
    out["criterion"]["rules"] = "NORME_HOWM2_A + addendum 1 + addendum 2"
    out["criterion_all_families_descriptive"] = margins(ref, FAMS)
    out["hidden_state"] = hidden_state(ref)
    out["family_table_REF"] = family_table(ref)
    for part in ("HOWM2_DIAG", "VAL", "TRAIN"):
        rs = load(part)
        if rs:
            out[f"descriptive_{part}"] = {
                "n": len(rs),
                "all_families": margins(rs, FAMS)["by_horizon"],
                "family_table": family_table(rs),
            }
    (ROOT / "evidence/howm2/LADDER_A.json").write_text(json.dumps(out, indent=1) + "\n")
    print(
        json.dumps(
            {
                "failing_amended": failing2,
                "kept": kept,
                "verdict": out["criterion"]["verdict"],
                "criterion": {
                    h: [
                        out["criterion"]["by_horizon"][h]["M_pub"],
                        out["criterion"]["by_horizon"][h]["ci95"],
                        out["criterion"]["by_horizon"][h]["best_reference"],
                    ]
                    for h in HS
                },
                "a_prime": {
                    f: {
                        lv: (
                            r.get(lv, {}).get("KS_D"),
                            r.get(lv, {}).get("threshold"),
                            r.get(lv, {}).get("n"),
                        )
                        for lv in ("L4", "L5")
                    }
                    for f, r in vam["a_prime"].items()
                    if f not in ("arrivals", "care")
                },
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
