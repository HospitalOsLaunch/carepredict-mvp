"""HOWM-2 A step 1: re-check every fact of programme section 2 against the delivered files."""
import json, re
from pathlib import Path
E = Path("evidence/howm1")
out = {}
ls = json.loads((E / "LOSS_SCALES.json").read_text())
claimed = {"care": 1608714, "arrivals": 73728, "auth": 34810, "ready": 1534, "confirmation": 832, "cleaning": 217, "transport": 195}
out["F1_training_item_counts"] = {"file": str(E / "LOSS_SCALES.json"), "found": ls["counts"], "claimed": claimed,
                                  "match": ls["counts"] == claimed, "train_establishments": ls.get("train_establishments")}
r = json.loads((E / "RESULTS_R1_DEVTEST.json").read_text())
fam = r["LS_by_family_h24"]
d_pool = {f: round(fam["B0-local"][f] - fam["B0-pool"][f], 3) for f in ("ready", "transport", "cleaning")}
d_h1 = {f: round(fam["B0-local"][f] - fam["H1"][f], 3) for f in ("ready", "transport", "cleaning")}
out["F2_family_advantage_h24"] = {"B0-local_minus_B0-pool": d_pool, "B0-local_minus_H1": d_h1,
                                  "claimed": {"ready": -0.057, "transport": -0.084, "cleaning": -0.051},
                                  "note": "claimed figures are B0-local minus B0-pool"}
runs = {}
for st in sorted((E / "train").glob("*/state.json")):
    m = json.loads(st.read_text()); L = m["log"]
    v = [e["val_total"] for e in L]
    runs[st.parent.name] = {"first": round(v[0], 4), "best": round(min(v), 4), "gain_vs_first": round(v[0] - min(v), 4),
                            "max_after_best": round(max(v[v.index(min(v)):]), 4), "epochs": len(v)}
out["F3_val_curves"] = {"runs": runs, "claimed": "best gain 0.004-0.009 on 7.215; VAL loss rises after (up to 7.45 for B2 at 1e-3)"}
src = Path("src/hospitalos/howm/train.py").read_text()
out["F4_train_loss_logged"] = {"meta_log_fields": re.findall(r'meta\["log"\]\.append\(\s*\{([^}]*)\}', src, re.S)[:1],
                               "train_loss_in_log": "train_total" in src or "train_loss" in src}
d8 = json.loads((E / "DIAG_T_INF_08.json").read_text())
r1 = Path("scripts/howm_r1.py").read_text()
m = re.search(r"def cmd_permuted.*?tr = load_part\(\"TRAIN\", (\d+)\).*?va = load_part\(\"VAL\", (\d+)\).*?max_steps=(\d+)", r1, re.S)
out["F5_T_INF_08"] = {"improvement": d8["improvement"], "train_establishments_used": int(m.group(1)), "val_establishments_used": int(m.group(2)),
                      "steps": int(m.group(3)), "loss_scales_at_that_time": "TRAIN 0-31 (ledger #52-#53 precede #54)",
                      "claimed": "0.0088 in 60 steps; scales differ (48 vs 32 establishments)"}
p = json.loads((E / "PILOT.json").read_text())
out["F6_train_establishments"] = {"pilot_state": p["state"]}
out["F7_confirmation_h24"] = {k: round(fam[k]["confirmation"], 3) for k in fam}
dm = r["decision_means"]; g = r["gain_vs_habitual"]
out["F8_decision"] = {"gain_C_full": round(g["C_full"], 1), "gain_rule": round(g["strengthened_rule"], 1),
                      "gain_oracle": round(dm["habitual"] - dm["oracle"], 1)}
print(json.dumps(out, indent=1))
Path("evidence/howm2/FACTS_CHECK.json").write_text(json.dumps(out, indent=1) + "\n")
