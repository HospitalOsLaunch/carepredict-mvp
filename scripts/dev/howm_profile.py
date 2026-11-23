import cProfile, pstats, time
from hospitalos.howm import corpus as C, predict as P, rollout as R
from hospitalos.howm.b0 import fit_pool
from hospitalos.howm.history import PublicStream
d = C.load("VAL", 0); ep, est = d["episode"], d["data"]
p = fit_pool([C.load("TRAIN", i)["episode"] for i in range(4)])
H = 100; od = est.origins[H]
ps = PublicStream(ep.observations); ps.advance(H * 60); eng = ps.to_engine(H * 60)
pr = P.b0_predict(p, od, est, True)
freq = R.NewProfileFreq(0.15, (0.4, 0.4, 0.2), 0.6)
provs = [R.ModelProvider(pr, od, 4 * H, m, R.rollout_key("VAL", 0, H), freq) for m in range(16)]
t0 = time.time(); [R.rollout(eng, pv, None) for pv in provs]; print("16 rollouts", round(time.time() - t0, 3))
pf = cProfile.Profile(); pf.enable(); [R.rollout(eng, pv, None) for pv in provs]; pf.disable()
pstats.Stats(pf).sort_stats("cumulative").print_stats(22)
