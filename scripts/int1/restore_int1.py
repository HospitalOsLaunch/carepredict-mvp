#!/usr/bin/env python3
"""HOWM-INT-1 receipt in a FRESH environment (decision n.9).

    restore_int1.py setup|tests|load|analysis|regen|refit|assemble ARCHIVE.zip FRESH_PYTHON

Every section is one ledgered command (< 540 s). The orchestrator only extracts, launches and compares; every
computation runs under FRESH_PYTHON, a venv rebuilt from the archived requirements (not the campaign venv), in a
fresh directory extracted from the archive. Section results are written to <fresh>/receipt/<section>.json and
assembled into evidence/howm_int1_receipt/RESTORE_RECEIPT_INT1.json.

Rules (mandate s.12; defects of earlier receipts not repeated):
  * SEPARATE OUTPUTS: reproductions and regenerations write under <fresh>/repro/, never over the archived files
    they are compared with (archived originals are never deleted or replaced); refits write to their own run dir.
  * TIMING RULE (documented): before any comparison, keys that are run-time measurements are removed recursively:
    any key named seconds, fit_seconds, train_seconds, wall_s, or containing "cpu_s" (decision CPU times).
    Nothing else is excluded. Scientific values are compared exactly (regenerations, analysis) or within
    rtol 1e-6 (re-evaluation of recorded VAL metrics of loaded models).
  * PER-FILE PARAMETERS: every regenerated file is re-run with the parameters read from the archived file itself
    (panel, structure, episode, future; corpus part, structure, K).
  * Sections that fail are reported as failed; nothing is retried silently.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
S = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad")
FRESH = S / "int1_receipt_fresh"
REC = ROOT / "evidence/howm_int1_receipt"
TIMING_EXACT = {"seconds", "fit_seconds", "train_seconds", "wall_s"}
TIMING_RULE = "keys named seconds, fit_seconds, train_seconds, wall_s, or containing 'cpu_s' are removed recursively before comparison"
REGEN = {"eval": [("MAIN", 17, 1, None), ("SIZE12", 5, 2, None), ("SUB32", 0, 2, 2)],
         "corpus": [("INT_TRAIN", 137), ("INT_TRAIN", 9001), ("INT_VAL", 5)]}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def strip(x):
    if isinstance(x, dict):
        return {k: strip(v) for k, v in x.items() if k not in TIMING_EXACT and "cpu_s" not in k}
    if isinstance(x, list):
        return [strip(v) for v in x]
    return x


def close(a, b, rtol=0.0):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(close(a[k], b[k], rtol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y, rtol) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return a == b or abs(a - b) <= rtol * max(abs(a), abs(b))
    return a == b


def diffs(a, b, path="", rtol=0.0, out=None):
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}/{k}: missing")
            else:
                diffs(a[k], b[k], f"{path}/{k}", rtol, out)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            diffs(x, y, f"{path}[{i}]", rtol, out)
    elif not close(a, b, rtol):
        out.append(f"{path}: {str(a)[:80]} != {str(b)[:80]}")
    return out[:20]


PRELUDE = """
import os, sys, json
os.environ['OMP_NUM_THREADS'] = '1'
T, D, R = {tree!r}, {data!r}, {repro!r}
from pathlib import Path
sys.path[:0] = [T + '/src', T + '/scripts', T + '/scripts/int1']
import torch; torch.set_num_threads(1)
"""


def pyproc(py, fresh, code, extra_env=None):
    pre = PRELUDE.format(tree=str(fresh / "tree"), data=str(fresh / "data"), repro=str(fresh / "repro"))
    return subprocess.Popen([py, "-c", pre + code], cwd=fresh / "tree", stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env={**tree_env(fresh), **(extra_env or {})})


def tree_env(fresh):
    """Explicit environment for every fresh-tree subprocess: the ledger runner exports PYTHONPATH=<repo>/src:<repo>
    (rehearsal finding); it is REPLACED so that only the extracted tree is importable."""
    return {**{k: v for k, v in os.environ.items() if k != "PYTHONPATH"}, "PYTHONPATH": f"{fresh / 'tree/src'}:{fresh / 'tree'}", "OMP_NUM_THREADS": "1"}


def collect(p):
    so, se = p.communicate()
    lines = [ln for ln in so.strip().splitlines() if ln.startswith("{")]
    return (json.loads(lines[-1]) if lines else {"error": se.strip().splitlines()[-3:]}), p.returncode


def sec_setup(z, py, fresh):
    if fresh.exists():
        shutil.rmtree(fresh)
    fresh.mkdir(parents=True)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(fresh)
    lines = (fresh / "SHA256SUMS").read_text().splitlines()
    bad = [rel for h, rel in (ln.split("  ", 1) for ln in lines) if sha(fresh / rel) != h]
    (fresh / "tree").mkdir()
    with tarfile.open(fresh / "source_tree.tar.gz") as tf:
        tf.extractall(fresh / "tree", filter="data")
    ev = fresh / "tree/evidence/howm_int1"
    fr = json.loads((ev / "FREEZE_INT1.json").read_text())
    models_bad = [k for k, h in fr["models_sha256"].items() if sha(fresh / "data" / k) != h]
    scripts_bad = [k for k, h in fr["files_sha256"].items() if not (fresh / "tree" / k).exists() or sha(fresh / "tree" / k) != h]
    man = json.loads((ev / "MANIFEST_CORPUS.json").read_text())
    corpus_bad, corpus_n = [], 0
    for part in ("INT_TRAIN", "INT_VAL"):
        for row in man[part]["rows"]:
            f = fresh / "data/int1_corpus" / part / f"s{row['s']:05d}.npz"
            if f.exists():
                corpus_n += 1
                if sha(f) != row["sha256"]:
                    corpus_bad.append(f"{part}/{f.name}")
    freeze_pip = subprocess.run([py, "-m", "pip", "freeze"], capture_output=True, text=True).stdout
    origin = subprocess.run([py, "-c", "import hospitalos.howmint.world as w, torch, sklearn; print(w.__file__); print(torch.__version__, sklearn.__version__)"],
                            cwd=fresh / "tree", capture_output=True, text=True, env=tree_env(fresh)).stdout.split()
    env = {"python": subprocess.run([py, "-c", "import sys; print(sys.version.split()[0])"], capture_output=True, text=True).stdout.strip(),
           "pip_freeze_sha256": hashlib.sha256(freeze_pip.encode()).hexdigest(),
           # compared as a set of lines: pip orders case-sensitively, the archived file case-insensitively (rehearsal finding)
           "matches_archived_requirements": sorted(freeze_pip.split()) == sorted((fresh / "requirements_frozen.txt").read_text().split()),
           "interpreter": py, "campaign_venv_not_used": "venv_howm" not in py,
           "hospitalos_imported_from": origin[0] if origin else None, "torch_sklearn": origin[1:] if origin else None}
    env["imports_from_fresh_tree"] = bool(env["hospitalos_imported_from"] and env["hospitalos_imported_from"].startswith(str(fresh / "tree")))
    (fresh / "receipt").mkdir()
    (fresh / "repro").mkdir()
    # scripts changed after the freeze are listed (they must be exactly the declared ones)
    return {"archive_files": len(lines), "bad": bad, "frozen_models_hash_mismatch": models_bad,
            "frozen_scripts_changed_since_freeze": scripts_bad, "corpus_files_checked_against_manifest": corpus_n, "corpus_hash_mismatch": corpus_bad,
            "environment": env,
            "ok": not bad and not models_bad and not corpus_bad and env["matches_archived_requirements"] and env["campaign_venv_not_used"]
            and env["imports_from_fresh_tree"]}


M7 = "tests/howm_int1/test_models.py::test_m7_historical_sources_and_results_unchanged"


def sec_tests(z, py, fresh):
    """All INT-1 tests under the fresh interpreter and tree. M7 (historical files unchanged) reads files that are not
    in the git archive (historical model binaries, gitignored): it is deselected here and replaced by the same
    check on the files present in the archive; absent files are listed, not counted as passed."""
    r = subprocess.run([py, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/howm_int1", "--deselect", M7], cwd=fresh / "tree",
                       capture_output=True, text=True, env=tree_env(fresh))
    latest = {}
    for fr in ("evidence/howm2_bfrag/FREEZE_BFRAG.json", "evidence/howm2_bfrag2/FREEZE1_PROTOCOL.json", "evidence/howm2_bfrag2/FREEZE2_BFRAG2.json",
               "evidence/howm2_bfrag2w/FREEZE_PILOT.json"):
        latest.update(json.loads((fresh / "tree" / fr).read_text())["files_sha256"])
    present = {p: h for p, h in latest.items() if (fresh / "tree" / p).exists()}
    mism = [p for p, h in present.items() if sha(fresh / "tree" / p) != h]
    absent = sorted(set(latest) - set(present))
    m7 = {"historical_files": len(latest), "present_in_archive_and_identical": len(present) - len(mism), "mismatch": mism,
          "absent_from_git_archive": absent}
    return {"exit": r.returncode, "tail": r.stdout.strip().splitlines()[-1:], "deselected": [M7], "m7_on_archived_files": m7,
            "ok": r.returncode == 0 and not mism}


LOAD_POLICIES = """
import eval_campaign as EC
EC.S = Path(D)
fr = json.loads(Path(T, 'evidence/howm_int1/FREEZE_INT1.json').read_text())
out = {}
for panel, n, iv in (('MAIN', 2, 24), ('EXT', 8, 6), ('SUB32', 2, 24)):
    pols = EC.build_policies(fr, panel, n, iv, {}, [])
    out[panel] = sorted(pols)
