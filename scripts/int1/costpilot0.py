"""INT-1 smoke + first cost probe of the derived engine (2/4/8/12 units)."""
import json, resource, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from hospitalos.howmint import world as W, loop as L, actions as A  # noqa: E402


def hist(**kw):
    cat, adm = kw["cat"], kw["adm"]
    return cat[1] if adm[1] else cat[0]


out = {}
for n in (2, 4, 8, 12):
    sp = W.structure("INT_PILOT", 0, n)
    e = W.episode(sp, 0)
    t = time.time(); pre = L.prefix(e, 48); tp = time.time() - t
    hz, nd, iv = (168, 7, 24) if n == 2 else (24, 4, 6)
    t = time.time(); res = L.closed_loop(e, pre, 1, hist, nd, iv, hz); tc = time.time() - t
    t = time.time(); ps, peng = L.public_view(pre, L.W.Recorder(e, 1), pre["t0"]); tv = time.time() - t
    cat = A.catalogue(peng, e.units); adm = [A.admissible(peng, a, n, pre["t0"]) for a in cat]
    seqs = L.sequences(cat, adm)
    t = time.time(); br = L.branch(pre, e, pre["eng"], seqs[2], 1, 48 if n == 2 else 24, iv, pre["anchor"]); tb = time.time() - t
    out[n] = {"family": e.family, "beds": sum(e.beds.values()), "c_cl": e.c_cl, "c_tr": e.c_tr, "aval_slots": e.aval_slots_per_day,
              "prefix_s": round(tp, 2), "closed_loop_s": round(tc, 2), "public_view_s": round(tv, 3), "branch_s": round(tb, 3),
              "n_actions": len(cat), "n_admissible": sum(adm), "n_sequences": len(seqs),
              "wait": res["wait_patient_min"], "rupture_min": res["rupture_minutes"], "choices": res["choices"],
              "aval_blocked_end": res["aval_blocked_end"], "transfer_pending_end": res["transfer_pending_end"], "rejections": res["rejections"],
              "branch_states_shape": list(br["states"].shape)}
    print(n, json.dumps(out[n]), flush=True)
out["maxrss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
Path(ROOT / "evidence/howm_int1/COSTPILOT0.json").write_text(json.dumps(out, indent=1))
