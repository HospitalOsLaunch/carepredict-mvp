"""Product regressions for the five noon resource families, on synthetic cases only."""

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from httpx import Response
from numpy.typing import NDArray

from hospitalos.world_model import engine
from hospitalos.world_model.contracts import Session
from hospitalos.world_model.physics import rollout
from hospitalos.world_model.projection import reconstruct
from hospitalos.world_model.resources import Offer, simulate_offer
from services.api.hybrid_app import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(world_model_db=tmp_path / "five.sqlite")) as local:
        yield local


def session(response: Response) -> Session:
    assert response.is_success, response.text
    return Session.model_validate_json(response.content, strict=True)


def opened(client: TestClient, context: str) -> tuple[str, Session]:
    path = f"/world-model/sessions/{uuid4()}"
    return path, session(client.put(path, json={"context_id": context}))


@pytest.mark.parametrize("context", ["rives", "parc", "belvedere"])
def test_five_families_share_the_noon_catalogue(client: TestClient, context: str) -> None:
    _, state = opened(client, context)
    assert {o.kind for o in state.options} == {
        "reference",
        "transport",
        "cleaning",
        "staffing",
        "smr",
        "beds",
    }
    assert len({o.id for o in state.options}) == len(state.options)
    ids = {ward.id for ward in state.wards}
    for option in state.options:
        assert {"eligible", "constraint", "jepa_forecast"} <= option.model_fields_set
        assert option.ward_id is None if option.kind == "reference" else option.ward_id in ids
        assert len(option.by_ward) == state.context.ward_count
        assert option.forecast == pytest.approx(sum(option.by_ward))
        assert option.reconstruction is None and option.reconstructed_by_ward is None
        if option.kind in {"staffing", "smr", "beds"}:
            assert option.jepa_forecast is None
        else:
            assert option.jepa_forecast is not None
        if not option.eligible:
            assert option.constraint and option.constraint.strip()
    assert state.observation is None


def test_insufficient_budget_blocks_ide_and_allows_an_affordable_as(client: TestClient) -> None:
    path, initial = opened(client, "parc")
    ide = [o for o in initial.options if o.id.startswith("staffing-ide-")]
    assert ide and all(not option.eligible for option in ide)
    for option in ide:
        blocked = client.post(f"{path}/confirm", json={"option_id": option.id})
        assert blocked.status_code == 409, blocked.text
        assert session(client.get(path)) == initial
    affordable = next(o for o in initial.options if o.id.startswith("staffing-as-") and o.eligible)
    confirmed = session(client.post(f"{path}/confirm", json={"option_id": affordable.id}))
    assert confirmed.selected_id == affordable.id
    assert confirmed.phase == "confirmed" and confirmed.observation is None
    assert session(client.post(f"{path}/confirm", json={"option_id": affordable.id})) == confirmed


@pytest.mark.parametrize("family", ["staffing", "smr", "beds"])
def test_selected_resource_reaches_the_factual_replay(client: TestClient, family: str) -> None:
    path, initial = opened(client, "rives")
    selected = next(o for o in initial.options if o.kind == family and o.eligible)
    confirmed = session(client.post(f"{path}/confirm", json={"option_id": selected.id}))
    assert confirmed.morning_plan == initial.morning_plan
    assert confirmed.selected_id == selected.id and confirmed.observation is None
    done = session(client.post(f"{path}/advance", json={"from_hour": 12}))
    assert done.phase == "review" and done.observation is not None
    assert done.observation.sample_hour == done.observation.published_hour == 16
    assert done.observation.observed_stock is not None
    for option in done.options:
        if option.id == selected.id:
            assert option.reconstruction == pytest.approx(done.observation.observed_stock)
            assert option.reconstructed_by_ward == pytest.approx(done.observation.by_ward)
    assert done.morning_plan == initial.morning_plan
    assert session(client.post(f"{path}/advance", json={"from_hour": 12})) == done


def test_reserve_bed_capacity_applies_to_its_own_factual_or_alternative_option() -> None:
    # At noon both plans forecast two patients ready for SMR. The reserve-bed plan
    # can physically host three, and it alone yields the observed three at 16:00.
    prior = np.zeros((2, 1, 5))
    prior[:, 0, 2] = 2.0
    beds = np.array([[2.0], [3.0]])
    source = np.array([[0.0, 0.0, 3.0, 0.0, 0.0]])
    mask = np.ones((1, 5), dtype=bool)
    early = reconstruct(prior, 1, source, mask, beds, now=12, published=16)
    np.testing.assert_array_equal(early[:, 0, 2], [2.0, 2.0])
    after = reconstruct(prior, 1, source, mask, beds, now=16, published=16)
    np.testing.assert_array_equal(after[:, 0, 2], [2.0, 3.0])
    np.testing.assert_array_equal(after[1], source)
    assert np.all(after[..., 1:].sum(axis=-1) <= beds)


