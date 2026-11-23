"""Test isolation for the frozen B-FRAG code (test_bfrag.py itself is frozen and is not modified).

hospitalos.bfrag.core.f_pairs replaces hospitalos.howm2.nowcast.pending_arrivals by the B-FRAG arrival law
for the rest of the process (documented in the frozen source). In a full test session this leaked into the
HOWM-2 A' tests run afterwards (KeyError on the B-FRAG nominal-capacity table). The original attribute is
restored after every test of this directory."""
from collections.abc import Iterator

import pytest

from hospitalos.howm2 import nowcast as N


@pytest.fixture(autouse=True)
def _restore_nowcast_pending_arrivals() -> Iterator[None]:
    original = N.pending_arrivals
    yield
    N.pending_arrivals = original
