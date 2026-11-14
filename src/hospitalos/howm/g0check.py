"""Post-G0 integrity: the generator / information-boundary files committed in G0 must be
byte-identical; model and evaluation modules may only change before F1 (frozen there)."""

from __future__ import annotations

import json

from .corpus import EVID, code_hashes

G0_FROZEN = (
    "src/hospitalos/howm/keys.py",
    "src/hospitalos/howm/world.py",
    "src/hospitalos/howm/generator.py",
    "src/hospitalos/howm/history.py",
    "src/hospitalos/howm/dataset.py",
    "src/hospitalos/howm/corpus.py",
    "src/hospitalos/howm/galt.py",
    "src/hospitalos/howm/verify.py",
    "scripts/howm_r0.py",
)


class G0Violation(RuntimeError):
    pass


def check() -> dict[str, str]:
    g0 = json.loads((EVID / "COMMITMENT_G0.json").read_text())["code"]
    now = code_hashes()
    bad = [f for f in G0_FROZEN if g0.get(f) != now.get(f)]
    if bad:
        raise G0Violation(f"G0-frozen files changed: {bad}")
    return {f: now[f] for f in G0_FROZEN}
