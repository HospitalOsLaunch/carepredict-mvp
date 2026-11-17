#!/usr/bin/env python3
"""B-FRAG 2 independent restoration receipt, in a fresh directory. Separate sections:
(1) integrity; (2) tests; (3) reload of learned references (hashes) and refit from TRAIN (predictions);
(4) reproduction of VAL selections and CONF analysis from packaged files; (5) regenerations actually
executed (1 CONF-S full episode, 1 VAL-S val episode, 1 CONF features episode, 1 paired-control structure;
compared without timings); (6) elements NOT reproduced."""

import hashlib
import json
import pickle
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


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def strip(d):
    d = dict(d)
    d.pop("timing_s", None)
    d.pop("maxrss_mb", None)
    return d


def main() -> int:
    z, py = Path(sys.argv[1]), sys.argv[2]
    t0 = time.time()
    fresh = Path(tempfile.mkdtemp(prefix="restoreBF2_", dir=z.parent))
    out = {"package": z.name, "package_sha256": sha(z)}
    with zipfile.ZipFile(z) as zf:
        zf.extractall(fresh)
    bad = [rel for h, rel in (ln.split("  ", 1) for ln in (fresh / "SHA256SUMS").read_text().splitlines()) if sha(fresh / rel) != h]
    out["1_integrity"] = {"files": len((fresh / "SHA256SUMS").read_text().splitlines()), "bad": bad, "ok": not bad}
    tree = fresh / "tree"
    tree.mkdir()
    with tarfile.open(fresh / "source_tree.tar.gz") as tf:
        tf.extractall(tree, filter="data")
    shutil.rmtree(tree / "evidence/howm2_bfrag2", ignore_errors=True)
    shutil.copytree(fresh / "evidence_howm2_bfrag2", tree / "evidence/howm2_bfrag2")
    ev = tree / "evidence/howm2_bfrag2"

    def run(*a):
        return subprocess.run([py, *a], cwd=tree, capture_output=True, text=True)

    def start(*a):
        return subprocess.Popen([py, *a], cwd=tree, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # (5) regenerations in parallel with the rest
    regen_items = [("S", "BF2_CONF", 5, 1, "full"), ("S", "BF2_VAL", 7, 2, "val"), ("F", "BF2_CONF", 150, 0, "features")]
    refs, procs = {}, []
    for tag, part, s, e, mode in regen_items:
        f = ev / "runs" / tag / part / f"s{s:03d}_e{e}.json"
        refs[(tag, part, s, e)] = strip(json.loads(f.read_text()))
        f.unlink()
        procs.append(start("scripts/bfrag2.py", "run", "--part", part, "--tag", tag, "--mode", mode, "--s0", str(s), "--s1", str(s + 1),
                           "--Mr", "32", "--Md", "32", "--E", "8", "--par", "1", "--budget", "1000"))
    pf = ev / "runs/PAIRED/BF2_CONF/s011.json"
    pref = json.loads(pf.read_text())
    pf.unlink()
    procs.append(start("scripts/bfrag2_paired.py", "--s0", "11", "--s1", "12", "--par", "1"))
    r = run("-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/bfrag2", "tests/bfrag")
    out["2_tests"] = {"exit": r.returncode, "tail": r.stdout.strip().splitlines()[-1:]}
    # (3) learned references
    learn = json.loads((ev / "LEARN.json").read_text())
    reload_ok = {k: sha(ev / "models" / f"{v['view']}_{v['config']}.pkl") == v["sha256"] for k, v in learn["table"].items()}
    old_models = {k: pickle.loads((ev / "models" / f"{v['view']}_{v['config']}.pkl").read_bytes()) for k, v in learn["table"].items()}
    keep_learn = learn
    run("scripts/bfrag2_learn.py")
    new_learn = json.loads((ev / "LEARN.json").read_text())
    for d in (keep_learn, new_learn):
        for v in d["table"].values():
            v.pop("fit_seconds", None)
            v.pop("sha256", None)
            v.pop("bytes", None)
    import numpy as np  # noqa: E402

    sys.path.insert(0, str(tree / "scripts"))
    import bfrag2_lib as L  # noqa: E402

    L.RUNS = ev / "runs"
    va = L.rows(L.load("F", "BF2_VAL"), learn["feature_names"])
    pred_same = {}
    for k, v in learn["table"].items():
        m_new = pickle.loads((ev / "models" / f"{v['view']}_{v['config']}.pkl").read_bytes())
        pred_same[k] = bool(np.allclose(old_models[k].predict_proba(va["X"][v["view"]]), m_new.predict_proba(va["X"][v["view"]]), atol=1e-12))
    out["3_learned_references"] = {"reload_hash_ok": all(reload_ok.values()), "refit_predictions_identical": all(pred_same.values()),
                                   "learn_json_identical": bool(close(keep_learn, new_learn)), "models": len(reload_ok)}
    out["3_learned_references"]["ok"] = all(out["3_learned_references"][k] for k in ("reload_hash_ok", "refit_predictions_identical", "learn_json_identical"))
    for p in procs:
        p.wait()
    # (4) analysis reproduction (after the regenerations so that regenerated files are used)
    keep = {k: json.loads((ev / k).read_text()) for k in ("SELECTION_VAL.json", "RESULTS_BFRAG2_CONF.json")}
    run("scripts/bfrag2_val.py")
    run("scripts/bfrag2_analyse.py")
    same = {k: bool(close(v, json.loads((ev / k).read_text()))) for k, v in keep.items()}
    out["4_analysis_reproduction"] = {"identical": same, "ok": all(same.values())}
    regen = {}
    for (tag, part, s, e), ref in refs.items():
        f = ev / "runs" / tag / part / f"s{s:03d}_e{e}.json"
        regen[f"{tag}/{part}/s{s:03d}_e{e}"] = bool(f.exists() and close(ref, strip(json.loads(f.read_text()))))
    regen["PAIRED/BF2_CONF/s011"] = bool(pf.exists() and close(pref, json.loads(pf.read_text())))
    out["5_regenerations_executed"] = {"items": regen, "ok": all(regen.values())}
    out["6_not_reproduced"] = ["the other CONF/VAL/TRAIN episode files (packaged, hash-checked, used by the reproduced analyses)",
                               "DEV cost checks and Monte-Carlo stability study (packaged outputs only)"]
    out["seconds"] = round(time.time() - t0, 1)
    out["ok"] = (out["1_integrity"]["ok"] and out["2_tests"]["exit"] == 0 and out["3_learned_references"]["ok"]
                 and out["4_analysis_reproduction"]["ok"] and out["5_regenerations_executed"]["ok"])
    shutil.rmtree(fresh)
    rec = ROOT / "evidence/howm2_bfrag2_receipt"
    rec.mkdir(exist_ok=True)
    (rec / "RESTORE_RECEIPT_BFRAG2.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
