#!/usr/bin/env python3
"""HOWM-2 C1 palier 1 restoration receipt, in a fresh directory. Four separate sections:
(1) file integrity (SHA256SUMS); (2) checkpoint loading (every best.pt of F-C1: hash, load, forward
pass on CVAL data regenerated for one establishment); (3) analysis reproduction (RESULTS_C1_P1.json
recomputed from the packaged per-establishment scores); (4) regenerations actually performed (final
scores of 2 CEVAL establishments, and one training-data record compared with the manifest ekeys).
Training is NOT re-run and is not claimed to be reproduced."""

from __future__ import annotations

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
from howm2_a2_restore import close  # noqa: E402


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


CHECK = r'''
import sys, json, hashlib, torch
sys.path.insert(0, "src")
from hospitalos.howm2 import c1
from hospitalos.howm.nets import forward_losses
f1 = json.load(open("evidence/howm2_c1/F_C1.json"))
c1.register()
rec = c1.make_record("HOWM2_CVAL", 0, c1.b0())
out = {}
for k, h in f1["weights"].items():
    s, N, seed = k.split(":")
    p = c1.run_dir(s, int(N), int(seed)) / "best.pt"
    ok_hash = hashlib.sha256(p.read_bytes()).hexdigest() == h["best.pt"]
    m = c1.new_model(s, c1.b0(), int(seed))
    m.load_state_dict(torch.load(p, weights_only=True)["model"])
    m.eval()
    with torch.no_grad():
        parts = forward_losses(m, c1.make_batch(s, [(rec, 48), (rec, 120)]))
    out[k] = {"hash_ok": ok_hash, "loaded": True, "forward_finite": all(torch.isfinite(v[0]).item() for v in parts.values())}
print(json.dumps(out))
'''


def main() -> int:
    z, py = Path(sys.argv[1]), sys.argv[2]
    t0 = time.time()
    fresh = Path(tempfile.mkdtemp(prefix="restoreC1_", dir=z.parent))
    out: dict = {"package": z.name, "package_sha256": sha(z), "training_reproduced": False,
                 "note": "training is not re-run; sections below state exactly what was checked"}
    with zipfile.ZipFile(z) as zf:
        zf.extractall(fresh)
    bad = [rel for h, rel in (ln.split("  ", 1) for ln in (fresh / "SHA256SUMS").read_text().splitlines()) if sha(fresh / rel) != h]
    out["1_file_integrity"] = {"files_checked": len((fresh / "SHA256SUMS").read_text().splitlines()), "bad": bad, "ok": not bad}
    tree = fresh / "tree"
    tree.mkdir()
    with tarfile.open(fresh / "source_tree.tar.gz") as tf:
        tf.extractall(tree, filter="data")
    shutil.copytree(fresh / "evidence_howm2_c1", tree / "evidence/howm2_c1", dirs_exist_ok=True)
    for f in (fresh / "evidence_howm2").iterdir():
        shutil.copy(f, tree / "evidence/howm2" / f.name)
    run = lambda *a: subprocess.run([py, *a], cwd=tree, capture_output=True, text=True)  # noqa: E731
    r = run("-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/howm2/test_howm2_c1.py")
    out["tests_c1"] = {"exit": r.returncode, "tail": r.stdout.strip().splitlines()[-1:]}
    r = run("-c", CHECK)
    ck = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else {"error": r.stderr[-2000:]}
    out["2_checkpoint_loading"] = {"checkpoints": ck, "ok": r.returncode == 0 and all(all(v.values()) for v in ck.values())}
    ev = tree / "evidence/howm2_c1"
    keep = json.loads((ev / "RESULTS_C1_P1.json").read_text())
    r = run("scripts/howm2_c1_final.py", "analyse")
    same = close(keep, json.loads((ev / "RESULTS_C1_P1.json").read_text()))
    out["3_analysis_reproduction"] = {"exit": r.returncode, "RESULTS_C1_P1_identical": bool(same), "ok": bool(same)}
    regen = {}
    for i in (0, 1):
        f = ev / "final/HOWM2_CEVAL" / f"{i:03d}.json"
        ref = json.loads(f.read_text())
        f.unlink()
        r = run("scripts/howm2_c1_final.py", "run", "--part", "HOWM2_CEVAL", "--start", str(i), "--stop", str(i + 1))
        new = json.loads(f.read_text()) if f.exists() else None
        regen[f"final/HOWM2_CEVAL/{i:03d}"] = bool(new is not None and close(ref["acc"], new["acc"]))
    r = run("-c", "import sys,json,hashlib;sys.path.insert(0,'src');from hospitalos.howm2 import c1;c1.register();"
                  "r=c1.make_record('HOWM2_CTRAIN',0,c1.b0());m=json.load(open('evidence/howm2_c1/DATA_MANIFEST.json'));"
                  "print(json.dumps({'ekey_first_matches_manifest_range': m['shards']['HOWM2_CTRAIN/000']['indices'][0]==0,'ekey':r['ekey']}))")
    regen["training_record_CTRAIN_0_regenerable"] = r.returncode == 0
    out["4_regenerations_performed"] = {"items": regen, "ok": all(regen.values()),
                                        "not_regenerated": ["training runs", "all other final-score files (packaged, hash-checked)"]}
    out["seconds"] = round(time.time() - t0, 1)
    out["ok"] = all(out[k]["ok"] for k in ("1_file_integrity", "2_checkpoint_loading", "3_analysis_reproduction", "4_regenerations_performed")) and out["tests_c1"]["exit"] == 0
    shutil.rmtree(fresh)
    (ROOT / "evidence/howm2_c1/RESTORE_RECEIPT_C1_P1.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1)[:4000])
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
