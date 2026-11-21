"""Conservation, indivisible named patients and shared operational capacity at noon."""

import numpy as np
import pytest
from numpy.typing import NDArray

from hospitalos.world_model import engine
from hospitalos.world_model.joint_physics import (
    JointAction,
    JointCase,
    JointResult,
    simulate_batch,
    simulate_joint,
)
from hospitalos.world_model.physics import rollout

ED, ACTIVE, READY, DIRTY, INTERNAL = range(5)
(
    ED_H,
    TRANSFER_H,
    UNMET_IDE,
    UNMET_AS,
    ADMITTED,
    DIRECT,
    SMR_EXIT,
    DIVERTED,
    IN,
    OUT,
    ARRIVED,
    LOAN,
    RECALL,
    VIOLATION,
) = range(14)


@pytest.fixture(scope="module")
def kernel() -> str:
    result = engine.manifest()["kernel_sha256"]
    assert isinstance(result, str)
    return result


def quiet() -> tuple[dict[str, NDArray[np.generic]], NDArray[np.float64], NDArray[np.float64]]:
    noop = np.array([0, -1, -1], dtype=np.int32)
    data = {
        "beds": np.full(4, 10.0),
        "route": np.array([1, 2, 3, 0], dtype=np.int32),
        "schedules": np.broadcast_to(noop, (1, 1, 4, 3)).copy(),
    }
    state = np.zeros((4, 5))
    tape = np.zeros((4, 4, 17))
    tape[..., 7:9] = 240.0
    return data, state, tape


def balance(initial: NDArray[np.float64], result: JointResult) -> None:
    m, end = result.metrics, result.stocks
    start_occupied = initial[:, ACTIVE] + initial[:, READY] + initial[:, INTERNAL]
    np.testing.assert_allclose(
        end[:, ED], initial[:, ED] + m[:, ARRIVED] - m[:, ADMITTED] - m[:, DIVERTED], atol=1e-7
    )
    np.testing.assert_allclose(
        result.occupied_beds,
        start_occupied + m[:, ADMITTED] + m[:, IN] - m[:, OUT] - m[:, DIRECT] - m[:, SMR_EXIT],
        atol=1e-7,
    )
    np.testing.assert_allclose(
        end[:, DIRTY],
        initial[:, DIRTY] + m[:, DIRECT] + m[:, SMR_EXIT] + m[:, OUT] - result.beds_cleaned,
        atol=1e-7,
    )
    np.testing.assert_allclose(
        result.capacities, result.occupied_beds + end[:, DIRTY] + result.clean_beds, atol=1e-7
    )
    assert m[:, IN].sum() == pytest.approx(m[:, OUT].sum())
    assert m[:, VIOLATION].sum() == 0
    assert (end >= -1e-7).all()
    assert np.all(result.transport_used + 1e-7 >= m[:, SMR_EXIT] + m[:, OUT])
    assert all(
        0 <= delivery <= result.requested[key] + 1e-7 for key, delivery in result.realized.items()
    )


@pytest.mark.parametrize("code", ["rives", "parc", "belvedere"])
def test_unnamed_baseline_matches_original_hourly_engine(code: str, kernel: str) -> None:
    data = engine.arrays(engine.cases()[code], "public")
    metrics, stocks = rollout(data, data["initial"], data["drivers"], data["schedules"][:1], kernel)
    matched = simulate_joint(data, data["initial"], data["drivers"], [], kernel)
    np.testing.assert_allclose(matched.stocks, stocks[0], atol=1e-12, rtol=1e-12)
    np.testing.assert_allclose(matched.metrics, metrics[0], atol=1e-12, rtol=1e-12)
    balance(data["initial"], matched)


