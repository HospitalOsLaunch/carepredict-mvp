"""Pack INT_TRAIN structures 0-9999 (tier 2) of one size into memory-mappable arrays:  pack.py N"""
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts/int1"))
import corpus as CO  # noqa: E402
from hospitalos.howmint import data as DA  # noqa: E402
S = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad")
n = int(sys.argv[1])
t = time.time()
s_list = [s for s in range(10000) if CO.size_of("INT_TRAIN", s) == n]
print(json.dumps(DA.pack(S / "int1_corpus", "INT_TRAIN", s_list, S / "int1_pack_t2", n_only=n)), len(s_list), round(time.time() - t, 1))