@pytest.fixture(scope="module")
def kernel() -> str:
    digest = engine.manifest()["kernel_sha256"]
    assert isinstance(digest, str)
    return digest


def quiet_wards() -> tuple[
    dict[str, NDArray[np.generic]], NDArray[np.float64], NDArray[np.float64]
]:
    # All four units start with ten open beds. Every movement must come from the test.
    noop = np.array([0, -1, -1], dtype=np.int32)
    data = {
        "beds": np.full(4, 10.0),
        "route": np.array([1, 2, 3, 0], dtype=np.int32),
        "schedules": np.broadcast_to(noop, (1, 1, 4, 3)).copy(),
    }
    return data, np.zeros((4, 5)), np.zeros((4, 4, 17))


@pytest.mark.parametrize("mode,skill,other", [("ide", 2, 3), ("as", 3, 2)])
def test_noon_shift_delivers_four_hours_only_for_its_skill(
    kernel: str, mode: str, skill: int, other: int
) -> None:
    data, state, tape = quiet_wards()
    state[0, 1] = 6.0
    # Each occupied bed needs ten minutes per skill per hour. Base supply is zero.
    tape[:, :, 9:11] = 10
    baseline, _ = rollout(data, state, tape, data["schedules"], kernel)
    offer = Offer("extra", "staffing", mode, 0, "Renfort", 190 if mode == "ide" else 140, "", True)
    after, end = simulate_offer(data, state, tape, offer, kernel)
    assert baseline[0, 0, skill] - after[0, skill] == pytest.approx(4 * 60)
    np.testing.assert_array_equal(after[:, other], baseline[0, :, other])
    np.testing.assert_array_equal(after[1:], baseline[0, 1:])
    np.testing.assert_array_equal(end, state)
    np.testing.assert_array_equal(tape[:, :, 7:9], 0)


def test_loan_checks_actual_donor_each_hour_and_records_recalled_hours(kernel: str) -> None:
    data, state, tape = quiet_wards()
    state[:2, 1] = 6
    tape[:, :, 9] = 10  # 12 + 6 * 10 = 72 IDE minutes needed each hour.
    tape[:, :, 8] = 180
    tape[:, 1, 7] = [150, 120, 131, 132]
    baseline, _ = rollout(data, state, tape, data["schedules"], kernel)
    loan = Offer("loan", "staffing", "loan", 0, "Prêt IDE", 0, "", True, donor=1)
    after, _ = simulate_offer(data, state, tape, loan, kernel)
    assert baseline[0, 0, 2] - after[0, 2] == pytest.approx(120)
    assert after[1, 2] == baseline[0, 1, 2] == 0
    assert after[1, 11] == 2  # Donor, two delivered IDE-hours.
    assert after[1, 12] == 2  # Donor, two recalls at the floor.
    assert after[:, 13].sum() == 0


def test_single_smr_place_waits_for_transport_and_is_consumed_once(kernel: str) -> None:
    data, state, tape = quiet_wards()
    state[0, 2] = 8
    offer = Offer("seat", "smr", "smr", 0, "Place SMR", 85, "", True)
    no_vehicle, _ = simulate_offer(data, state, tape, offer, kernel)
    assert no_vehicle[:, 6].sum() == 0

    # The original morning SMR block still delivers one ordinary place per hour
    # from 13:00. Delayed transport allows both ordinary and additional departures.
    data["schedules"][0, 0, 1] = [3, 0, -1]
    tape[:, 0, 14] = 1
    tape[2:, 0, 4] = 8
    baseline, _ = rollout(data, state, tape, data["schedules"], kernel)
    after, end = simulate_offer(data, state, tape, offer, kernel)
    assert baseline[0, 0, 6] == 2
    assert after[0, 6] == 3
    assert end[0, 2] == 5 and end[0, 3] == 3


@pytest.mark.parametrize("staff,admitted", [(0, 0), (300, 1)])
def test_equipped_bed_needs_staff_and_only_increases_target_capacity(
    kernel: str, staff: int, admitted: int
) -> None:
    data, state, tape = quiet_wards()
    state[0, :2] = [3, 10]  # Three waiting for a bed, ten already occupied.
    tape[:, :, 7:9] = staff
    baseline, baseline_end = rollout(data, state, tape, data["schedules"], kernel)
    offer = Offer("reserve", "beds", "bed", 0, "Lit de réserve", 0, "", True)
    after, end = simulate_offer(data, state, tape, offer, kernel)
    assert baseline[0, 0, 4] == 0 and after[0, 4] == admitted
    assert end[0, 1] == 10 + admitted
    assert baseline[0, 0, 0] - after[0, 0] == 4 * admitted  # Cumulative bed-wait patient-hours.
    np.testing.assert_array_equal(end[1:], baseline_end[0, 1:])
    np.testing.assert_array_equal(data["beds"], [10, 10, 10, 10])
