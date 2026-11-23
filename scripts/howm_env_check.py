"""R0.ENV check: torch version, CPU op, threads, and the checkpoint contract under weights_only=True
(RNG states of torch/numpy/python converted to tensors/plain types; optimizer + scheduler)."""

import hashlib
import io
import json
import random
import sys

import numpy as np
import torch

assert torch.__version__.split("+")[0] == "2.15.0", torch.__version__
torch.set_num_threads(4)
a = torch.randn(64, 64)
assert torch.allclose(a @ torch.eye(64), a)
sys.path.insert(0, "src")
from hospitalos.howm.ckpt import pack_rng, unpack_rng  # noqa: E402

model = torch.nn.GRU(8, 16)
opt = torch.optim.Adam(model.parameters(), lr=1e-3)
sch = torch.optim.lr_scheduler.StepLR(opt, 10)
model(torch.randn(5, 2, 8))[0].sum().backward()
opt.step()
sch.step()
random.seed(3)
np.random.seed(4)
torch.manual_seed(5)
state = {
    "model": model.state_dict(),
    "opt": opt.state_dict(),
    "sch": sch.state_dict(),
    "rng": pack_rng(),
    "pos": {"epoch": 1, "batch": 7},
}
buf = io.BytesIO()
torch.save(state, buf)
raw = buf.getvalue()
expect = (random.random(), float(np.random.rand()), float(torch.rand(1)))
loaded = torch.load(io.BytesIO(raw), weights_only=True)
unpack_rng(loaded["rng"])
got = (random.random(), float(np.random.rand()), float(torch.rand(1)))
assert got == expect, (got, expect)
print(
    json.dumps(
        {
            "torch": torch.__version__,
            "threads": torch.get_num_threads(),
            "numpy": np.__version__,
            "ckpt_weights_only_roundtrip": True,
            "ckpt_sha256": hashlib.sha256(raw).hexdigest()[:16],
        }
    )
)