print(json.dumps({'policies_built': out}))
"""

LOAD_W = """
import numpy as np, train_w as TW
from hospitalos.howmint import data as DA, models as MO
run = {run!r}
rd = Path(D, 'int1_runs', run)
cfg = json.loads((rd / 'config.json').read_text())
m = MO.GraphWM(cfg['d'], use_messages=cfg.get('ablate') != 'no_msg', use_history=cfg.get('ablate') != 'no_hist')
m.load_state_dict(torch.load(rd / 'best.pt', weights_only=False)['model'])
st = {{k: (v.item() if v.ndim == 0 else v) for k, v in np.load(rd / 'norm.npz').items()}}
va = DA.situations(DA.load(Path(D, 'int1_corpus'), 'INT_VAL', list(range(300))))
with torch.no_grad():
    ev = TW.evaluate(m, va, st)
rec = json.loads((rd / 'curve.json').read_text())['state']['best']['val']
print(json.dumps({{'run': run, 'reproduced': ev, 'recorded': rec}}))
"""

LOAD_D = """
import numpy as np, train_d as TD
from hospitalos.howmint import data as DA, planners as PL
va = DA.situations(DA.load(Path(D, 'int1_corpus'), 'INT_VAL', list(range(300))))
out = {}
for run, name in (('D_t2_hgb', 'hgb_4'), ('D_t2_ridge', 'ridge_100.0')):
    m = TD.load_d_model(Path(D, 'int1_runs', run, name + '.pkl'))
    def score_rows(s, m=m):
        g = {'unit': s['unit'][0], 'res': s['res'][0], 'glob': s['glob'][0]}
        Ls = DA.LOOKAHEAD_STEPS[s['n']]
        return m.predict(np.stack([PL.fixed_features(g, {'U': s['U'][i], 'R': s['R'][i]}, s['desc'][i], Ls) for i in range(len(s['desc']))]))
    out[run + '/' + name] = {'reproduced': TD.val_metrics(score_rows, va),
                             'recorded': json.loads(Path(D, 'int1_runs', run, 'result.json').read_text())[name]['val']}
