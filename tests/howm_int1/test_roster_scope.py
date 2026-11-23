"""The five-year exporter owns a calendar for each monthly episode."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/filter_pipeline"))
import longitudinal
from common import W


def test_roster_length_is_per_engine():
    sp = W.n_unit_structure("ROSTER_FIXTURE", 1, 4)
    provider = W.ProvN(sp, 0)
    normal = W.ROSTER_HOURS
    for hours in [41 * 24, normal, 24]:
        eng = W.initial_engine(sp, provider, roster_hours=hours)
        assert {len(r) for unit in eng.units.values() for r in unit.roster.values()} == {hours}
        assert W.ROSTER_HOURS == normal
    standard = W.initial_engine(sp, provider)
    assert {len(r) for unit in standard.units.values() for r in unit.roster.values()} == {normal}


def test_monthly_export_keeps_default_even_during_failure(monkeypatch):
    normal = W.ROSTER_HOURS

    def stop_after_initialization(eng):
        assert {len(r) for unit in eng.units.values() for r in unit.roster.values()} == {41 * 24}
        assert W.ROSTER_HOURS == normal
        raise RuntimeError("fixture interrupts the monthly export")

    monkeypatch.setattr(longitudinal, "freeze_rosters", stop_after_initialization)
    with pytest.raises(RuntimeError, match="fixture interrupts"):
        longitudinal.generate_episode("ROSTER_FIXTURE", 1, 0, {}, [])
    assert W.ROSTER_HOURS == normal
