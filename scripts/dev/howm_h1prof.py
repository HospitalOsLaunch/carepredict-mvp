"""Dev profile of one H1 training step on TRAIN batches."""
import json, time, torch
from torch.profiler import profile, ProfilerActivity
from hospitalos.howm import corpus as C
from hospitalos.howm.b0 import B0Params
from hospitalos.howm.nets import H1, make_batch, forward_losses, total_loss
torch.set_num_threads(4)
p = B0Params.from_json(json.load(open("evidence/howm1/B0_PARAMS.json")))
sc = json.load(open("evidence/howm1/LOSS_SCALES.json"))["s_f"]
tr = [C.load("TRAIN", i) for i in range(4)]
pairs = [(d["data"], H) for d in tr for H in sorted(d["data"].origins)]
torch.manual_seed(0); m = H1(p); opt = torch.optim.Adam(m.parameters(), 1e-3)
b = make_batch(pairs[:32], "H1")
print("nodes", b["graph"]["n"], "edges/h", sum(int(e[0].numel()) for e in b["graph"]["edges"]) / 24)
for _ in range(2):
    parts = forward_losses(m, b); parts.pop("presence", None); loss = total_loss(parts, sc); opt.zero_grad(); loss.backward(); opt.step()
t0 = time.time(); enc = m.encode(b); t1 = time.time()
parts = forward_losses(m, b); parts.pop("presence", None); loss = total_loss(parts, sc); t2 = time.time()
opt.zero_grad(); loss.backward(); t3 = time.time()
print(json.dumps({"encode_s": t1 - t0, "forward_all_s": t2 - t1, "backward_s": t3 - t2}))
with profile(activities=[ProfilerActivity.CPU]) as prof:
    parts = forward_losses(m, b); parts.pop("presence", None); loss = total_loss(parts, sc); opt.zero_grad(); loss.backward()
print(prof.key_averages().table(sort_by="self_cpu_time_total", row_limit=14))