print(json.dumps(out))
"""


def sec_load(z, py, fresh):
    procs = {"policies": pyproc(py, fresh, LOAD_POLICIES), "D": pyproc(py, fresh, LOAD_D),
             "W_t2_S_s0": pyproc(py, fresh, LOAD_W.format(run="W_t2_S_s0")), "W_t2_M_s0": pyproc(py, fresh, LOAD_W.format(run="W_t2_M_s0"))}
    res = {k: collect(p) for k, p in procs.items()}
    out = {"policies_built": res["policies"][0].get("policies_built", res["policies"][0])}
    checks = {}
    for k in ("W_t2_S_s0", "W_t2_M_s0"):
        r = res[k][0]
        checks[k] = {"recorded_VAL_metrics_reproduced": bool("reproduced" in r and close(r["reproduced"], r["recorded"], 1e-6)),
                     "diffs": diffs(r.get("reproduced"), r.get("recorded"), rtol=1e-6) if "reproduced" in r else r}
    for k, r in res["D"][0].items():
        if isinstance(r, dict) and "reproduced" in r:
            checks[k] = {"recorded_VAL_metrics_reproduced": bool(close(r["reproduced"], r["recorded"], 1e-6)), "diffs": diffs(r["reproduced"], r["recorded"], rtol=1e-6)}
        else:
            checks[k] = {"recorded_VAL_metrics_reproduced": False, "error": r}
    out["checks"] = checks
    out["ok"] = all(c["recorded_VAL_metrics_reproduced"] for c in checks.values()) and "MAIN" in out["policies_built"] \
        and all(rc == 0 for _r, rc in res.values())
    return out


ANALYSIS = """
import shutil, re
import analyse as AN, posthoc_main as PH, propagation_w as PW
rp = Path(R, 'analysis'); (rp / 'evidence/howm_int1').mkdir(parents=True, exist_ok=True)
shutil.copy(Path(T, 'evidence/howm_int1/FREEZE_INT1.json'), rp / 'evidence/howm_int1/FREEZE_INT1.json')
AN.OUT, AN.EV = Path(D, 'int1_eval'), rp / 'evidence/howm_int1'
AN.main()
PH.ROOT = rp
PH.main()
PW.S, PW.ROOT = Path(D), rp
PW.main()
src = Path(T, 'scripts/int1/curves.py').read_text()
src = re.sub(r'^S = Path\\(.*\\)$', 'S = Path(D)', src, flags=re.M).replace('ROOT / "evidence/howm_int1/CURVES.json"', 'rp / "evidence/howm_int1/CURVES.json"')
exec(compile(src, 'curves.py (paths substituted)', 'exec'), {'__name__': 'curves', '__file__': T + '/scripts/int1/curves.py', 'D': D, 'rp': rp, 'Path': Path})
print(json.dumps({'written': sorted(p.name for p in (rp / 'evidence/howm_int1').glob('*.json'))}))
"""


def sec_analysis(z, py, fresh):
    r, rc = collect(pyproc(py, fresh, ANALYSIS))
    rp, ev = fresh / "repro/analysis/evidence/howm_int1", fresh / "tree/evidence/howm_int1"
    items = {}
    for f in ("RESULTS_INT1.json", "POSTHOC_MAIN.json", "PROPAGATION_W_VAL.json", "CURVES.json"):
        if not (rp / f).exists():
            items[f] = {"identical": False, "error": "not written"}
            continue
        a, b = strip(json.loads((rp / f).read_text())), strip(json.loads((ev / f).read_text()))
        items[f] = {"identical": bool(close(a, b)), "diffs": diffs(a, b)}
    return {"run": r, "exit": rc, "items": items, "outputs": "repro/analysis (separate from the archived evidence)",
            "ok": rc == 0 and all(v["identical"] for v in items.values())}


REGEN_EVAL = """
import eval_campaign as EC
EC.S, EC.OUT, EC.EV = Path(D), Path(R, 'int1_eval'), Path(T, 'evidence/howm_int1')
fr = json.loads(Path(T, 'evidence/howm_int1/FREEZE_INT1.json').read_text())
panel, s, e, r = {args!r}
EC.job((panel, s, e, fr) if r is None else (panel, s, e, fr, r))
print(json.dumps({{'done': [panel, s, e, r]}}))
"""

REGEN_DEMO = """
import shutil, eval_campaign as EC, demo as DM
EC.S = Path(D)
rp = Path(R, 'demo'); (rp / 'evidence/howm_int1').mkdir(parents=True, exist_ok=True); (rp / 'docs/howm_int1').mkdir(parents=True, exist_ok=True)
shutil.copy(Path(T, 'evidence/howm_int1/FREEZE_INT1.json'), rp / 'evidence/howm_int1/FREEZE_INT1.json')
DM.ROOT = rp
DM.main()
print(json.dumps({'done': 'demo'}))
"""


def sec_regen(z, py, fresh):
    data, repro = fresh / "data", fresh / "repro"
    plan, procs = [], []
    for panel, s, e, r in REGEN["eval"]:
        orig = data / "int1_eval" / panel / (f"s{s:04d}_e{e}.json" if r is None else f"s{s:04d}_e{e}_r{r}.json")
        rec = json.loads(orig.read_text())  # per-file parameters read from the archived file itself
        args = (rec["panel"], rec["structure"], rec["episode"], None if r is None else int(next(iter(rec["futures"]))))
        plan.append(("eval", orig, repro / "int1_eval" / panel / orig.name, args))
        procs.append(pyproc(py, fresh, REGEN_EVAL.format(args=args)))
    for part, s in REGEN["corpus"]:
        orig = data / "int1_corpus" / part / f"s{s:05d}.json"
        meta = json.loads(orig.read_text())
        cmd = ["scripts/int1/corpus.py", "--part", meta["part"], "--s0", str(meta["structure"]), "--s1", str(meta["structure"] + 1), "--par", "1",
               "--budget", "500", "--out", str(repro / "corpus")]
        if part == "INT_VAL":
            cmd += ["--K", str(meta["K"])]
        plan.append(("corpus", orig, repro / "corpus" / part / orig.name, cmd[2:]))
        procs.append(subprocess.Popen([py, *cmd], cwd=fresh / "tree", stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=tree_env(fresh)))
    plan.append(("demo", fresh / "tree/evidence/howm_int1/DEMO.json", repro / "demo/evidence/howm_int1/DEMO.json", "fixed DEV cases of demo.py"))
    procs.append(pyproc(py, fresh, REGEN_DEMO))
    rcs = [p.communicate() and p.returncode for p in procs]
    import numpy as np

    items = {}
    for (kind, orig, new, params), rc in zip(plan, rcs):
        key = f"{kind}:{orig.parent.name}/{orig.name}"
        if not new.exists():
            items[key] = {"identical": False, "exit": rc, "params": params, "error": "not regenerated"}
            continue
        a, b = strip(json.loads(new.read_text())), strip(json.loads(orig.read_text()))
        same = close(a, b)
        it = {"params": params, "exit": rc, "json_identical_after_timing_rule": bool(same), "diffs": diffs(a, b)}
        if kind == "corpus":
            za, zb = np.load(new.with_suffix(".npz")), np.load(orig.with_suffix(".npz"))
            arr = sorted(za.files) == sorted(zb.files) and all(np.array_equal(za[k], zb[k]) for k in za.files)
            it["arrays_identical"] = bool(arr)
            it["note"] = "npz bytes embed zip timestamps; arrays compared exactly (archived original hash-checked against the manifest in setup)"
            same = same and arr
        it["identical"] = bool(same)
        items[key] = it
    return {"items": items, "outputs": "repro/ (separate from the archived originals, which are kept)", "ok": all(v["identical"] for v in items.values())}


REFIT = """
import pickle, numpy as np, train_d as TD
from hospitalos.howmint import data as DA, planners as PL
TD.CORPUS, TD.OUT = Path(D, 'int1_corpus'), Path(R, 'refit_runs')
cfg = {cfg}
sys.argv = ['train_d.py', '--tier', '1', '--which', {which!r}, '--config', str(cfg)]
TD.main()
name = {name!r}
new = TD.load_d_model(Path(R, 'refit_runs', 'D_t1_' + {which!r}, name + '.pkl'))
old = TD.load_d_model(Path(D, 'int1_runs', 'D_t1_' + {which!r}, name + '.pkl'))
va = DA.situations(DA.load(Path(D, 'int1_corpus'), 'INT_VAL', list(range(0, 300, 10))))
X = np.concatenate([np.stack([PL.fixed_features({{'unit': s['unit'][0], 'res': s['res'][0], 'glob': s['glob'][0]}}, {{'U': s['U'][i], 'R': s['R'][i]}}, s['desc'][i],
                    DA.LOOKAHEAD_STEPS[s['n']]) for i in range(len(s['desc']))]) for s in va])
