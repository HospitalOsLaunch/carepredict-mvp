from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from services.admissions_smr.domain.scoring import (
    DayAvailability,
    RequestFeatures,
    SiteCandidate,
    normalise_weights,
    prioritise,
)

TODAY = date(2026, 10, 25)
NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


def request(**kw: object) -> RequestFeatures:
    base: dict[str, object] = {
        "request_id": 1,
        "received_at": NOW - timedelta(hours=24),
        "mention": "geriatrie",
        "care_level": 2,
        "isolation_required": False,
        "needs": frozenset(),
        "desired_date": TODAY + timedelta(days=1),
        "referrer_facility": "CH A",
    }
    base.update(kw)
    return RequestFeatures(**base)  # type: ignore[arg-type]


def availability(free_from_day: int, prob: float = 0.95) -> list[DayAvailability]:
    return [
        DayAvailability(
            TODAY + timedelta(days=k),
            2.0 if k >= free_from_day else 0.0,
            prob if k >= free_from_day else 0.05,
        )
        for k in range(14)
    ]


def site(site_id: int, free_from_day: int = 0, **kw: object) -> SiteCandidate:
    base: dict[str, object] = {
        "site_id": site_id,
        "site_name": f"Site {site_id}",
        "mentions": frozenset({"geriatrie"}),
        "capabilities": frozenset({"oxygene"}),
        "isolation_rooms_by_mention": {"geriatrie": 1},
        "availability_by_mention": {"geriatrie": availability(free_from_day)},
    }
    base.update(kw)
    return SiteCandidate(**base)  # type: ignore[arg-type]


def test_weights_are_normalised_and_unknown_keys_ignored() -> None:
    w = normalise_weights({"disponibilite": 2, "attente": 0, "urgence": 0, "adresseur": 0, "x": 5})
    assert w["disponibilite"] == pytest.approx(1.0)
    assert sum(w.values()) == pytest.approx(1.0)


def test_blockers_make_a_site_ineligible() -> None:
    req = request(needs=frozenset({"dialyse"}), isolation_required=True, mention="neuro")
    result = prioritise(req, [site(1, isolation_rooms_by_mention={"geriatrie": 0})], TODAY, NOW)
    s = result.suggestions[0]
    assert not s.eligible
    assert len(s.blockers) == 3
    assert result.best is None
    assert result.score == 0.0


def test_site_with_earlier_bed_ranks_first_and_dates_are_explained() -> None:
    result = prioritise(request(), [site(1, free_from_day=6), site(2, free_from_day=1)], TODAY, NOW)
    assert result.best is not None
    assert result.best.site_id == 2
    assert result.best.safe_date == TODAY + timedelta(days=1)
    dispo = next(f for f in result.best.factors if f.code == "disponibilite")
    assert dispo.value == pytest.approx(1.0)
    assert "date souhaitée" in dispo.detail


def test_probable_but_not_safe_date_is_discounted() -> None:
    uncertain = site(1, availability_by_mention={"geriatrie": availability(0, prob=0.5)})
    result = prioritise(request(desired_date=TODAY), [uncertain], TODAY, NOW)
    assert result.best is not None
    assert result.best.safe_date is None
    assert result.best.probable_date == TODAY
    dispo = next(f for f in result.best.factors if f.code == "disponibilite")
    assert dispo.value == pytest.approx(0.6)


def test_waiting_time_raises_priority() -> None:
    fresh = prioritise(request(received_at=NOW - timedelta(minutes=10)), [site(1)], TODAY, NOW)
    old = prioritise(request(received_at=NOW - timedelta(hours=60)), [site(1)], TODAY, NOW)
    assert old.score > fresh.score


def test_preferred_site_is_kept_when_eligible() -> None:
    result = prioritise(
        request(),
        [site(1, free_from_day=0), site(2, free_from_day=8)],
        TODAY,
        NOW,
        preferred_site_id=2,
    )
    assert result.best is not None and result.best.site_id == 2
