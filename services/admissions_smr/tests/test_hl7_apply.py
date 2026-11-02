"""Applying IHE PAM movements: stays, emergency visits, beds, journal, cancellations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.admissions_smr.domain.hl7_pam import ParsedMovement, parse
from services.admissions_smr.domain.pseudonym import pseudonym
from services.admissions_smr.models import Bed, BedPool, EdVisit, Group, Movement, Site, Stay, User
from services.admissions_smr.movement_service import ApplyResult, apply_movement
from services.admissions_smr.security import hash_password

FIXTURES = Path(__file__).parent / "fixtures" / "hl7"
PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 10, 25, 8, 30, tzinfo=UTC)
SECRET = "p" * 40  # Settings default in tests is the dev secret; any value works here
PASSWORD = "mot-de-passe-solide"


def build_hospital(db: Session, name: str = "CH Test") -> Group:
    """MCO site (FINESS 590000017: ED 1001, medicine 2101, cardiology 2301) + SMR site 5101."""
    group = Group(name=name, created_at=NOW)
    db.add(group)
    db.flush()
    units = {
        ("CH Test", "590000017"): [
            ("urgences", "urgences", "1001", []),
            ("medecine_polyvalente", "medecine", "2101", [("2101", "2101", "X")]),
            ("cardiologie", "medecine", "2301", [("2301", "2301", "X")]),
        ],
        ("SMR Test", None): [("polyvalent", "smr", "5101", [("5101", "5101", "X")])],
    }
    for (site_name, finess), pools in units.items():
        site = Site(group_id=group.id, name=site_name, finess=finess, created_at=NOW)
        db.add(site)
        db.flush()
        for code, unit_type, uf, beds in pools:
            pool = BedPool(
                site_id=site.id,
                mention=code,
                beds_installed=len(beds),
                beds_open=len(beds),
                unit_type=unit_type,
                uf_code=uf,
                updated_at=NOW,
            )
            db.add(pool)
            db.flush()
            for room, label, sex in beds:
                db.add(
                    Bed(
                        group_id=group.id,
                        site_id=site.id,
                        pool_id=pool.id,
                        room=room,
                        label=label,
                        sex_constraint=sex,
                        status="libre",
                        updated_at=NOW,
                    )
                )
            if code != "urgences":
                room = f"{uf[:2]}02"
                for side in "AB":
                    db.add(
                        Bed(
                            group_id=group.id,
                            site_id=site.id,
                            pool_id=pool.id,
                            room=room,
                            label=room + side,
                            sex_constraint="F" if uf == "2301" else "X",
                            status="libre",
                            updated_at=NOW,
                        )
                    )
    for login, role in (
        ("agent", "ingestion"),
        ("coord", "coordination"),
        ("dir", "direction"),
        ("admin", "admin_groupe"),
    ):
        db.add(
            User(
                group_id=group.id,
                email=f"{login}@hl7.test",
                full_name=login,
                role=role,
                password_hash=hash_password(PASSWORD, 1000),
                created_at=NOW,
            )
        )
    db.commit()
    return group


def fixture(name: str) -> ParsedMovement:
    return parse((FIXTURES / f"{name}.hl7").read_bytes(), PARIS)


Apply = Callable[..., ApplyResult]


@pytest.fixture
def hospital(db: Session) -> Group:
    return build_hospital(db)


@pytest.fixture
def apply(db: Session, hospital: Group) -> Apply:
    def run(name_or_parsed: str | ParsedMovement) -> ApplyResult:
        parsed = fixture(name_or_parsed) if isinstance(name_or_parsed, str) else name_or_parsed
        result = apply_movement(db, hospital, parsed, NOW, secret=SECRET, zone=PARIS)
        db.commit()
        return result

    return run


def stay_of(db: Session, group: Group, nda: str) -> Stay | None:
    ref = pseudonym(SECRET, group.id, "nda", "GAM", nda)
    return db.scalar(select(Stay).where(Stay.encounter_ref == ref))


def bed(db: Session, label: str) -> Bed:
    found = db.scalar(select(Bed).where(Bed.label == label))
    assert found is not None
    return found


def unit(db: Session, stay: Stay) -> str:
    return stay.mention


def test_admission_creates_a_pseudonymous_stay_in_its_bed(
    db: Session, hospital: Group, apply: Apply
) -> None:
    # Act
    result = apply("a01_admission")

    # Assert
    assert (result.status, result.ack_code) == ("applied", "AA")
    stay = stay_of(db, hospital, "900001")
    assert stay is not None and stay.source == "hl7"
    assert stay.mention == "medecine_polyvalente" and stay.admission_date == date(2026, 10, 25)
    assert stay.patient_ref == pseudonym(SECRET, hospital.id, "ipp", "GAM", "IPP4242")
    assert (stay.patient_sex, stay.patient_age) == ("F", 76)
    assert stay.admitted_at == datetime(2026, 10, 25, 9, 0, tzinfo=PARIS)
    occupied = bed(db, "2102A")
    assert (occupied.status, occupied.stay_id, stay.bed_id) == ("occupe", stay.id, occupied.id)
    journal = db.scalars(select(Movement)).one()
    assert (journal.status, journal.event, journal.movement_ref) == ("applied", "A01", "MVT-1")
    assert journal.bed_id == occupied.id


def test_resending_the_same_message_has_no_effect(db: Session, apply: Apply) -> None:
    apply("a01_admission")

    again = apply("a01_admission")

    assert (again.status, again.ack_code) == ("duplicate", "AA")
    assert db.query(Stay).count() == 1 and db.query(Movement).count() == 1


def test_same_movement_under_a_new_control_id_is_journaled_as_duplicate(
    db: Session, apply: Apply
) -> None:
    apply("a01_admission")

    result = apply(replace(fixture("a01_admission"), control_id="MSG-A01-BIS"))

    assert result.status == "duplicate" and db.query(Stay).count() == 1
    assert sorted(m.status for m in db.query(Movement)) == ["applied", "duplicate"]


def test_transfer_moves_the_same_stay_and_leaves_a_bed_to_clean(
    db: Session, hospital: Group, apply: Apply
) -> None:
    apply("a01_admission")

    result = apply("a02_transfer")

    stay = stay_of(db, hospital, "900001")
    assert stay is not None and result.status == "applied"
    assert stay.mention == "cardiologie" and stay.bed_id == bed(db, "2302A").id
    assert stay.admission_date == date(2026, 10, 26)  # entry into the current unit
    assert stay.admitted_at == datetime(2026, 10, 25, 9, 0, tzinfo=PARIS)  # hospital admission
    assert bed(db, "2102A").status == "a_nettoyer" and bed(db, "2102A").stay_id is None
    assert bed(db, "2302A").status == "occupe"


def test_cancelled_transfer_restores_unit_bed_and_date(
    db: Session, hospital: Group, apply: Apply
) -> None:
    apply("a01_admission")
    apply("a02_transfer")

    result = apply("a12_cancel_transfer")

    stay = stay_of(db, hospital, "900001")
    assert stay is not None and result.status == "applied"
    assert stay.mention == "medecine_polyvalente" and stay.bed_id == bed(db, "2102A").id
    assert stay.admission_date == date(2026, 10, 25)
    assert bed(db, "2102A").status == "occupe" and bed(db, "2302A").status == "libre"
    statuses = {m.message_control_id: m.status for m in db.query(Movement)}
    assert statuses == {"MSG-A01": "applied", "MSG-A02": "cancelled", "MSG-A12": "applied"}


def test_discharge_frees_the_bed_and_its_cancellation_reopens_the_stay(
    db: Session, hospital: Group, apply: Apply
) -> None:
    apply("a01_admission")

    apply("a03_discharge")
    stay = stay_of(db, hospital, "900001")
    assert stay is not None and stay.discharge_date == date(2026, 10, 28)
    assert stay.discharged_at == datetime(2026, 10, 28, 10, 45, tzinfo=PARIS)
    assert stay.bed_id is None and bed(db, "2102A").status == "a_nettoyer"
    assert bed(db, "2102A").stay_id is None

    apply("a13_cancel_discharge")
    db.refresh(stay)
    assert stay.discharge_date is None and stay.discharged_at is None
    assert stay.bed_id == bed(db, "2102A").id and bed(db, "2102A").status == "occupe"


def test_cancelled_admission_removes_the_stay_and_frees_the_bed(
    db: Session, hospital: Group, apply: Apply
) -> None:
    apply("a01_admission")

    result = apply("a11_cancel_admission")

    assert result.status == "applied" and stay_of(db, hospital, "900001") is None
    assert bed(db, "2102A").status == "libre" and bed(db, "2102A").stay_id is None


def test_leave_of_absence_keeps_the_bed_and_cancellations_restore(
    db: Session, hospital: Group, apply: Apply
) -> None:
    apply("a01_admission")
    apply("a02_transfer")

    apply("a21_leave")
    kept = bed(db, "2302A")
    assert kept.status == "occupe" and kept.status_reason and "Absence" in kept.status_reason

    apply("a52_cancel_leave")
    db.refresh(kept)
    assert kept.status_reason is None

    apply("a21_leave")  # same message again: duplicate, still no leave
    db.refresh(kept)
    assert kept.status_reason is None

    apply(replace(fixture("a21_leave"), control_id="MSG-A21-2", movement_ref="MVT-3b"))
    apply("a22_return")
    db.refresh(kept)
    assert kept.status_reason is None and kept.status == "occupe"
    apply("a53_cancel_return")
    db.refresh(kept)
    assert kept.status_reason is not None


def test_emergency_visit_decision_then_hospitalisation_then_cancellation(
    db: Session, hospital: Group, apply: Apply
) -> None:
    ref = pseudonym(SECRET, hospital.id, "nda", "GAM", "900002")
    cardio = db.scalar(select(BedPool).where(BedPool.uf_code == "2301"))
    assert cardio is not None

    apply("a04_ed_arrival")
    visit = db.scalar(select(EdVisit).where(EdVisit.encounter_ref == ref))
    assert visit is not None and visit.arrived_at == datetime(
        2026, 10, 25, 0, 10, tzinfo=UTC
    )  # DST fold: first 02:10
    assert visit.left_at is None and visit.source == "hl7"

    apply("a02_ed_decision")
    db.refresh(visit)
    assert visit.admit_decision_at == datetime(2026, 10, 25, 4, 55, tzinfo=PARIS)
    assert visit.target_pool_id == cardio.id and visit.left_at is None
    assert stay_of(db, hospital, "900002") is None  # still in the emergency department

    apply("a06_ed_to_ward")
    db.refresh(visit)
    stay = stay_of(db, hospital, "900002")
    assert stay is not None and stay.admission_mode == "urgences" and stay.mention == "cardiologie"
    assert visit.outcome == "hospitalise" and visit.left_at == stay.admitted_at
    assert bed(db, "2301").stay_id == stay.id

    apply("a07_cancel_a06")
    db.refresh(visit)
    assert stay_of(db, hospital, "900002") is None and bed(db, "2301").status == "libre"
    assert visit.left_at is None and visit.outcome is None
    assert visit.admit_decision_at is not None  # the decision itself was not cancelled


def test_emergency_discharge_records_the_outcome(
    db: Session, hospital: Group, apply: Apply
) -> None:
    apply("a04_ed_arrival")

    apply("a03_ed_discharge")

    visit = db.scalars(select(EdVisit)).one()
    assert visit.outcome == "sortie" and visit.left_at == datetime(
        2026, 10, 25, 5, 50, tzinfo=PARIS
    )


def test_correction_z99_updates_the_referenced_movement(
    db: Session, hospital: Group, apply: Apply
) -> None:
    apply("a01_admission")

    result = apply("z99_update")

    stay = stay_of(db, hospital, "900001")
    assert result.status == "applied" and stay is not None
    assert stay.admitted_at == datetime(2026, 10, 25, 8, 30, tzinfo=PARIS)
    assert stay.bed_id == bed(db, "2101").id and bed(db, "2102A").status == "libre"
    original = db.scalar(select(Movement).where(Movement.message_control_id == "MSG-A01"))
    assert original is not None and original.bed_id == bed(db, "2101").id


def test_ignored_and_unknown_unit_and_out_of_order(
    db: Session, hospital: Group, apply: Apply
) -> None:
    assert apply("a05_preadmission_ignored").status == "ignored"

    unknown = apply(replace(fixture("a01_admission"), uf_code="9999", facility=None))
    assert (unknown.status, unknown.ack_code) == ("rejected", "AE")
    assert "UF 9999 inconnue" in unknown.message

    early = apply(replace(fixture("a03_discharge"), encounter_id="777"))
    assert early.status == "rejected" and "Sortie sans séjour" in early.message

    # Fixed by the sender and sent again with the same control id: now applied.
    fixed = apply(replace(fixture("a01_admission"), control_id=unknown_id(db)))
    assert fixed.status == "applied"
    assert db.query(Stay).count() == 1


def unknown_id(db: Session) -> str:
    row = db.scalar(select(Movement).where(Movement.status == "rejected", Movement.event == "A01"))
    assert row is not None
    return row.message_control_id


def test_bed_constraints_are_flagged_not_blocking(
    db: Session, hospital: Group, apply: Apply
) -> None:
    man = replace(fixture("a02_transfer"), sex="M")
    apply(replace(fixture("a01_admission"), sex="M"))

    result = apply(man)

    assert result.status == "applied" and "réservé aux femmes" in result.message
    journal = db.scalar(select(Movement).where(Movement.message_control_id == "MSG-A02"))
    assert journal is not None and journal.error and "réservé aux femmes" in journal.error
    stay = stay_of(db, hospital, "900001")
    assert stay is not None and stay.bed_id == bed(db, "2302A").id


def test_occupied_bed_keeps_the_stay_without_a_bed(
    db: Session, hospital: Group, apply: Apply
) -> None:
    apply("a01_admission")
    other = replace(
        fixture("a01_admission"),
        control_id="X1",
        movement_ref="X1",
        encounter_id="900003",
        patient_id="IPP9",
    )

    result = apply(other)

    assert result.status == "applied" and "déjà occupé" in result.message
    stay = stay_of(db, hospital, "900003")
    assert stay is not None and stay.bed_id is None
    assert bed(db, "2102A").stay_id == stay_of(db, hospital, "900001").id  # type: ignore[union-attr]


def test_only_the_last_movement_can_be_cancelled(db: Session, apply: Apply) -> None:
    apply("a01_admission")
    apply("a02_transfer")

    result = apply("a11_cancel_admission")

    assert result.status == "rejected" and "dernier mouvement" in result.message


def test_single_site_group_needs_no_finess_and_unit_found_by_uf(
    db: Session, hospital: Group, apply: Apply
) -> None:
    result = apply(
        replace(fixture("a01_admission"), facility=None, uf_code="5101", room=None, bed="5101")
    )

    stay = stay_of(db, hospital, "900001")
    assert result.status == "applied" and stay is not None and stay.mention == "polyvalent"
    assert stay.bed_id == bed(db, "5101").id
