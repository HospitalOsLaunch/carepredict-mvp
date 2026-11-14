#!/usr/bin/env python3
"""HOWM-1 R0 commands (run under scripts/howm_budget_run.py).

g0                      write evidence/howm1/COMMITMENT_G0.json (before any corpus generation)
gen --partition P       generate corpus files for P (TRAIN, VAL, DEVTEST, DIAG_DEV) + manifest
constants               CRPS target scales s_c from TRAIN only (NORM N3.5)
precheck --start --stop decision-margin precheck on VAL (privileged controllers only, NORM N2)
precheck-summary        aggregate PRECHECK files -> PRECHECK.json (rule delta_dec = 15)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hospitalos.howm import corpus as C  # noqa: E402
from hospitalos.howm.generator import EVAL_DAY, INSTANT_HOURS, PARTITION_SIZES  # noqa: E402
from hospitalos.howm.keys import key  # noqa: E402

EVID = C.EVID
G0 = EVID / "COMMITMENT_G0.json"
DELTA_DEC = 15.0


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def cmd_g0() -> None:
    if G0.exists():
        raise SystemExit("G0 already written: refused")
    from hospitalos.howm.ledger import notes

    if not any(r.get("kind") == "norm_recorded" for r in notes()):
        raise SystemExit("norm v1.2 must be recorded before G0")
    body = {
        "schema": "HOWM1_G0_1",
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "code": C.code_hashes(),
        "norm": {
            p: sha(ROOT / p)
            for p in (
                "docs/howm1/NORME_HOWM1_R0_R1_v1_2.md",
                "docs/howm1/EXPERIMENT_HOWM1_R0_R1_v1_2.json",
            )
        },
        "accord_sha256": sha(ROOT / "docs/howm1/inputs/accord/ACCORD_HOWM1_v1_1_ADOPTE.txt"),
        "partitions": PARTITION_SIZES,
        "origins": {k: [v[0], v[-1], len(v)] for k, v in C.ORIGINS.items()},
        "sealed_reserve_seed_digest": C.sealed_seed_digest(),
        "seed_rule": "establishment key = key('HOWM1', partition, index); realisation r and primitives keyed",
        "bootstrap_seed": int(key("HOWM1", "bootstrap") % (2**31)),
        "decision_instants": {"day": EVAL_DAY, "local_hours": list(INSTANT_HOURS)},
        "delta_dec": DELTA_DEC,
        "rules": "population laws/mixtures fixed by code hash; never tuned on any model gain; DEVTEST/DIAG_DEV read once after F1",
    }
    G0.write_text(json.dumps(body, indent=1) + "\n")
    print(json.dumps({"G0_sha256": sha(G0), "files": len(body["code"])}))


def _check_g0() -> dict:
    g0 = json.loads(G0.read_text())
    if g0["code"] != C.code_hashes():
        raise SystemExit("code differs from G0 commitment: refused")
    return g0


def cmd_gen(partition: str) -> None:
    _check_g0()
    man = (
        json.loads(C.MANIFEST.read_text())
        if C.MANIFEST.exists()
        else {"g0_sha256": sha(G0), "files": {}}
    )
    t0 = time.time()
    for i in range(PARTITION_SIZES[partition]):
        k = f"{partition}/{i:03d}"
        if k in man["files"]:
            continue
        man["files"][k] = C.write_establishment(partition, i)
        C.MANIFEST.write_text(json.dumps(man, indent=1) + "\n")
    print(
        json.dumps(
            {
                "partition": partition,
                "n": PARTITION_SIZES[partition],
                "seconds": round(time.time() - t0, 2),
            }
        )
    )


def cmd_constants() -> None:
    _check_g0()
    from hospitalos.howm.rollout import TARGET_NAMES, truth_vector

    vals = []
    for i in range(PARTITION_SIZES["TRAIN"]):
        ep = C.load("TRAIN", i)["episode"]
        for H in range(24, 168):
            vals.append(truth_vector(ep, H, 0) or [np.nan] * len(TARGET_NAMES))
    arr = np.array(vals, float)
    s = {n: float(np.nanstd(arr[:, j])) for j, n in enumerate(TARGET_NAMES)}
    out = {
        "rule": "s_c = std of the target over TRAIN establishments x hours 24..167 (TRAIN only); s_c == 0 -> excluded and reported",
        "s_c": s,
        "excluded": [n for n, v in s.items() if v == 0.0],
    }
    (EVID / "CRPS_SCALES.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out))


def cmd_precheck(start: int, stop: int) -> None:
    _check_g0()
    from hospitalos.howm.controllers import evaluate_instant
    from hospitalos.howm.history import PublicStream

    d = EVID / "precheck"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(start, min(stop, PARTITION_SIZES["VAL"])):
        f = d / f"VAL_{i:03d}.json"
        if f.exists():
            continue
        ep = C.load("VAL", i)["episode"]
        rows = []
        for h in INSTANT_HOURS:
            tau = EVAL_DAY * 96 + h * 4
            ps = PublicStream(ep.observations)
            ps.advance(tau * 15)
            out = evaluate_instant(
                ep, tau, ps.to_engine(tau * 15), {}, controllers=("C_full", "C_param", "C_pub_snap")
            )
            rows.append(out)
        f.write_text(json.dumps({"index": i, "mech": ep.spec.mech, "instants": rows}) + "\n")
        print(
            i, {r["tau"]: {k: round(v, 1) for k, v in r["value"].items()} for r in rows}, flush=True
        )


def cmd_precheck_summary() -> None:
    d = EVID / "precheck"
    vp, vl, ceil, per = [], [], [], []
    for i in range(PARTITION_SIZES["VAL"]):
        r = json.loads((d / f"VAL_{i:03d}.json").read_text())
        for ins in r["instants"]:
            v = ins["value"]
            vp.append(v["C_pub_snap"] - v["C_param"])
            vl.append(v["C_param"] - v["C_full"])
            ceil.append(v["C_full"] - ins["oracle_U_star"])
            per.append(
                {
                    "index": i,
                    "tau": ins["tau"],
                    **{k: round(x, 2) for k, x in v.items()},
                    "oracle": round(ins["oracle_U_star"], 2),
                }
            )
    margin = float(np.mean(vp) + np.mean(vl))
    out = {
        "name": "margin observed under privileged information (NORM N2.3)",
        "V_param": float(np.mean(vp)),
        "V_latent": float(np.mean(vl)),
        "margin": margin,
        "ceiling_C_full_minus_oracle": float(np.mean(ceil)),
        "delta_dec": DELTA_DEC,
        "decision_comparison_informative": margin >= DELTA_DEC,
        "n_instants": len(vp),
        "per_instant": per,
        "note": "C_full is an evaluated privileged controller, not a certified optimum; the generator is NOT modified whatever the outcome",
    }
    (EVID / "PRECHECK.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "per_instant"}))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--partition", default="")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--stop", type=int, default=10**6)
    a = ap.parse_args()
    {"g0": cmd_g0, "constants": cmd_constants, "precheck-summary": cmd_precheck_summary}.get(
        a.cmd, lambda: None
    )()
    if a.cmd == "gen":
        cmd_gen(a.partition)
    elif a.cmd == "precheck":
        cmd_precheck(a.start, a.stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
