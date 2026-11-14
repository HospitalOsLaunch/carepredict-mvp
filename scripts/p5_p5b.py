#!/usr/bin/env python3
"""P5b under authorisation (iii), option A (L2: 28 fits). Every sub-command runs under the counter.

Order enforced (each step refuses if its predecessor is missing):
  run --partition P5b_train --from i --to j      train labels (R1, K=3)
  precheck                                       twin precheck; NOT informative -> STOP before validation
  run --partition P5b_val ...                    validation labels (R1, K=3)
  matrices --partition P5b_train|P5b_val         feature matrices (regenerated public episodes)
  fit --family F --depth D --lr L --iters a,b --seed 0       24 selection fits (seed 0)
  select                                         per-family selection on validation
  fit ... --seed 1|2 (selected config only)      4 inter-seed controls
  controls                                       control summary (max abs prediction difference)
  precision                                      Delta_rep projection on validation (before F_b)
  isolation-select / isolation-check             50 episodes, method v2 for models (before F_b)
  freeze                                         F_b document (then a ledger note freeze_F_b)
  run --partition P5b_eval ...                   reserved evaluation (refused without F_b)
  matrices --partition P5b_eval ; predict-eval ; analyse
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import sys
import time
from pathlib import Path

T0 = time.perf_counter()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
import p5_budget_run as runner  # noqa: E402

from hospitalos.decision_support.planner import Settings  # noqa: E402
from hospitalos.decision_support.snapshot import CONFIG_DIR, load_json, load_profile  # noqa: E402
from hospitalos.p5 import integrity  # noqa: E402
from hospitalos.p5 import p5b as B  # noqa: E402
from hospitalos.p5 import p5b_analysis as BA  # noqa: E402
from hospitalos.p5 import p5b_isolation as BI  # noqa: E402
from hospitalos.p5.a5 import FIXED  # noqa: E402
from hospitalos.p5.pilot import (  # noqa: E402
    PilotStop,
    ResumeRefused,
    RuntimeRefused,
    check_runtime,
    run_identity,
    running_environment,
    structure_id,
)

P5 = ROOT / "evidence" / "decision_support" / "p5"
OUT = P5 / "p5b"
ART = OUT / "artifacts"
SIZES = {"P5b_train": (24, 15), "P5b_val": (8, 15), "P5b_eval": (30, 4)}
REGIMES = {"P5b_train": ("R1",), "P5b_val": ("R1",), "P5b_eval": ("R1", "R2")}
K = 3
GRID = [(d, lr, it) for d in (3, 5) for lr in (0.05, 0.1) for it in (100, 200, 400)]
MS_PER_TREE_1440 = {"M_agg": 4.42, "M_ent": 11.55}  # A5 measurements (upper side: depth 5)
COMMAND_SAFE_S = 27.0


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def jl(path: Path) -> list:
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def write(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=1, sort_keys=True, default=float) + "\n")


def guarded():
    commitment = integrity.verify(integrity.effective_commitment())
    env = running_environment()
    ledger = runner.base.read_ledger(runner.LEDGER)
    check_runtime(env, runner.approved_environments(ledger))
    return commitment, env, ledger


def identity_for(partition, commitment, env):
    seeds = json.loads((P5 / "SEEDS_SEALED.json").read_text())["partitions"][partition]
    code = hashlib.sha256((ROOT / "src/hospitalos/p5/p5b.py").read_bytes() + (ROOT / "scripts/p5_p5b.py").read_bytes()).hexdigest()
    return run_identity(commitment, partition, seeds, SIZES[partition][1], K, REGIMES[partition], env, code), seeds


def exec_dir(identity) -> Path:
    return OUT / identity["partition"] / "executions" / identity["run_id"]


def load_exec(partition, commitment, env, complete=True):
    ident, seeds = identity_for(partition, commitment, env)
    d = exec_dir(ident)
    recs, meta = jl(d / "parents.jsonl"), jl(d / "structures.jsonl")
    n_s, n_p = SIZES[partition]
    if complete and len(recs) != n_s * n_p:
        raise SystemExit(f"refused: {partition} incomplete ({len(recs)}/{n_s * n_p})")
    return ident, seeds, recs, meta, d


def seed_map(partition, seeds):
    return {structure_id(partition, s): s for s in seeds}


def bootstrap_seed(freeze_hash: str | None = None) -> int:
    seeds = json.loads((P5 / "SEEDS_SEALED.json").read_text())
    seed = int(seeds["bootstrap_seed"])
    committed = json.loads((P5 / "COMMITMENT_E0.json").read_text())["seeds"]["bootstrap_seed_sha256"]
    if hashlib.sha256((str(seed) + seeds["salt"]).encode()).hexdigest() != committed:
        raise SystemExit("refused: bootstrap seed does not match its E0 commitment")
    return seed


def fit_estimate(family: str, rows: int, iters: int) -> float:
    return MS_PER_TREE_1440[family] / 1000 * rows / 1440 * iters


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--partition", default="P5b_train")
    ap.add_argument("--from", dest="start", type=int, default=0)
    ap.add_argument("--to", dest="stop", type=int, default=None)
    ap.add_argument("--family", default="M_agg")
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--iters", default="100")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    try:
        commitment, env, ledger = guarded()
    except (integrity.IntegrityError, RuntimeRefused) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 3
    OUT.mkdir(parents=True, exist_ok=True)
    profile = load_profile()

    if a.cmd == "run":
        if a.partition == "P5b_val" and not json.loads((OUT / "PRECHECK.json").read_text() if (OUT / "PRECHECK.json").exists() else "{}").get("informative"):
            print("refused: validation requires an informative twin precheck", file=sys.stderr)
            return 4
        if a.partition == "P5b_eval":
            try:
                BI.require_freeze(ledger, {f: sha(ROOT / f) for f in json.loads((OUT / "F_b.json").read_text())["files_sha256"]} if (OUT / "F_b.json").exists() else {})
            except BI.FreezeMissing as error:
                print(f"refused: {error}", file=sys.stderr)
                return 4
        ident, seeds = identity_for(a.partition, commitment, env)
        n_s = SIZES[a.partition][0]
        try:
            out = B.run_segment(out_dir=OUT / a.partition, identity=ident, seeds=seeds,
                                indices=range(a.start, min(a.stop if a.stop is not None else n_s, n_s)), profile=profile,
                                score=load_json(CONFIG_DIR / "PRESSURE_SCORE_CONFIG.json"),
                                with_planner=a.partition == "P5b_eval", settings=Settings.default())
        except (PilotStop, ResumeRefused) as error:
            print(f"STOP: {error}", file=sys.stderr)
            return 6
        print(json.dumps(out))
        return 0

    if a.cmd == "precheck":
        _, _, recs, meta, _ = load_exec("P5b_train", commitment, env)
        res = B.precheck(recs, bootstrap_seed())
        res["train_exclusions"] = {"candidates": sum(m["candidates"] for m in meta), "excluded": sum(sum(m["exclusions"].values()) for m in meta)}
        write(OUT / "PRECHECK.json", res)
        print(json.dumps(res))
        return 0 if res["informative"] else 8

    if a.cmd == "matrices":
        if a.partition == "P5b_eval":
            try:
                BI.require_freeze(ledger, {f: sha(ROOT / f) for f in json.loads((OUT / "F_b.json").read_text())["files_sha256"]})
            except (BI.FreezeMissing, FileNotFoundError) as error:
                print(f"refused: {error}", file=sys.stderr)
                return 4
        _, seeds, recs, _, _ = load_exec(a.partition, commitment, env)
        m = B.build_matrices(recs, seed_map(a.partition, seeds), a.partition, profile, SIZES[a.partition][1])
        ART.mkdir(parents=True, exist_ok=True)
        path = ART / f"{a.partition}_matrices.npz"
        np.savez(path, M_agg=m["M_agg"], M_ent=m["M_ent"], y=m["y"], w=m["w"], index=np.asarray(m["index"], dtype=object))
        body = {"partition": a.partition, "rows": len(m["y"]), "features": {"M_agg": m["M_agg"].shape[1], "M_ent": m["M_ent"].shape[1]},
                "npz_sha256": sha(path), "seconds": time.perf_counter() - T0}
        write(OUT / f"MATRICES_{a.partition}.json", body)
        print(json.dumps(body))
        return 0

    if a.cmd == "fit":
        from hospitalos.p5.a5 import check_threads
        check_threads()
        from sklearn.ensemble import HistGradientBoostingRegressor
        fits = jl(OUT / "FITS.jsonl")
        sel = json.loads((OUT / "SELECTION.json").read_text()) if (OUT / "SELECTION.json").exists() else None
        tr = np.load(ART / "P5b_train_matrices.npz", allow_pickle=True)
        va = np.load(ART / "P5b_val_matrices.npz", allow_pickle=True)
        for name, rec in (("P5b_train", tr), ("P5b_val", va)):
            if sha(ART / f"{name}_matrices.npz") != json.loads((OUT / f"MATRICES_{name}.json").read_text())["npz_sha256"]:
                print("refused: matrices differ from their receipt", file=sys.stderr)
                return 4
        done_now = []
        for it in [int(x) for x in a.iters.split(",")]:
            cfg = (a.depth, a.lr, it)
            if cfg not in GRID:
                print(f"refused: {cfg} not in grid", file=sys.stderr)
                return 4
            if a.seed != 0 and (sel is None or list(cfg) != sel[a.family]["config"]):
                print("refused: seeds 1/2 only for the selected configuration (L2 controls)", file=sys.stderr)
                return 4
            if any(f["family"] == a.family and f["config"] == list(cfg) and f["seed"] == a.seed for f in fits + done_now):
                continue
            est = fit_estimate(a.family, len(tr["y"]), it)
            if est > COMMAND_SAFE_S:
                write(OUT / "FIT_STOP.json", {"reason": "single_fit_projected_over_30s", "family": a.family, "config": list(cfg), "estimate_s": est})
                print(f"STOP: projected single fit {est:.1f}s > 30 s rule", file=sys.stderr)
                return 6
            if (time.perf_counter() - T0) + est > COMMAND_SAFE_S:
                print(json.dumps({"deferred": list(cfg)}))
                break
            model = HistGradientBoostingRegressor(**FIXED, max_depth=a.depth, learning_rate=a.lr, max_iter=it, random_state=a.seed)
            t = time.perf_counter()
            model.fit(tr[a.family], tr["y"], sample_weight=tr["w"])
            fit_s = time.perf_counter() - t
            pred = model.predict(va[a.family])
            stem = f"{a.family}_d{a.depth}_lr{a.lr}_it{it}_s{a.seed}"
            mpath, ppath = ART / f"model_{stem}.pkl", ART / f"valpred_{stem}.npy"
            mpath.write_bytes(pickle.dumps(model))
            np.save(ppath, pred)
            row = {"family": a.family, "config": list(cfg), "seed": a.seed, "fit_s": fit_s, "n_iter": int(model.n_iter_),
                   "model_sha256": sha(mpath), "valpred_sha256": sha(ppath), "role": "selection" if a.seed == 0 else "L2_control"}
            with (OUT / "FITS.jsonl").open("a") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
            done_now.append(row)
        print(json.dumps([{k: r[k] for k in ("family", "config", "seed", "fit_s", "n_iter")} for r in done_now]))
        return 0

    if a.cmd == "select":
        fits = [f for f in jl(OUT / "FITS.jsonl") if f["seed"] == 0]
        if len(fits) != 24:
            print(f"refused: {len(fits)}/24 selection fits", file=sys.stderr)
            return 4
        _, _, vrecs, _, _ = load_exec("P5b_val", commitment, env)
        va = np.load(ART / "P5b_val_matrices.npz", allow_pickle=True)
        index = [tuple(x) for x in va["index"]]
        table = {}
        for f in fits:
            stem = f"{f['family']}_d{f['config'][0]}_lr{f['config'][1]}_it{f['config'][2]}_s0"
            pred = np.load(ART / f"valpred_{stem}.npy")
            ch = B.choices(pred, index, vrecs)
            table.setdefault(f["family"], []).append({"config": f["config"], "realised_U": B.realised_choice_value(ch, vrecs),
                                                      "mae": B.weighted_mae(pred, va["y"], va["w"])})
        sel = {}
        for fam, rows in table.items():
            best = min(rows, key=lambda r: (round(r["realised_U"], 9), r["mae"], r["config"][2], r["config"][0]))
            sel[fam] = {"config": best["config"], "realised_U": best["realised_U"], "mae": best["mae"], "table": rows}
        write(OUT / "SELECTION.json", sel)
        print(json.dumps({f: sel[f]["config"] for f in sel}))
        return 0

    if a.cmd == "controls":
        sel = json.loads((OUT / "SELECTION.json").read_text())
        fits = jl(OUT / "FITS.jsonl")
        out = {}
        for fam, s in sel.items():
            c = s["config"]
            diffs = {}
            ref = np.load(ART / f"valpred_{fam}_d{c[0]}_lr{c[1]}_it{c[2]}_s0.npy")
            for seed in (1, 2):
                if not any(f["family"] == fam and f["config"] == c and f["seed"] == seed for f in fits):
                    print(f"refused: control fit missing {fam} seed {seed}", file=sys.stderr)
                    return 4
                p = np.load(ART / f"valpred_{fam}_d{c[0]}_lr{c[1]}_it{c[2]}_s{seed}.npy")
                diffs[str(seed)] = float(np.max(np.abs(p - ref)))
            out[fam] = {"config": c, "max_abs_diff_vs_seed0": diffs, "identical": all(v <= 1e-12 for v in diffs.values())}
        out["total_fits"] = len(fits)
        write(OUT / "CONTROLS.json", out)
        print(json.dumps(out))
        return 0

    if a.cmd == "precision":
        sel = json.loads((OUT / "SELECTION.json").read_text())
        _, _, vrecs, _, _ = load_exec("P5b_val", commitment, env)
        va = np.load(ART / "P5b_val_matrices.npz", allow_pickle=True)
        index = [tuple(x) for x in va["index"]]
        ch = {}
        for fam, s in sel.items():
            c = s["config"]
            ch[fam] = B.choices(np.load(ART / f"valpred_{fam}_d{c[0]}_lr{c[1]}_it{c[2]}_s0.npy"), index, vrecs)
        structs = BA.group(vrecs, ch["M_agg"], ch["M_ent"], "R1")
        proj = BA.precision_projection(structs, SIZES["P5b_eval"][0])
        write(OUT / "PRECISION_P5b.json", {**proj, "note": "validation: only the projection is read before F_b"})
        print(json.dumps(proj))
        return 0

    if a.cmd in ("isolation-select", "isolation-check"):
        _, vseeds, vrecs, _, _ = load_exec("P5b_val", commitment, env)
        path = OUT / "ISOLATION50_SELECTION.json"
        if a.cmd == "isolation-select":
            if path.exists():
                print("refused: selection already written", file=sys.stderr)
                return 2
            eps = sorted((r["structure_id"], r["parent_index"], t) for r in vrecs for t in ("A", "B"))
            sel = BI.select(eps, commitment["commitment_id"])
            write(path, {"selection": [list(x) for x in sel], "rule": BI.RULE, "module_sha256": sha(ROOT / "src/hospitalos/p5/p5b_isolation.py"),
                         "selection_sha256": hashlib.sha256(json.dumps([list(x) for x in sel]).encode()).hexdigest()})
            print(json.dumps({"selected": len(sel)}))
            return 0
        notes = [r for r in ledger if r.get("kind") == "p5b_isolation_procedure"]
        if not path.exists() or not notes or notes[-1]["payload"] != json.loads(path.read_text()):
            print("refused: isolation selection missing or not recorded", file=sys.stderr)
            return 4
        sel = json.loads((OUT / "SELECTION.json").read_text())
        models = {}
        for fam, s in sel.items():
            c = s["config"]
            models[fam] = pickle.loads((ART / f"model_{fam}_d{c[0]}_lr{c[1]}_it{c[2]}_s0.pkl").read_bytes())
        rec_by = {(r["structure_id"], r["parent_index"]): r for r in vrecs}
        receipts = OUT / "ISOLATION50_RECEIPTS.jsonl"
        done = {(r["structure_id"], r["parent_index"], r["twin"]) for r in jl(receipts)}
        todo = [tuple(x) for x in json.loads(path.read_text())["selection"] if tuple(x) not in done][a.start:a.stop]
        smap = seed_map("P5b_val", vseeds)
        try:
            for sid, p, t in todo:
                if time.perf_counter() - T0 > 24:
                    print(json.dumps({"deferred_from": [sid, p, t]}))
                    break
                ep = BI.reconstruct(sid, p, t, smap, rec_by[(sid, p)], profile)
                r = BI.check_episode(ep, models, profile, Settings.default(), commitment["commitment_id"])
                with receipts.open("a") as fh:
                    fh.write(json.dumps({"structure_id": sid, "parent_index": p, "twin": t, **r}, sort_keys=True) + "\n")
        except BI.IsolationFailure as fail:
            write(OUT / "ISOLATION50_FAILURE.json", {"kind": fail.kind, "detail": fail.detail})
            print(f"STOP: {fail}", file=sys.stderr)
            return 6
        rs = jl(receipts)
        summ = {"checked": len(rs), "T04a_detected": sum(r["T04a"] == "DETECTED" for r in rs),
                "T04a_non_informatif": sum(r["T04a"] == "NON_INFORMATIF" for r in rs), "true_failures": 0}
        write(OUT / "ISOLATION50_SUMMARY.json", summ)
        print(json.dumps(summ))
        return 0

    if a.cmd == "freeze":
        need = ["PRECHECK.json", "SELECTION.json", "CONTROLS.json", "PRECISION_P5b.json", "ISOLATION50_SUMMARY.json"]
        missing = [n for n in need if not (OUT / n).exists()]
        iso = json.loads((OUT / "ISOLATION50_SUMMARY.json").read_text()) if (OUT / "ISOLATION50_SUMMARY.json").exists() else {}
        if missing or iso.get("checked") != 50 or (OUT / "ISOLATION50_FAILURE.json").exists():
            print(f"refused: prerequisites missing {missing} or isolation incomplete", file=sys.stderr)
            return 4
        sel = json.loads((OUT / "SELECTION.json").read_text())
        files = ["docs/decision_support/P5_PROTOCOL_v3.md", "docs/decision_support/P5_PROTOCOL_PARAMS_v3.json",
                 "docs/decision_support/P5_PROTOCOL_v3_1.md", "docs/decision_support/P5_PROTOCOL_PARAMS_v3_1.json",
                 "docs/decision_support/P5_DECISIONS_v7_P5b.json",
                 "src/hospitalos/p5/generator.py", "src/hospitalos/p5/truth.py", "src/hospitalos/p5/eval_adapter.py",
                 "src/hospitalos/p5/features.py", "src/hospitalos/p5/p5b.py", "src/hospitalos/p5/p5b_analysis.py",
                 "src/hospitalos/p5/p5b_isolation.py", "src/hospitalos/p5/p5a_analysis.py", "src/hospitalos/p5/analysis.py",
                 "scripts/p5_p5b.py", "configs/decision_support/UNIT_PROFILE.json", "configs/decision_support/OBJECTIVE_CONFIG.json",
                 "configs/decision_support/PRESSURE_SCORE_CONFIG.json"]
        files += [f"evidence/decision_support/p5/p5b/{n}" for n in need]
        for fam, s in sel.items():
            c = s["config"]
            files.append(f"evidence/decision_support/p5/p5b/artifacts/model_{fam}_d{c[0]}_lr{c[1]}_it{c[2]}_s0.pkl")
        prec = json.loads((OUT / "PRECISION_P5b.json").read_text())
        body = {"stage": "F_b", "effective_commitment": {"stage": commitment["stage"], "ledger_record": commitment["ledger_record_sha256"]},
                "files_sha256": {f: sha(ROOT / f) for f in files}, "delta": BA.DELTA, "harm_max": BA.HARM_MAX,
                "exclusion_max": BA.EXCLUSION_MAX, "half_width_max": BA.HALF_WIDTH_MAX, "bootstrap_resamples": 2000,
                "selected": {f: s["config"] for f, s in sel.items()}, "precision_projection": prec,
                "declared_reading": prec["declared_reading"], "isolation50": iso,
                "reserved": {"partition": "P5b_eval", "structures": 30, "parents": 4, "twins": 2, "regimes": ["R1", "R2"], "K_eval": K}}
        write(OUT / "F_b.json", body)
        print(json.dumps({"declared_reading": body["declared_reading"], "files": len(files)}))
        return 0

    if a.cmd == "predict-eval":
        fb = BI.require_freeze(ledger, {f: sha(ROOT / f) for f in json.loads((OUT / "F_b.json").read_text())["files_sha256"]})
        _, _, erecs, _, _ = load_exec("P5b_eval", commitment, env)
        ev = np.load(ART / "P5b_eval_matrices.npz", allow_pickle=True)
        if sha(ART / "P5b_eval_matrices.npz") != json.loads((OUT / "MATRICES_P5b_eval.json").read_text())["npz_sha256"]:
            print("refused: eval matrices differ from their receipt", file=sys.stderr)
            return 4
        index = [tuple(x) for x in ev["index"]]
        out = {"choices": {}, "fit_quality_R1": {}}
        for fam, c in fb["selected"].items():
            model = pickle.loads((ART / f"model_{fam}_d{c[0]}_lr{c[1]}_it{c[2]}_s0.pkl").read_bytes())
            pred = model.predict(ev[fam])
            ch = B.choices(pred, index, erecs)
            out["choices"][fam] = [[k[0], k[1], k[2], v] for k, v in sorted(ch.items())]
            err = pred - ev["y"]
            out["fit_quality_R1"][fam] = {"mae_weighted": B.weighted_mae(pred, ev["y"], ev["w"]),
                                          "rmse_weighted": float(np.sqrt(np.sum(ev["w"] * err ** 2) / np.sum(ev["w"])))}
        write(OUT / "EVAL_CHOICES.json", out)
        print(json.dumps(out["fit_quality_R1"]))
        return 0

    if a.cmd == "analyse":
        fb = BI.require_freeze(ledger, {f: sha(ROOT / f) for f in json.loads((OUT / "F_b.json").read_text())["files_sha256"]})
        _, _, erecs, emeta, _ = load_exec("P5b_eval", commitment, env)
        chs = json.loads((OUT / "EVAL_CHOICES.json").read_text())["choices"]
        ca = {(s, p, t): i for s, p, t, i in chs["M_agg"]}
        ce = {(s, p, t): i for s, p, t, i in chs["M_ent"]}
        seed = bootstrap_seed()
        precise = fb["precision_projection"]["precision_sufficient"]
        iso_ok = fb["isolation50"].get("true_failures", 1) == 0
        res = {"F_b_declared_reading": fb["declared_reading"], "selected": fb["selected"],
               "R1": BA.analyse(erecs, emeta, ca, ce, "R1", seed, 2000, precise, iso_ok, True),
               "R2": BA.analyse(erecs, emeta, ca, ce, "R2", seed, 2000, precise, iso_ok, False)}
        write(OUT / "RESULTS_P5b.json", res)
        print(json.dumps({r: {"verdict": res[r]["verdict"], "delta_rep": res[r]["point"]["delta_rep"], "ci95": res[r]["ci95"]["delta_rep"]} for r in ("R1", "R2")}))
        return 0

    print(f"unknown command {a.cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    os.environ.setdefault("PYTHONHASHSEED", "0")
    raise SystemExit(main())