def test_named_discharge_resources_accumulate_without_double_natural_exit(kernel: str) -> None:
    data, state, tape = quiet()
    state[0, ACTIVE] = 2
    tape[:, 0, 1] = 1.0  # All ordinary active patients leave immediately.
    tape[:, 0, 4] = [0.5, 0.0, 0.5, 0.0]
    cases = [JointCase("S1", "discharge", 0, 12, 16)]
    action = JointAction("coordinate-S1", "discharge", 0, patient_id="S1")
    normal, early = simulate_batch(data, state, tape, [[], [action]], kernel, known_cases=cases)
    assert normal.metrics[0, DIRECT] == 1 and normal.stocks[0, ACTIVE] == 1
    assert normal.case_hour == {"S1": None}
    assert early.case_hour == {"S1": 15}
    assert early.realized[action.id] == 1 and early.metrics[0, DIRECT] == 2
    assert early.stocks[0, ACTIVE] == 0 and early.stocks[0, DIRTY] == 2
    assert early.transport_used.sum() == 1
    balance(state, early)
    # A partial escort never becomes a fractional discharged person.
    tape[2, 0, 4] = 0.0
    unfinished = simulate_joint(data, state, tape, [action], kernel, known_cases=cases)
    assert unfinished.realized[action.id] == 0
    assert unfinished.transport_used.sum() == 0.5
    assert unfinished.stocks[0, ACTIVE] == 1


def test_named_admissions_use_the_existing_queue_and_an_ordinary_comparator(kernel: str) -> None:
    data, state, tape = quiet()
    state[0, ED] = 3
    cases = [JointCase("A1", "admission", 0, 12, 14), JointCase("A2", "admission", 0, 12, 16)]
    options = [JointAction(c.id, c.direction, c.ward) for c in cases]
    normal, early = simulate_batch(data, state, tape, [[], options], kernel, known_cases=cases)
    assert normal.case_hour == {"A1": 15, "A2": None}
    assert early.case_hour == {"A1": 13, "A2": 13}
    assert normal.metrics[0, ADMITTED] == 2 and early.metrics[0, ADMITTED] == 3
    assert normal.metrics[0, ED_H] == 6 and early.metrics[0, ED_H] == 0
    assert normal.metrics[:, ARRIVED].sum() == early.metrics[:, ARRIVED].sum() == 0
    assert early.stocks[0, ACTIVE] == 3 and state[0, ED] == 3
    balance(state, normal)
    balance(state, early)

    # At publication one person is actually present. A coordination request may
    # not insert the absent second person, or strip another ordinary arrival.
    state[0, ED] = 1
    tape[3, 0, 0] = 1
    missing = simulate_joint(data, state, tape, options, kernel, known_cases=cases)
    assert missing.case_present == {"A1": True, "A2": False}
    assert missing.realized == {"A1": 1.0, "A2": 0.0}
    assert missing.metrics[0, ARRIVED] == 1 and missing.metrics[0, ADMITTED] == 2
    balance(state, missing)


def test_discharge_cleaning_and_admission_need_a_joint_sequence(kernel: str) -> None:
    data, state, tape = quiet()
    data["beds"][0] = 1
    state[0, [ACTIVE, ED]] = 1
    tape[:, 0, 4] = 1
    tape[:, 0, 13] = 1  # Mobile cleaning crew available from 14:00.
    cases = [JointCase("S1", "discharge", 0, 12, 16), JointCase("A1", "admission", 0, 12, 16)]
    s, a = JointAction("S1", "discharge", 0), JointAction("A1", "admission", 0)
    clean = JointAction("C", "cleaning", 0)
    stay, dirty, full, different_order = simulate_batch(
        data, state, tape, [[a], [s, a], [s, a, clean], [clean, a, s]], kernel, known_cases=cases
    )
    assert stay.realized[a.id] == 0
    assert dirty.realized == {"S1": 1.0, "A1": 0.0}
    assert dirty.stocks[0, DIRTY] == 1 and dirty.stocks[0, ED] == 1
    assert full.realized == {"S1": 1.0, "A1": 1.0, "C": 1.0}
    assert full.case_hour == {"A1": 15, "S1": 13}
    assert full.stocks[0, ACTIVE] == 1 and full.stocks[0, ED] == full.stocks[0, DIRTY] == 0
    np.testing.assert_array_equal(full.metrics, different_order.metrics)
    np.testing.assert_array_equal(full.stocks, different_order.stocks)
    balance(state, dirty)
    balance(state, full)


