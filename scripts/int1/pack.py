"""Pack INT_TRAIN structures 0-9999 (tier 2) into memory-mappable arrays."""
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from hospitalos.howmint import data as DA  # noqa: E402
S = Path("/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad")
t = time.time()
print(json.dumps(DA.pack(S / "int1_corpus", "INT_TRAIN", list(range(10000)), S / "int1_pack_t2")), round(time.time() - t, 1))
