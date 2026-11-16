import os
os.environ["OMP_NUM_THREADS"] = "1"; os.environ["OPENBLAS_NUM_THREADS"] = "1"; os.environ["MKL_NUM_THREADS"] = "1"
import cProfile, pstats, json, time
from hospitalos.howm.b0 import B0Params
from hospitalos.howm2 import space
from hospitalos.howm2.ladder import run_establishment
space.register()
p = B0Params.from_json(json.load(open("evidence/howm1/B0_PARAMS.json")))
pf = cProfile.Profile(); pf.enable(); r = run_establishment("HOWM2_REF", 3, p); pf.disable()
print("sec", r["seconds"], r["timing"], r["mech"])
pstats.Stats(pf).sort_stats("tottime").print_stats(18)