def test_replacement_external_as_and_donor_protection_are_distinct(kernel: str) -> None:
    data, state, tape = quiet()
    state[:2, ACTIVE] = 6
    tape[:, :, 9:11] = 10
    tape[:, 0, 7:9] = 0
    tape[:, 1, 8] = [99, 129, 100, 128]  # AS donor need is 69; only 129 permits a loan.
    move = JointAction("mobile-AS", "redeploy", 0, donor=1)
    external = JointAction("external-AS", "as", 1)
    replacement = JointAction("replace-IDE", "replacement", 0)
    base, lone, both, full = simulate_batch(
        data,
        state,
        tape,
        [[], [move], [move, external], [replacement, move, external]],
        kernel,
    )
    assert lone.realized[move.id] == 60 and lone.requested[move.id] == 240
    assert both.realized == {move.id: 240.0, external.id: 240.0}
    assert full.realized[replacement.id] == 240
    assert full.metrics[0, UNMET_IDE] == base.metrics[0, UNMET_IDE] - 240
    assert full.metrics[0, UNMET_AS] == base.metrics[0, UNMET_AS] - 240
    assert full.metrics[1, UNMET_AS] == base.metrics[1, UNMET_AS] == 0
    np.testing.assert_allclose(lone.staff_minutes.sum(0), base.staff_minutes.sum(0))
    np.testing.assert_allclose(full.staff_minutes.sum(0) - base.staff_minutes.sum(0), [240, 240])
    assert full.staff_minutes[1, 1] == base.staff_minutes[1, 1]


def test_smr_uses_a_single_seat_and_shared_transport(kernel: str) -> None:
    data, state, tape = quiet()
    state[0, READY] = 4
    tape[:, 0, 12] = 2
    seat, port = JointAction("place", "smr", 0), JointAction("équipe", "transport", 0)
    seat_only, port_only, both = simulate_batch(
        data, state, tape, [[seat], [port], [seat, port]], kernel
    )
    assert seat_only.metrics[:, SMR_EXIT].sum() == port_only.metrics[:, SMR_EXIT].sum() == 0
    assert both.metrics[0, SMR_EXIT] == both.realized[seat.id] == 1
    assert both.realized[port.id] == 1 and both.requested[port.id] == 4
    assert both.transport_used.sum() == 1 and both.stocks[0, DIRTY] == 1
    balance(state, both)


def test_reserve_bed_and_inpatient_care_are_joint_prerequisites(kernel: str) -> None:
    data, state, tape = quiet()
    state[0, [ED, ACTIVE]] = [1, 10]
    tape[:, 0, 7] = 0
    a = JointAction("A1", "admission", 0)
    r = JointAction("reserve", "bed", 0)
    nurse = JointAction("IDE", "ide", 0)
    cases = [JointCase("A1", "admission", 0, 12, 16)]
    room, staff, both = simulate_batch(
        data, state, tape, [[a, r], [a, nurse], [a, r, nurse]], kernel, known_cases=cases
    )
    assert room.realized[a.id] == staff.realized[a.id] == 0
    assert both.realized[a.id] == 1 and both.beds_opened[0] == 1
    np.testing.assert_array_equal(both.capacities, [11, 10, 10, 10])
    assert both.occupied_beds[0] == 11 and both.clean_beds[0] == 0
    balance(state, both)


def test_plan_rejects_double_booking_or_mismatched_patient(kernel: str) -> None:
    data, state, tape = quiet()
    c = JointCase("A1", "admission", 0)
    bad_plans = [
        [
            JointAction("x", "admission", 0, patient_id="A1"),
            JointAction("y", "admission", 0, patient_id="A1"),
        ],
        [JointAction("x", "admission", 1, patient_id="A1")],
        [JointAction("x", "redeploy", 1, donor=1)],
        [JointAction("x", "as", 0), JointAction("y", "as", 1)],
        [JointAction("x", "transport", 0), JointAction("y", "transport", 1)],
        [JointAction("x", "bed", 0), JointAction("y", "bed", 0)],
    ]
    for plan in bad_plans:
        with pytest.raises(ValueError):
            simulate_joint(data, state, tape, plan, kernel, known_cases=[c])
    result = simulate_joint(
        data, state, tape, [JointAction("x", "bed", 0), JointAction("y", "bed", 1)], kernel
    )
    np.testing.assert_array_equal(result.beds_opened, [1, 1, 0, 0])
