"""Literal plan IDs measured on 486b0cb, before the unit planning changes."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "web" / "dev"))

import demo_pole  # type: ignore[import-not-found]  # noqa: E402
import demo_unit  # type: ignore[import-not-found]  # noqa: E402

from hospitalos.hybrid.planning import plan  # noqa: E402


@pytest.mark.parametrize(("factory", "digest"), [
    (demo_unit.nominal, "72d1c0b7fb6a99959220b122513f7e1fd9d0c62428dfd5611d05c6d9e5cc8d05"),
    (demo_unit.peak, "d4664d781db0da3bac8332c0e6958b4ff44a5317fbd35564601147da6c6664d8"),
    (demo_unit.incomplete, "8fccbf8ca11ab55123f3dcb7462ee7d87bb36ddf615247a7c0081e6307806442"),
    (demo_unit.perturbations, "c6e1e6e3a858da08440ca71622c324cce961520d8f7c5cea8b363a062a2cccb4"),
    (demo_pole.geriatrie, "2cc05c63a27bc45e86415b757c13cff2589f1d95346c3f996d013fb2576d6cdc"),
    (demo_pole.medecine_interne, "46ed15b19ea67324b66ae55c8c1ce6e1f7af3f985319415db12b1292a018f20f"),
    (demo_pole.pneumologie, "cc3dc86fb5cba886af3f6f60efb14e6b002ef5bf19fbb361ab7513c6d6b47168"),
])
def test_historical_plan_id(factory, digest):
    assert plan(factory()).plan_id == digest
