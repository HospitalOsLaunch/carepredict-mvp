#!/usr/bin/env python3
"""Decision n.8 independent restoration receipt (fresh directory). Separate sections:
(1) integrity; (2) tests; (3) reload of frozen models (hashes) and reproduction of recorded predictions;
(4) refits actually executed: D (4 configurations) and W seed 1, compared on predictions; (5) analysis
reproduction (decomposition, pilot results); (6) regenerations actually executed: 1 final-evaluation decision and
1 TRAIN origin, with each file's own parameters (E, Md, K), compared after removing run-time measurements only
(timing_s, seconds, maxrss_mb: documented rule); (7) elements NOT reproduced."""

import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from howm2_c1_restore import close  # noqa: E402

TIMING_KEYS = ("timing_s", "seconds", "maxrss_mb")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def strip(d):
    return {k: v for k, v in d.items() if k not in TIMING_KEYS}


def main() -> int:
    z, py = Path(sys.argv[1]), sys.argv[2]
    t0 = time.time()
    fresh = Path(tempfile.mkdtemp(prefix="restoreBW_", dir=z.parent))
    out = {"package": z.name, "package_sha256": sha(z), "comparison_rule": f"run-time measurements {TIMING_KEYS} excluded from scientific comparisons"}
    with zipfile.ZipFile(z) as zf:
        zf.extractall(fresh)
    bad = [rel for h, rel in (ln.split("  ", 1) for ln in (fresh / "SHA256SUMS").read_text().splitlines()) if sha(fresh / rel) != h]
    out["1_integrity"] = {"files": len((fresh / "SHA256SUMS").read_text().splitlines()), "bad": bad, "ok": not bad}
    tree = fresh / "tree"
    tree.mkdir()
    with tarfile.open(fresh / "source_tree.tar.gz") as tf:
        tf.extractall(tree, filter="data")
    for d in ("howm2_bfrag2", "howm2_bfrag2w"):
        shutil.rmtree(tree / "evidence" / d, ignore_errors=True)
        shutil.copytree(fresh / f"evidence_{d}", tree / "evidence" / d)
    ev = tree / "evidence/howm2_bfrag2w"

    def run(*a):
        return subprocess.run([py, *a], cwd=tree, capture_output=True, text=True)

    def start(*a):
        return subprocess.Popen([py, *a], cwd=tree, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # (6) regenerations, launched first (parallel)
    ef = sorted((ev / "runs/eval").glob("s*_e*.json"))[4]
    eref = json.loads(ef.read_text())
    tf_ = ev / "runs/train/s137_e2.json"
    tref = json.loads(tf_.read_text())
    tnpz = (tf_.with_suffix(".npz")).read_bytes()
    ef.unlink()
    tf_.unlink()
    tf_.with_suffix(".npz").unlink()
    procs = [start("scripts/bf2w_data.py", "eval", "--s0", str(eref["structure"]), "--s1", str(eref["structure"] + 1), "--E", str(eref["E"]),
                   "--Md", str(eref["Md"]), "--par", "1", "--budget", "1000"),
             start("scripts/bf2w_data.py", "train", "--s0", "137", "--s1", "138", "--K", str(len(tref["futures"])), "--par", "1")]
    r = run("-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/bfrag2w", "tests/bfrag2")
    out["2_tests"] = {"exit": r.returncode, "tail": r.stdout.strip().splitlines()[-1:]}
    # (3) reload + reproduce recorded predictions
    sys.path.insert(0, str(tree / "scripts"))
    sys.path.insert(0, str(tree / "src"))
    import bf2w_models as M  # noqa: E402

    M.EV, M.MD = ev, ev / "models"
    fr = json.loads((ev / "FREEZE_PILOT.json").read_text())
    hashes_ok = all(sha(tree / f) == h for f, h in fr["files_sha256"].items() if f.startswith("evidence/howm2_bfrag2w/models/"))
    recs = [json.loads(p.read_text()) for p in sorted((ev / "runs/eval").glob("s*_e*.json"))[:6]]
    rep = all(close(r_["pred"], M.predict_costs(r_)) for r_ in recs)
    out["3_reload_and_reproduce_predictions"] = {"model_hashes_ok": hashes_ok, "recorded_predictions_reproduced": bool(rep), "decisions_checked": len(recs),
                                                 "ok": bool(hashes_ok and rep)}
    # (4) refits
    keep_d = json.loads((ev / "LEARN_D.json").read_text())
    old_d = {k: M.load_d(k) for k in keep_d["configs"]}
    keep_w1 = M.load_w(1)
    run("scripts/bf2w_models.py", "train_d")
    new_d = json.loads((ev / "LEARN_D.json").read_text())
    import numpy as np  # noqa: E402

    val = M.load_val()
    d_same = all(np.allclose(old_d[k].predict(M.xvec(v), np.array([M.adesc(a) for a in v["actions"]])),
                             M.load_d(k).predict(M.xvec(v), np.array([M.adesc(a) for a in v["actions"]])), atol=1e-9) for k in old_d for v in val[:10])
    packaged = {f: (ev / f).read_bytes() for f in ("LEARN_W.json", "LEARN_D.json")}
    packaged |= {f"models/{q.name}": q.read_bytes() for q in (ev / "models").glob("*")}
    run("scripts/bf2w_models.py", "train_w", "--seeds", "1")
    new_w1 = M.load_w(1)
    w_same = bool(np.allclose(M.w_predict_costs(*keep_w1, val), M.w_predict_costs(*new_w1, val), rtol=1e-5, atol=1e-3))
    out["4_refits_executed"] = {"D_4_configs_predictions_identical": bool(d_same), "D_selection_identical": new_d["selected"] == keep_d["selected"],
                                "W_seed1_retrained_predictions_identical": w_same, "ok": bool(d_same and new_d["selected"] == keep_d["selected"] and w_same)}
    for f, b_ in packaged.items():  # restore the packaged learning outputs (refits are compared, not substituted)
        (ev / f).write_bytes(b_)
    for p in procs:
        p.wait()
    # (5) analysis reproduction (with regenerated files in place)
    keep = {k: json.loads((ev / k).read_text()) for k in ("DECOMPOSITION_F_R1.json", "RESULTS_PILOT_W.json")}
    run("scripts/bf2w_decompose.py")
    run("scripts/bf2w_analyse.py")
    rr = json.loads((ev / "RESULTS_PILOT_W.json").read_text())
    kr = keep["RESULTS_PILOT_W.json"]
    for d_ in (rr, kr):  # run-time measurements excluded (documented rule): response times and training durations
        d_.get("costs", {}).pop("response_seconds_per_decision", None)
        d_.get("costs", {}).pop("W_training_seconds_per_seed", None)
    same = {"DECOMPOSITION_F_R1.json": bool(close(keep["DECOMPOSITION_F_R1.json"], json.loads((ev / "DECOMPOSITION_F_R1.json").read_text()))),
            "RESULTS_PILOT_W.json": bool(close(kr, rr))}
    out["5_analysis_reproduction"] = {"identical": same, "note": "run-time measurements excluded: costs.response_seconds_per_decision, costs.W_training_seconds_per_seed", "ok": all(same.values())}
    regen = {f"eval/{ef.name}": bool(ef.exists() and close(strip(eref), strip(json.loads(ef.read_text())))),
             f"train/{tf_.name}": bool(tf_.exists() and close(strip(tref), strip(json.loads(tf_.read_text())))),
             f"train/{tf_.with_suffix('.npz').name}": bool(tf_.with_suffix(".npz").exists() and tf_.with_suffix(".npz").read_bytes() == tnpz)}
    out["6_regenerations_executed"] = {"items": regen, "params": {"eval": {"E": eref["E"], "Md": eref["Md"]}, "train": {"K": len(tref["futures"])}},
                                       "ok": all(regen.values())}
    out["7_not_reproduced"] = ["the other 47 evaluation decisions and 199 TRAIN origins (packaged, hash-checked, used by the reproduced analysis)",
                               "W seeds 0 and 2 retraining", "DEV numerical check (packaged output only)", "B-FRAG 2 runs (see the B-FRAG 2 receipt)"]
    out["seconds"] = round(time.time() - t0, 1)
    out["ok"] = all(out[k]["ok"] for k in ("1_integrity", "3_reload_and_reproduce_predictions", "4_refits_executed", "5_analysis_reproduction",
                                           "6_regenerations_executed")) and out["2_tests"]["exit"] == 0
    shutil.rmtree(fresh)
    rec = ROOT / "evidence/howm2_bfrag2w_receipt"
    rec.mkdir(exist_ok=True)
    (rec / "RESTORE_RECEIPT_BW.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
