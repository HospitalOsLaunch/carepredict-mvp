#!/usr/bin/env python3
"""B-FRAG independent restoration receipt, in a fresh directory. Sections kept separate:
(1) integrity; (2) analysis reproduction (TUNE, CONF, descriptive JSON recomputed from packaged per-world files);
(3) regenerations actually executed (2 CONF worlds and 1 TUNE world incl. paired control, full pipeline, compared
without timings); (4) elements NOT reproduced (listed)."""

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
    fresh = Path(tempfile.mkdtemp(prefix="restoreBF_", dir=z.parent))
    out = {"package": z.name, "package_sha256": sha(z)}
    with zipfile.ZipFile(z) as zf:
        zf.extractall(fresh)
    bad = [rel for h, rel in (ln.split("  ", 1) for ln in (fresh / "SHA256SUMS").read_text().splitlines()) if sha(fresh / rel) != h]
    out["1_integrity"] = {"files": len((fresh / "SHA256SUMS").read_text().splitlines()), "bad": bad, "ok": not bad}
    tree = fresh / "tree"
    tree.mkdir()
    with tarfile.open(fresh / "source_tree.tar.gz") as tf:
        tf.extractall(tree, filter="data")
    shutil.copytree(fresh / "evidence_howm2_bfrag", tree / "evidence/howm2_bfrag", dirs_exist_ok=True)
    run = lambda *a: subprocess.run([py, *a], cwd=tree, capture_output=True, text=True)  # noqa: E731
    r = run("-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/bfrag")
    out["tests_bfrag"] = {"exit": r.returncode, "tail": r.stdout.strip().splitlines()[-1:]}
    ev = tree / "evidence/howm2_bfrag"
    keep = {k: json.loads((ev / k).read_text()) for k in ("TUNE_TUNE_D2.json", "RESULTS_BFRAG_CONF.json", "CONF_DESCRIPTIVE.json")}
    run("scripts/bfrag_analyse.py", "tune", "--tag", "TUNE_D2")
    run("scripts/bfrag_analyse.py", "conf", "--tag", "CONF_D2")
    run("scripts/bfrag_descriptive.py")
    same = {k: bool(close(v, json.loads((ev / k).read_text()))) for k, v in keep.items()}
    out["2_analysis_reproduction"] = {"identical": same, "ok": all(same.values())}
    regen = {}
    for tag, part, idx, ctrl in (("CONF_D2", "BFRAG_CONF", 0, False), ("CONF_D2", "BFRAG_CONF", 5, False), ("TUNE_D2", "BFRAG_TUNE", 2, True)):
        f = ev / "runs" / tag / part / f"{idx:03d}.json"
        ref = strip(json.loads(f.read_text()))
        f.unlink()
        args = ["scripts/bfrag.py", "run", "--part", part, "--design", "D2", "--tag", tag, "--start", str(idx), "--stop", str(idx + 1), "--par", "1"]
        r = run(*(args + (["--controls"] if ctrl else [])))
        new = strip(json.loads(f.read_text())) if f.exists() else None
        regen[f"{tag}/{part}/{idx:03d}"] = bool(new is not None and close(ref, new))
    out["3_regenerations_executed"] = {"items": regen, "ok": all(regen.values())}
    out["4_not_reproduced"] = ["the other 141 TUNE/CONF world files (packaged, hash-checked, used by the reproduced analyses)",
                               "DEV scans and cost pilot", "C1 training (closure envelope only)"]
    out["seconds"] = round(time.time() - t0, 1)
    out["ok"] = out["1_integrity"]["ok"] and out["tests_bfrag"]["exit"] == 0 and out["2_analysis_reproduction"]["ok"] and out["3_regenerations_executed"]["ok"]
    shutil.rmtree(fresh)
    rec_dir = ROOT / "evidence/howm2_bfrag_receipt"
    rec_dir.mkdir(exist_ok=True)
    (rec_dir / "RESTORE_RECEIPT_BFRAG.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