pn, po = new.predict(X), old.predict(X)
rn = json.loads(Path(R, 'refit_runs', 'D_t1_' + {which!r}, 'result.json').read_text())[name]
ro = json.loads(Path(D, 'int1_runs', 'D_t1_' + {which!r}, 'result.json').read_text())[name]
print(json.dumps({{'rows': int(len(X)), 'max_abs_pred_diff': float(np.abs(pn - po).max()), 'pred_identical': bool(np.array_equal(pn, po)),
                  'result_new': rn, 'result_archived': ro}}))
"""


# Per-fit parameter: the archived tier-1 Ridge was fitted with 4 OpenBLAS threads (machine default; float32 normal
# equations depend on the BLAS reduction order). Rehearsal probes #640/#642: 1 thread -> max |dpred| 0.55, 4 -> 0.
REFIT_ENV = {"D_t1_ridge/ridge_100.0": {"OPENBLAS_NUM_THREADS": "4"}, "D_t1_hgb/hgb_4": {}}
# 'bytes' (pickle size) is not compared: it depends on the module name under which the classes were pickled
# (__main__ in the campaign, train_d here), 1 byte apart; predictions are compared exactly instead.
REFIT_NOT_COMPARED = ("bytes",)


def sec_refit(z, py, fresh):
    jobs = {"D_t1_ridge/ridge_100.0": REFIT.format(cfg=1, which="ridge", name="ridge_100.0"),
            "D_t1_hgb/hgb_4": REFIT.format(cfg=0, which="hgb", name="hgb_4")}
    res = {k: collect(pyproc(py, fresh, c, REFIT_ENV[k])) for k, c in jobs.items()}
    items = {}
    for k, (r, rc) in res.items():
        if "rows" not in r:
            items[k] = {"ok": False, "exit": rc, "error": r}
            continue
        a, b = ({kk: vv for kk, vv in strip(x).items() if kk not in REFIT_NOT_COMPARED} for x in (r["result_new"], r["result_archived"]))
        items[k] = {"env": REFIT_ENV[k], "not_compared": REFIT_NOT_COMPARED, "refit_dir": "repro/refit_runs (not the archived run dir)", "val_rows_compared": r["rows"],
                    "predictions_identical": r["pred_identical"], "max_abs_pred_diff": r["max_abs_pred_diff"],
                    "recorded_result_identical_after_timing_rule": bool(close(a, b)), "diffs": diffs(a, b),
                    "ok": bool(r["pred_identical"] and close(a, b))}
    return {"items": items, "ok": all(v["ok"] for v in items.values())}


def sec_assemble(z, py, fresh):
    secs = ["setup", "tests", "load", "analysis", "regen", "refit"]
    out = {"archive": z.name, "archive_sha256": sha(z), "fresh_directory": str(fresh), "fresh_python": py, "timing_rule": TIMING_RULE,
           "regeneration_sample_announced": REGEN}
    for s in secs:
        p = fresh / "receipt" / f"{s}.json"
        out[s] = json.loads(p.read_text()) if p.exists() else {"ok": False, "error": "section not run"}
    out["not_reproduced"] = [
        "W training (12 runs, 2 tiers) and ablations: not retrained; frozen checkpoints hash-checked, loaded, and their recorded VAL metrics re-evaluated (W_t2_S_s0, W_t2_M_s0)",
        "D tier-2 refits (HGB on the 4.3-GB pack, Ridge 10 % subsample) and DSet: not refitted; tier-2 D recorded VAL metrics re-evaluated; tier-1 Ridge and HGB refitted",
        "final evaluation: 3 of 1 320 files regenerated (MAIN, SIZE12, SUB32 one future); the others are archived, hash-checked and used by the reproduced analysis",
        "corpus: 3 structures regenerated; tier-1 (1 000) and VAL archived and checked against the manifest; tier 2 (9 000) described by the manifest only",
        "VAL closed-loop panel, DEV qualification, DEV propagation, SF1 diagnostic, cost pilots: archived outputs only"]
    out["ok"] = all(out[s].get("ok") for s in secs)
    REC.mkdir(exist_ok=True)
    (REC / "RESTORE_RECEIPT_INT1.json").write_text(json.dumps(out, indent=1) + "\n")
    shutil.rmtree(fresh)
    print(json.dumps({s: out[s].get("ok") for s in secs} | {"ok": out["ok"]}))
    return out


def main() -> int:
    sec, z, py = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    fresh = FRESH / z.stem
    t0 = time.time()
    fn = {"setup": sec_setup, "tests": sec_tests, "load": sec_load, "analysis": sec_analysis, "regen": sec_regen, "refit": sec_refit,
          "assemble": sec_assemble}[sec]
    res = fn(z, py, fresh)
    if sec != "assemble":
        res["seconds"] = round(time.time() - t0, 1)
        (fresh / "receipt" / f"{sec}.json").write_text(json.dumps(res, indent=1) + "\n")
        print(json.dumps({k: v for k, v in res.items() if k in ("ok", "seconds", "bad", "exit")} | {"section": sec}))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
