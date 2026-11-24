from dataclasses import replace

from hospitalos.hybrid.models import Action
from scripts.unit_planning.decision_challenge import (
    HORIZON,
    Realization,
    booking_outcome,
    case,
    realizations,
    waiting_cost,
)


def test_bed_competition_hand_calculation_and_late_reservation() -> None:
    c = replace(
        case("compatible_beds", 0),
        beds=(("A", "clean", True), ("B", "clean", False)),
        queue=(("w0", False), ("w1", True)),
        initial_capacity=2,
    )
    w = next(realizations(c))
    reserve = (Action(kind="reserve_bed", bed_id="A", patient_id="w1"),)
    assert waiting_cost(c, (), w) == HORIZON
    assert waiting_cost(c, reserve, w) == 0
    assert waiting_cost(c, reserve, w, active=False, gesture_at=30) == HORIZON
    assert waiting_cost(c, (), w, active=False) == HORIZON
    assert not any(
        len(p) == 2 and p[0].kind == p[1].kind == "reserve_bed" and p[0].bed_id == p[1].bed_id
        for p in c.programs(2)
    )


def test_real_booking_work_and_unannounced_capacity_loss() -> None:
    c = replace(case("staff_booking", 0), initial_capacity=0, team_delay=60, schedule_capacity=110)
    w = Realization({}, 0, 0, 40, 70)
    assert booking_outcome(c, set(), w) == (70, 0)
    assert booking_outcome(c, {"reinforce", "prepare_admission"}, w) == (30, 0)
    assert booking_outcome(c, set(), w, shock=True) == (110, 0)
    assert booking_outcome(c, {"reinforce", "prepare_admission"}, w, shock=True) == (30, 60)


def test_identical_future_and_zero_incremental_gain_for_redundant_transport() -> None:
    c = replace(
        case("transport_cleaning", 0),
        beds=(("C", "occupied", True),),
        queue=(("w", True),),
        team_delay=30,
    )
    w = Realization({"C": 20}, 90, 15, 0, 0)
    action = (Action(kind="request_transport", bed_id="C", patient_id="out"),)
    assert waiting_cost(c, action, w, active=False, preparing=True) == 125
    assert waiting_cost(c, action, w, active=False, gesture_at=30, preparing=True) == 125
    assert waiting_cost(c, action, w, active=False, gesture_at=30, preparing=False) == 155
