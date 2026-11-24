"""A synthetic booked admission and a confirmed staff offer in the selected unit."""

from datetime import timedelta

from demo_unit import AT, HOSPITAL, SOURCE, UNIT

from hospitalos.hybrid.models import Bed, FactEvent, Unit
from hospitalos.hybrid.planning import PlanRequest
from hospitalos.hybrid.scenarios import FutureAssumptions, ResourceChange
from hospitalos.hybrid.unit_schedule import UnitSchedule


def handover() -> PlanRequest:
    def after(minutes: int):
        return AT + timedelta(minutes=minutes)

    schedule = UnitSchedule.model_validate(
        {
            "id": UNIT,
            "budget_minutes": 60,
            "offers": [
                {
                    "staff_id": "IDE-pool-A",
                    "staffed_places": 1,
                    "option": {
                        "option_id": "IDE-garde",
                        "start": after(30),
                        "end": after(90),
                        "skill": "IDE",
                        "source": "shared_unit",
                        "lending_unit": "medecine-interne",
                        "lending_unit_scheduled": 4,
                        "lending_unit_minimum": 3,
                        "confirmation": "confirmed",
                    },
                }
            ],
            "admissions": [
                {
                    "request": {
                        "request_id": "ADM-garde",
                        "requirements": ["oxygene"],
                        "expected_arrival": after(40),
                        "arrival_delay": {"support": [0], "weights": [1]},
                        "care": [],
                        "admission_task_minutes": 90,
                        "provenance": {
                            "source": SOURCE,
                            "obs_id": "prog-garde",
                            "event_time": AT,
                            "available_at": AT,
                        },
                    },
                    "window_start": after(30),
                    "window_end": after(80),
                }
            ],
        }
    )
    facts = (
        Unit(id=UNIT, staffed_beds=0, cleaning_teams=1),
        Bed(id="L-garde", unit_id=UNIT, state="clean", capabilities=("oxygene",)),
        schedule,
    )
    return PlanRequest(
        hospital_id=HOSPITAL,
        unit_id=UNIT,
        at=AT,
        expected_entities=tuple(f"{f.kind}:{f.id}" for f in facts),
        events=tuple(
            FactEvent(
                hospital_id=HOSPITAL,
                source=SOURCE,
                event_id=f"garde:{f.kind}",
                event_time=AT,
                available_at=AT,
                fact=f,
            )
            for f in facts
        ),
        future=FutureAssumptions(
            declared_at=AT,
            changes=(
                ResourceChange(
                    id="releve", minute=90, resource="staffed_beds", target_id=UNIT, capacity=1
                ),
            ),
        ),
    )
