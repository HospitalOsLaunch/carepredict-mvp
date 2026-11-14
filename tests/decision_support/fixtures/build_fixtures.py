"""Deterministic generator of the synthetic P1 fixtures (pseudonymous, no real data).

    PYTHONPATH=src:. python3 tests/decision_support/fixtures/build_fixtures.py

All parameters are synthetic and hand-checkable; they are NOT validated clinical or
operational values and no interview was carried out. Each fixture keeps a ``private_truth``
section (realised primitives, including legacy-style ready_h/dis_h) that the public snapshot
builder never reads; it exists only to test the information boundary and the evaluation.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
PARIS = ZoneInfo("Europe/Paris")
AS_OF_LOCAL = datetime(2026, 11, 16, 20, 0, tzinfo=PARIS)  # Monday 20:00, plans "demain 20 h"


def at(day: int, hour: int, minute: int = 0) -> str:
    """Local Paris civil time (day 0 = 16 Nov 2026) as a UTC ISO instant."""
    local = datetime(2026, 11, 16 + day, hour, minute, tzinfo=PARIS)
    return local.astimezone(ZoneInfo("UTC")).isoformat()


def obs(oid: str, kind: str, subject: str, event: str, value: dict, avail_min: int = 5) -> dict:
    available = (datetime.fromisoformat(event) + timedelta(minutes=avail_min)).isoformat()
    return {
        "obs_id": oid,
        "kind": kind,
        "subject": subject,
        "event_time": event,
        "available_at": available,
        "source": "synthetic_feed",
        "synthetic": True,
        "value": value,
    }


def dist(*pairs: tuple[int, int]) -> dict:
    return {"support": [p[0] for p in pairs], "weights": [p[1] for p in pairs]}


def nominal() -> dict:
    o: list[dict] = []
    beds = {
        "L01": ["oxygen"],
        "L02": [],
        "L03": ["oxygen"],
        "L04": [],
        "L05": [],
        "L06": [],
        "L07": ["oxygen"],
        "L08": [],
    }
    for b, caps in beds.items():
        status = "dirty" if b == "L08" else "occupied"
        o.append(
            obs(
                f"o-bed-{b}",
                "bed",
                b,
                at(0, 19, 30),
                {"status": status, "capabilities": caps, "cleaning_hours": dist((1, 1))},
            )
        )
    stays = {  # stay: (bed, IDE day, IDE night)
        "S01": ("L01", 20, 8),
        "S02": ("L02", 15, 6),
        "S03": ("L03", 30, 12),
        "S04": ("L04", 25, 10),
        "S05": ("L05", 20, 8),
        "S06": ("L06", 20, 8),
        "S07": ("L07", 35, 15),
    }
    for s, (bed, d, n) in stays.items():
        o.append(obs(f"o-stay-{s}", "stay", s, at(0, 8), {"bed_id": bed, "present": True}))
        o.append(
            obs(
                f"o-care-{s}",
                "care_profile",
                f"{s}.IDE",
                at(0, 19),
                {
                    "stay_id": s,
                    "skill": "IDE",
                    "day_minutes_per_hour": d,
                    "night_minutes_per_hour": n,
                    "status": "estimated",
                },
            )
        )
    auth = {
        "S01": "authorized",
        "S02": "authorized",
        "S03": "not_authorized",
        "S04": "not_authorized",
        "S06": "authorized",
        "S07": "not_authorized",
    }
    for s, status in auth.items():
        o.append(
            obs(
                f"o-auth-{s}",
                "medical_authorization",
                s,
                at(0, 15),
                {"status": status, "by_role": "medecin"},
            )
        )
    # S05: authorised at 15:00 then revoked at 18:30 (T05 inside the nominal case)
    o.append(
        obs(
            "o-auth-S05-a",
            "medical_authorization",
            "S05",
            at(0, 15),
            {"status": "authorized", "by_role": "medecin"},
        )
    )
    o.append(
        obs(
            "o-auth-S05-b",
            "medical_authorization",
            "S05",
            at(0, 18, 30),
            {"status": "revoked", "by_role": "medecin"},
        )
    )
    # T02: an authorisation for S07 decided before 20:00 but only received at 20:20 -> excluded
    o.append(
        obs(
            "o-auth-S07-late",
            "medical_authorization",
            "S07",
            at(0, 19, 50),
            {"status": "authorized", "by_role": "medecin"},
            avail_min=30,
        )
    )
    # T02: an observation whose event is after the decision -> excluded
    o.append(
        obs(
            "o-auth-S04-future",
            "medical_authorization",
            "S04",
            at(0, 21),
            {"status": "authorized", "by_role": "medecin"},
        )
    )
    logistics = {
        "S01": {
            "destination": "home",
            "transport_need": "seated",
            "transport_lead_hours": dist((2, 1), (3, 1)),
        },
        "S02": {"destination": "home", "transport_need": "none"},
        "S05": {
            "destination": "home",
            "transport_need": "seated",
            "transport_lead_hours": dist((2, 1)),
        },
        "S06": {
            "destination": "facility",
            "transport_need": "stretcher",
            "transport_lead_hours": dist((3, 1)),
        },
    }
    for s, v in logistics.items():
        o.append(obs(f"o-logi-{s}", "discharge_logistics", s, at(0, 16), v))
    o.append(
        obs(
            "o-ready-S01",
            "readiness_estimate",
            "S01",
            at(0, 16),
            {"earliest": at(1, 9), "delay_hours": dist((0, 3), (1, 1))},
        )
    )
    o.append(
        obs(
            "o-ready-S02",
            "readiness_estimate",
            "S02",
            at(0, 16),
            {"earliest": at(1, 11), "delay_hours": dist((0, 1))},
        )
    )
    o.append(
        obs(
            "o-ready-S06",
            "readiness_estimate",
            "S06",
            at(0, 16),
            {"earliest": at(1, 10), "delay_hours": dist((0, 1))},
        )
    )
    o.append(obs("o-plan-S02", "planned_departure", "S02", at(0, 16), {"at": at(1, 12)}))
    o.append(
        obs(
            "o-obst-S06",
            "obstacle",
            "S06.aval",
            at(0, 17),
            {"stay_id": "S06", "code": "aval_non_confirme", "active": True},
        )
    )
    o.append(
        obs(
            "o-task-S03",
            "care_task",
            "T-S03-mob",
            at(0, 18),
            {
                "stay_id": "S03",
                "skill": "IDE",
                "start": at(1, 8),
                "minutes": 20,
                "staff_required": 2,
                "status": "known",
            },
        )
    )
    o.append(
        obs(
            "o-adm-A01",
            "admission_request",
            "A01",
            at(0, 18),
            {
                "requirements": [],
                "expected_arrival": at(0, 18),
                "arrival_delay": dist((0, 1)),
                "care": [
                    {
                        "skill": "IDE",
                        "day_minutes_per_hour": 25,
                        "night_minutes_per_hour": 10,
                        "status": "estimated",
                    }
                ],
                "admission_task_minutes": 45,
            },
        )
    )
    o.append(
        obs(
            "o-adm-A02",
            "admission_request",
            "A02",
            at(0, 19),
            {
                "requirements": ["oxygen"],
                "expected_arrival": at(1, 9),
                "arrival_delay": dist((0, 1), (1, 1)),
                "care": [
                    {
                        "skill": "IDE",
                        "day_minutes_per_hour": 30,
                        "night_minutes_per_hour": 12,
                        "status": "estimated",
                    }
                ],
                "admission_task_minutes": 45,
            },
        )
    )
    shifts = [
        ("E1", 0, 14, 0, 21),
        ("E2", 0, 14, 0, 21),
        ("N1", 0, 21, 1, 7),
        ("N2", 0, 21, 1, 7),
        ("M1", 1, 7, 1, 14),
        ("M2", 1, 7, 1, 14),
        ("M3", 1, 7, 1, 14),
        ("P1", 1, 14, 1, 21),
        ("P2", 1, 14, 1, 21),
    ]
    for sid, d0, h0, d1, h1 in shifts:
        o.append(
            obs(
                f"o-shift-{sid}",
                "staff_shift",
                sid,
                at(0, 12),
                {"skill": "IDE", "start": at(d0, h0), "end": at(d1, h1), "status": "scheduled"},
            )
        )
    o.append(
        obs(
            "o-roster-IDE",
            "roster_coverage",
            "IDE-window",
            at(0, 12),
            {"skill": "IDE", "start": at(0, 14), "end": at(1, 21)},
        )
    )
    o.append(
        obs(
            "o-r1",
            "reinforcement_option",
            "R1",
            at(0, 17),
            {
                "skill": "IDE",
                "start": at(1, 14),
                "end": at(1, 20),
                "source": "interim",
                "confirmation": "requested",
            },
        )
    )
    o.append(
        obs(
            "o-r2",
            "reinforcement_option",
            "R2",
            at(0, 17),
            {
                "skill": "IDE",
                "start": at(1, 7),
                "end": at(1, 11),
                "source": "internal_pool",
                "confirmation": "confirmed",
            },
        )
    )
    o.append(
        obs(
            "o-r3",
            "reinforcement_option",
            "R3",
            at(0, 17),
            {
                "skill": "IDE",
                "start": at(1, 14),
                "end": at(1, 20),
                "source": "shared_unit",
                "confirmation": "confirmed",
                "lending_unit": "U-CARDIO-SYN",
                "lending_unit_scheduled": 3,
                "lending_unit_minimum": 3,
            },
        )
    )
    o.append(
        obs(
            "o-team-tr",
            "team_capacity",
            "transport-day1",
            at(0, 12),
            {
                "team": "transport",
                "start": at(1, 8),
                "end": at(1, 18),
                "capacity": 1,
                "external_commitments": 0,
            },
        )
    )
    o.append(
        obs(
            "o-team-tr-16",
            "team_capacity",
            "transport-day1-16h",
            at(0, 12),
            {
                "team": "transport",
                "start": at(1, 16),
                "end": at(1, 17),
                "capacity": 1,
                "external_commitments": 1,
            },
        )
    )
    o.append(
        obs(
            "o-team-cl-0",
            "team_capacity",
            "cleaning-day0",
            at(0, 12),
            {
                "team": "cleaning",
                "start": at(0, 20),
                "end": at(0, 21),
                "capacity": 1,
                "external_commitments": 1,
            },
        )
    )
    o.append(
        obs(
            "o-team-cl-1",
            "team_capacity",
            "cleaning-day1",
            at(0, 12),
            {
                "team": "cleaning",
                "start": at(1, 7),
                "end": at(1, 21),
                "capacity": 1,
                "external_commitments": 0,
            },
        )
    )
    truth = {
        "note": "realised primitives of this synthetic episode; private; evaluation only",
        "primitives": {
            "readiness": {"S01": 1, "S02": 0, "S06": 0, "S05": 0},
            "transport_lead": {"S01": 3, "S05": 2, "S06": 3},
            "cleaning": {"L08|initial": 1, "L01|S01": 1, "L02|S02": 1, "L05|S05": 1, "L06|S06": 1},
            "cleaning_remaining": {},
            "arrival": {"A01": 0, "A02": 1},
        },
        "legacy": {
            "ready_h": {"S01": 14},
            "dis_h": {"S01": 21},
            "comment": "legacy-style private fields; must never reach the planner",
        },
    }
    return {
        "fixture_id": "FX-NOMINAL-AUTO",
        "version": "1",
        "synthetic": True,
        "description": "Nominal auto case: no user scenario. Unit U-MED-SYN, 8 beds, 7 stays.",
        "as_of": AS_OF_LOCAL.astimezone(ZoneInfo("UTC")).isoformat(),
        "observations": o,
        "private_truth": truth,
    }


def truth_variant(fx: dict) -> dict:
    """Same public observations, different private future (T03)."""
    fx = copy.deepcopy(fx)
    fx["fixture_id"] = "FX-NOMINAL-AUTO-TRUTH-B"
    p = fx["private_truth"]["primitives"]
    p["readiness"]["S01"] = 0
    p["transport_lead"]["S01"] = 2
    p["arrival"]["A02"] = 0
    fx["private_truth"]["legacy"] = {"ready_h": {"S01": 13}, "dis_h": {"S01": 15}}
    return fx


def no_action() -> dict:
    """Calm unit where the habitual practice is already sufficient (T16)."""
    fx = nominal()
    keep_beds = {"L01", "L02", "L03", "L04", "L05"}
    out = []
    for o in fx["observations"]:
        subj = o["value"].get("stay_id", o["subject"])
        if o["kind"] == "bed" and o["subject"] not in keep_beds:
            continue
        if subj in {"S03", "S04", "S05", "S06", "S07", "A01", "A02"}:
            continue
        if o["kind"] in {"admission_request", "care_task"}:
            continue
        if o["kind"] == "stay" and o["subject"] not in {"S01", "S02"}:
            continue
        if o["kind"] == "bed" and o["subject"] in {"L03", "L04", "L05"}:
            o = copy.deepcopy(o)
            o["value"]["status"] = "clean"
        out.append(o)
    fx["observations"] = out
    fx["fixture_id"] = "FX-NO-ACTION"
    fx["description"] = "Two stays, enough staff, no waiting admission: habitual practice suffices."
    fx["private_truth"]["primitives"]["arrival"] = {}
    return fx


def insufficient() -> dict:
    """Roster coverage missing for the next afternoon (T17)."""
    fx = nominal()
    for o in fx["observations"]:
        if o["kind"] == "roster_coverage":
            o["value"]["end"] = at(1, 14)
    fx["fixture_id"] = "FX-INSUFFICIENT-DATA"
    fx["description"] = "IDE roster only declared complete until 14:00 tomorrow."
    return fx


SCENARIOS = {
    "scenario_x1x2.json": {
        "scenario_id": "SC-X1X2",
        "fixture": "nominal_auto.json",
        "synthetic": True,
        "description": "X1=S01 discharge locked at 10:00 (observed authorisation, validated "
        "instruction); X2=S02 presence prolonged t=4 h from its visible "
        "planned departure 12:00; complements searched until tomorrow 20:00.",
        "locks": {
            "locks": [
                {
                    "kind": "discharge_at",
                    "stay_id": "S01",
                    "at": at(1, 10),
                    "basis": "validated_instruction",
                },
                {
                    "kind": "extend_presence",
                    "stay_id": "S02",
                    "reference_time": at(1, 12),
                    "extension_hours": 4,
                    "basis": "validated_instruction",
                },
            ],
            "deadline": {"day_offset": 1, "local_time": "20:00:00"},
            "search_complements": True,
        },
    },
    "scenario_hypothesis.json": {
        "scenario_id": "SC-HYPOTHESIS",
        "fixture": "nominal_auto.json",
        "synthetic": True,
        "description": "Hypothetical discharge of S04 (no authorisation) at 13:00 (T06).",
        "locks": {
            "locks": [
                {
                    "kind": "discharge_at",
                    "stay_id": "S04",
                    "at": at(1, 13),
                    "basis": "hypothesis_only",
                }
            ],
            "deadline": {"day_offset": 1, "local_time": "20:00:00"},
        },
    },
    "scenario_impossible.json": {
        "scenario_id": "SC-IMPOSSIBLE",
        "fixture": "nominal_auto.json",
        "synthetic": True,
        "description": "S01 discharge locked at 16:00 when transport is fully committed "
        "elsewhere: locked scenario violates a resource constraint.",
        "locks": {
            "locks": [
                {
                    "kind": "discharge_at",
                    "stay_id": "S01",
                    "at": at(1, 16),
                    "basis": "validated_instruction",
                }
            ],
            "deadline": {"day_offset": 1, "local_time": "20:00:00"},
        },
    },
    "scenario_contradictory.json": {
        "scenario_id": "SC-CONTRADICTORY",
        "fixture": "nominal_auto.json",
        "synthetic": True,
        "description": "S02 both discharged at 10:00 and prolonged: contradictory locks.",
        "locks": {
            "locks": [
                {
                    "kind": "discharge_at",
                    "stay_id": "S02",
                    "at": at(1, 10),
                    "basis": "validated_instruction",
                },
                {
                    "kind": "extend_presence",
                    "stay_id": "S02",
                    "reference_time": at(1, 12),
                    "extension_hours": 2,
                    "basis": "validated_instruction",
                },
            ],
            "deadline": {"day_offset": 1, "local_time": "20:00:00"},
        },
    },
}


def main() -> None:
    fx = nominal()
    files = {
        "nominal_auto.json": fx,
        "nominal_auto_truth_b.json": truth_variant(fx),
        "no_action.json": no_action(),
        "insufficient_data.json": insufficient(),
        **SCENARIOS,
    }
    for name, body in files.items():
        (HERE / name).write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
        print(name)


if __name__ == "__main__":
    main()
