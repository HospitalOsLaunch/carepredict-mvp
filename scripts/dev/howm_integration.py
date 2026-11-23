"""Development integration smoke (TRAIN/VAL only; no DEVTEST/DIAG/RESERVE)."""
import time, json
import numpy as np, torch
from hospitalos.howm.generator import establishment, generate, EVAL_DAY
from hospitalos.howm.dataset import build
from hospitalos.howm import b0 as B0, nets, predict as P, rollout as R, controllers as C
from hospitalos.howm.history import PublicStream
from hospitalos.howm.verify import check, events_from_observations
T = {}
t0 = time.time()
eps = [generate(establishment("TRAIN", i)) for i in range(3)]
T["gen3"] = time.time() - t0
for ep in eps:
    v = check(ep.truth_log, ep.static, ep.capacity)
    print("verify", ep.spec.index, len(v), v[:3])
t0 = time.time(); p = B0.fit_pool(eps); T["b0fit"] = time.time() - t0
print("b0 arr r", round(p.arr_r, 2), "care sigma", p.care_sigma.round(3), "pres", round(p.presence_p, 3))
ep_v = generate(establishment("VAL", 0), keep_instants=True)
t0 = time.time(); est = build(ep_v, list(range(24, 144))); T["build_val"] = time.time() - t0
od = est.origins[100]
print("items", {f: len(v) for f, v in od.items.items()}, "care stays", len(od.care_ref))
for local in (False, True):
    pr = P.b0_predict(p, od, est, local)
    sc = P.member_logscores(pr, od, 24)
    print("B0 local" if local else "B0 pool", {f: (round(float(-v.mean()), 3) if len(v) else None) for f, v in sc.items()})
torch.manual_seed(0)
for kind in ("B2", "H1"):
    m = nets.B2(p) if kind == "B2" else nets.H1(p)
    t0 = time.time()
    batch = nets.make_batch([(est, H) for H in range(30, 62)], kind)
    T[f"{kind}_batch"] = time.time() - t0
    t0 = time.time(); parts = nets.forward_losses(m, batch); T[f"{kind}_fwd"] = time.time() - t0
    t0 = time.time(); sum(v[0] for v in parts.values()).backward(); T[f"{kind}_bwd"] = time.time() - t0
    print(kind, nets.n_params(m)["total"], {f: round(float(v[0]) / max(v[1], 1), 3) for f, v in parts.items()})
    pr = nets.predict(m, est, 100)
    sc = P.member_logscores(pr, od, 24)
    print(kind, "pred", {f: (round(float(-v.mean()), 3) if len(v) else None) for f, v in sc.items()})
# rollouts from the public engine at origin 100
ps = PublicStream(ep_v.observations); ps.advance(100 * 60)
eng = ps.to_engine(100 * 60)
freq = R.NewProfileFreq(0.15, (0.4, 0.4, 0.2), 0.6)
pr = P.b0_predict(p, od, est, True)
t0 = time.time()
res = [R.rollout(eng, R.ModelProvider(pr, od, 400, m, R.rollout_key("VAL", 0, 100), freq), None) for m in range(16)]
T["16_rollouts_b0"] = time.time() - t0
y = np.array(R.truth_vector(ep_v, 100, 6))
S = np.array([R.target_vector(r, 6) for r in res])
print("crps h6", R.crps_samples(S, y).round(2), "U mean", round(float(np.mean([r["U"] for r in res])), 1), "rej", sum(r["rejected"] for r in res))
tau = EVAL_DAY * 96 + 11 * 4
ps2 = PublicStream(ep_v.observations); ps2.advance(tau * 15); peng = ps2.to_engine(tau * 15)
t0 = time.time()
out = C.evaluate_instant(ep_v, tau, peng, {}, controllers=("C_full", "C_param", "C_pub_snap"))
T["instant_truth_controllers"] = time.time() - t0
print("instant", {k: round(v, 1) for k, v in out["value"].items()}, "oracle", round(out["oracle_U_star"], 1), out["choices"])
print(json.dumps({k: round(v, 3) for k, v in T.items()}))
