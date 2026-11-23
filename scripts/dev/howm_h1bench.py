"""Dev benchmark: H1 train step time and equality of the optimised forward (VAL only)."""
import sys, time, json, torch
sys.path.insert(0, "scripts")
from hospitalos.howm import corpus as C
from hospitalos.howm.b0 import B0Params
from hospitalos.howm.nets import H1, make_batch, forward_losses, total_loss
p = B0Params.from_json(json.load(open("evidence/howm1/B0_PARAMS.json")))
sc = json.load(open("evidence/howm1/LOSS_SCALES.json"))["s_f"]
va = [C.load("VAL", i) for i in range(3)]
pairs = [(d["data"], H) for d in va for H in sorted(d["data"].origins)]
for th in (4, 2, 1):
    torch.set_num_threads(th); torch.manual_seed(0); m = H1(p); opt = torch.optim.Adam(m.parameters(), 1e-3)
    ts = []; tb = []
    for i in range(6):
        t0 = time.time(); b = make_batch(pairs[i*32:(i+1)*32], "H1"); tb.append(time.time() - t0)
        parts = forward_losses(m, b); parts.pop("presence", None)
        loss = total_loss(parts, sc); opt.zero_grad(); loss.backward(); opt.step(); ts.append(time.time() - t0)
    print(json.dumps({"threads": th, "step_s": sorted(ts)[3], "batch_build_s": sorted(tb)[3], "loss": float(loss)}))
