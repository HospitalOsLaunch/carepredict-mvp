"""PLAN48 amendment A1: projection draws are specific to each hospital."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sim import W, public_forecast  # noqa: E402


def _public(idx):
    sp = W.n_unit_structure("PLAN48_TEST_A1", idx, 4)
    eng = W.initial_engine(sp, W.ProvN(sp, 0))
    ps = W.PublicStreamN(W.static_obs(eng, sp))
    ps.advance(89)
    return sp, ps.to_engine_n(6)


def test_projection_key_depends_on_the_hospital():
    keys = set()
    for idx in (0, 1):
        sp, pe = _public(idx)
        state, prov = public_forecast(sp, pe, 10001)
        keys.add(prov.spec.ekey)
    assert len(keys) == 2
