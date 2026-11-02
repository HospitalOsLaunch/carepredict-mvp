"""Apply a parsed patient movement to the journal, stays, emergency visits and beds.

One path for HL7 messages and for the movements the computer-use agent reads on screen:
pseudonymise, deduplicate, resolve the unit and the bed, then replay the encounter's
effective movements (``hl7_pam.project``) and make the tables match. A cancellation or a
correction changes the journal, then replays the same way, so the previous state comes
back from the journal itself. Never commits: the caller owns the transaction.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.admissions_smr.domain.hl7_pam import (
    CANCELS,
    ED_CLASS,
    STATEFUL_EVENTS,
    EncounterState,
    Fact,
    MovementConflict,
    ParsedMovement,
    code_token,
    local_date,
    project,
)
from services.admissions_smr.domain.pseudonym import pseudonym
from services.admissions_smr.models import Bed, BedPool, EdVisit, Group, Movement, Site, Stay

LEAVE_REASON = "Absence provisoire (lit conservé)"
REUSED_ID = (
    "MSH-10 réutilisé avec un contenu différent",
    "Mouvement déjà reçu avec un contenu différent (même identifiant, même action)",
)
PATIENT_MISMATCH = (
    "Patient (PID-3) différent de celui déjà enregistré pour cette venue (PV1-19) : "
    "vérifiez l'identifiant et son domaine"
)
NEEDS_UNIT = frozenset({"A01", "A02", "A06"})


@dataclass(frozen=True)
class ApplyResult:
    status: str  # applied | duplicate | ignored | rejected
    ack_code: Literal["AA", "AE"]
    message: str
    movement_id: int | None = None
    hl7_code: int = 0
    location: str = ""  # ERR-2, when the error points at one field


@dataclass(frozen=True)
class Location:
    site_id: int | None = None
    pool_id: int | None = None
    bed_id: int | None = None
    warning: str | None = None


def apply_movement(
    session: Session,
    group: Group,
    parsed: ParsedMovement,
    now: datetime,
    *,
    secret: str,
    zone: ZoneInfo,
    source: str = "hl7",
    max_past: timedelta = timedelta(days=400),
    max_future: timedelta = timedelta(days=1),
) -> ApplyResult:
    existing = _by_control_id(session, group.id, parsed.source_system, parsed.control_id)
    if existing is not None and existing.status != "rejected":
        return _resent(session, group, parsed, existing, now, source)

    encounter, patient = references(secret, group.id, parsed)
    row = existing or Movement(
        group_id=group.id,
        source_system=parsed.source_system,
        message_control_id=parsed.control_id,
    )
    row.movement_ref = parsed.movement_ref
    row.event, row.action = parsed.event, parsed.action
    in_window = now - max_past <= parsed.occurred_at <= now + max_future
    row.occurred_at = parsed.occurred_at if in_window else now  # never store an odd date
    row.encounter_ref, row.patient_ref = encounter, patient
    row.message_digest, row.received_at = parsed.digest, now
    row.site_id = row.pool_id = row.bed_id = None
    row.status, row.error = "rejected", None  # until the outcome is known
    if existing is None:
        # Claim the control id first: a concurrent request with the same MSH-10 that
        # committed after our lookup makes this insert fail, never the movement (T-17).
        try:
            with session.begin_nested():
                session.add(row)
                session.flush()
        except IntegrityError:
            winner = _by_control_id(session, group.id, parsed.source_system, parsed.control_id)
            if winner is None:
                raise
            return _resent(session, group, parsed, winner, now, source)

    def record(status: str, error: str | None = None) -> Movement:
        row.status, row.error = status, error
        session.add(row)
        session.flush()
        return row

    if not in_window:
        days, hours = max_past.days, round(max_future.total_seconds() / 3600)
        error = (
            f"Date du mouvement hors de la plage acceptée ({days} jours avant, "
            f"{hours} h après la réception)"
        )
        record("rejected", error)
        return ApplyResult("rejected", "AE", error, row.id, 207)
    if (
        not parsed.supported
        or (parsed.event == "A07" and parsed.action == "INSERT")
        or (parsed.event == "A04" and parsed.patient_class != ED_CLASS)
    ):
        record("ignored", "Événement non utilisé pour la gestion des lits")
        return ApplyResult("ignored", "AA", "Événement reçu, non utilisé", row.id)
    if _other_patient(session, row):
        record("rejected", PATIENT_MISMATCH)
        return ApplyResult("rejected", "AE", PATIENT_MISMATCH, row.id, 207, "PID^1^3")
    if parsed.action == "INSERT" and parsed.movement_ref and _already_applied(session, row):
        record("duplicate", "Mouvement déjà reçu sous un autre identifiant de message")
        return ApplyResult("duplicate", "AA", "Mouvement déjà reçu, sans effet", row.id)

    try:
        with session.begin_nested():
            warnings = _apply(session, group, parsed, row, now, zone, source)
    except MovementConflict as exc:
        record("rejected", str(exc))
        return ApplyResult("rejected", "AE", str(exc), row.id, 207)
    status = "ignored" if row.status == "ignored" else "applied"
    record(status, "; ".join(warnings) or None)
    message = "Mouvement appliqué" + (f" ({'; '.join(warnings)})" if warnings else "")
    return ApplyResult(status, "AA", message, row.id)


def _by_control_id(
    session: Session, group_id: int, source_system: str, control_id: str
) -> Movement | None:
    return session.scalar(
        select(Movement).where(
            Movement.group_id == group_id,
            Movement.source_system == source_system,
            Movement.message_control_id == control_id,
        )
    )


def _resent(
    session: Session,
    group: Group,
    parsed: ParsedMovement,
    existing: Movement,
    now: datetime,
    source: str,
) -> ApplyResult:
    """Same control id as a message already handled: a resend only if the content is the
    same (REVIEW S-H1); otherwise refuse it rather than lose the movement silently."""
    if existing.message_digest == parsed.digest:
        return ApplyResult("duplicate", "AA", "Message déjà reçu, sans effet", existing.id)
    error = REUSED_ID[source == "agent"]
    row = record_rejection(
        session,
        group,
        parsed.source_system,
        parsed.control_id,
        parsed.event,
        error,
        now,
        parsed.digest,
    )
    return ApplyResult("rejected", "AE", error, row.id if row else None, 207, "MSH^1^10")


def references(secret: str, group_id: int, parsed: ParsedMovement) -> tuple[str, str]:
    """(encounter, patient) pseudonyms; the domain is the assigning authority, else the
    sending system (REVIEW S-H2)."""
    nda_domain = parsed.encounter_domain or parsed.source_system
    ipp_domain = parsed.patient_domain or parsed.source_system
    encounter = parsed.encounter_id and pseudonym(
        secret, group_id, "nda", nda_domain, parsed.encounter_id
    )
    patient = parsed.patient_id and pseudonym(
        secret, group_id, "ipp", ipp_domain, parsed.patient_id
    )
    return encounter, patient


def _other_patient(session: Session, row: Movement) -> bool:
    """The encounter is already recorded for another patient (never say which)."""
    if not row.encounter_ref or not row.patient_ref:
        return False
    known = session.scalar(
        select(Movement.patient_ref)
        .where(
            Movement.group_id == row.group_id,
            Movement.encounter_ref == row.encounter_ref,
            Movement.status.in_(("applied", "cancelled")),
            Movement.patient_ref != "",
        )
        .limit(1)
    )
    return known is not None and known != row.patient_ref


def _already_applied(session: Session, row: Movement) -> bool:
    return (
        session.scalar(
            select(Movement.id).where(
                Movement.group_id == row.group_id,
                Movement.source_system == row.source_system,
                Movement.movement_ref == row.movement_ref,
                Movement.event == row.event,
                Movement.action == "INSERT",
                Movement.status.in_(("applied", "cancelled", "ignored")),
            )
        )
        is not None
    )


def _effective(session: Session, group_id: int, encounter: str) -> list[Movement]:
    return list(
        session.scalars(
            select(Movement)
            .where(
                Movement.group_id == group_id,
                Movement.encounter_ref == encounter,
                Movement.status == "applied",
                Movement.action == "INSERT",
                Movement.event.in_(STATEFUL_EVENTS),
            )
            .order_by(Movement.id)
        )
    )


def _fact(m: Movement) -> Fact:
    return Fact(m.id, m.event, m.occurred_at, m.site_id, m.pool_id, m.bed_id)


def _apply(
    session: Session,
    group: Group,
    parsed: ParsedMovement,
    row: Movement,
    now: datetime,
    zone: ZoneInfo,
    source: str,
) -> list[str]:
    history = _effective(session, group.id, row.encounter_ref)
    facts = [_fact(m) for m in history]
    cancel = False
    warnings: list[str] = []
    if parsed.action == "INSERT":
        if parsed.event in ("A03", "A21", "A22"):
            current = project(facts, _ed_pools(session, group.id))
            here = current.stay if current.stay and not current.stay.discharged_at else None
            if here:
                row.site_id, row.pool_id, row.bed_id = here.site_id, here.pool_id, here.bed_id
            elif current.ed:
                row.site_id = current.ed.site_id
        else:
            loc = resolve_location(session, group.id, parsed)
            row.site_id, row.pool_id, row.bed_id = loc.site_id, loc.pool_id, loc.bed_id
            if loc.warning:
                warnings.append(loc.warning)
        facts.append(Fact(2**62, parsed.event, parsed.occurred_at, *_loc(row)))
    elif parsed.action == "CANCEL":
        target = _cancel_target(session, row, parsed)
        if target.status == "ignored":
            target.status = "cancelled"
            row.status = "ignored"
            return []
        if not history or history[-1].id != target.id:
            raise MovementConflict(
                "Seul le dernier mouvement de la venue peut être annulé (mouvements historiques "
                "non pris en charge)"
            )
        facts = [f for f in facts if f.id != target.id]
        row.site_id, row.pool_id, row.bed_id = _loc(target)
        target.status = "cancelled"
        cancel = True
    else:  # UPDATE (Z99)
        corrected = next(
            (
                m
                for m in history
                if m.movement_ref == parsed.movement_ref and m.source_system == row.source_system
            ),
            None,
        )
        if corrected is None:
            raise MovementConflict("Mouvement à corriger introuvable (ZBE-1)")
        if parsed.original_event and parsed.original_event != corrected.event:
            raise MovementConflict(
                f"ZBE-6 ne correspond pas au mouvement corrigé ({corrected.event})"
            )
        corrected.occurred_at = parsed.occurred_at
        if parsed.uf_code and corrected.event not in ("A03", "A21", "A22"):
            loc = resolve_location(session, group.id, replace(parsed, event=corrected.event))
            corrected.site_id, corrected.pool_id, corrected.bed_id = (
                loc.site_id,
                loc.pool_id,
                loc.bed_id,
            )
            if loc.warning:
                warnings.append(loc.warning)
        row.site_id, row.pool_id, row.bed_id = _loc(corrected)
        facts = [_fact(m) for m in history]
        cancel = True  # a corrected bed was never really used: free, not to clean
    state = project(facts, _ed_pools(session, group.id))
    warnings += _reconcile(session, group, row, state, parsed, now, zone, source, cancel)
    return warnings


def _loc(m: Movement) -> tuple[int | None, int | None, int | None]:
    return m.site_id, m.pool_id, m.bed_id


def _cancel_target(session: Session, row: Movement, parsed: ParsedMovement) -> Movement:
    query = select(Movement).where(
        Movement.group_id == row.group_id,
        Movement.encounter_ref == row.encounter_ref,
        Movement.event.in_(CANCELS[parsed.event]),
        Movement.action == "INSERT",
        Movement.status.in_(("applied", "ignored")),
    )
    if parsed.movement_ref:
        query = query.where(
            Movement.source_system == row.source_system,
            Movement.movement_ref == parsed.movement_ref,
        )
    target = session.scalar(query.order_by(Movement.id.desc()))
    if target is None:
        raise MovementConflict("Mouvement à annuler introuvable pour cette venue")
    return target


def _ed_pools(session: Session, group_id: int) -> frozenset[int]:
    return frozenset(
        session.scalars(
            select(BedPool.id)
            .join(Site, Site.id == BedPool.site_id)
            .where(Site.group_id == group_id, BedPool.unit_type == "urgences")
        )
    )


def resolve_location(session: Session, group_id: int, parsed: ParsedMovement) -> Location:
    """Site from the FINESS (or the only site, or the UF), unit from the UF, bed from labels."""
    sites = list(session.scalars(select(Site).where(Site.group_id == group_id)))
    site: Site | None = None
    if parsed.facility:
        site = next((s for s in sites if s.finess == parsed.facility), None)
        if site is None:
            raise MovementConflict(f"FINESS {code_token(parsed.facility)} inconnu dans ce groupe")
    elif len(sites) == 1:
        site = sites[0]
    pool: BedPool | None = None
    uf = " ".join(("UF", code_token(parsed.uf_code or ""))).strip()  # never a raw value
    if parsed.uf_code:
        candidates = list(
            session.scalars(
                select(BedPool).where(
                    BedPool.site_id.in_([site.id] if site else [s.id for s in sites]),
                    BedPool.uf_code == parsed.uf_code,
                )
            )
        )
        if len(candidates) > 1:
            raise MovementConflict(f"{uf} ambiguë : précisez le FINESS (PV1-3)")
        if candidates:
            pool = candidates[0]
            site = next(s for s in sites if s.id == pool.site_id)
    if pool is None and parsed.event in NEEDS_UNIT:
        raise MovementConflict(
            f"{uf} inconnue : renseignez-la sur l'unité dans HospitalOS"
            if parsed.uf_code
            else "UF manquante (PV1-3)"
        )
    if site is None:
        raise MovementConflict("Site introuvable : FINESS ou UF à renseigner")
    bed_id, warning = None, None
    labels = [x for x in (parsed.bed, (parsed.room or "") + (parsed.bed or ""), parsed.room) if x]
    if labels and pool is not None and pool.unit_type != "urgences":
        bed = session.scalar(
            select(Bed).where(Bed.site_id == site.id, Bed.label.in_(labels), Bed.active)
        )
        if bed is None:
            label = code_token(parsed.bed or parsed.room or "")
            warning = f"Lit {label} inconnu (PV1-3) : séjour enregistré sans lit".replace("  ", " ")
        else:
            bed_id = bed.id
    return Location(site.id, pool.id if pool else None, bed_id, warning)


def _reconcile(
    session: Session,
    group: Group,
    row: Movement,
    state: EncounterState,
    parsed: ParsedMovement,
    now: datetime,
    zone: ZoneInfo,
    source: str,
    cancel: bool,
) -> list[str]:
    """Make ``ed_visits``, ``stays`` and ``beds`` show ``state`` for this encounter."""
    warnings: list[str] = []
    encounter = row.encounter_ref
    visit = session.scalar(
        select(EdVisit).where(EdVisit.group_id == group.id, EdVisit.encounter_ref == encounter)
    )
    if state.ed is None:
        if visit is not None:
            session.delete(visit)
    else:
        ed = state.ed
        if visit is None:
            visit = EdVisit(group_id=group.id, encounter_ref=encounter, source=source)
            session.add(visit)
        if ed.left_at is None:
            outcome = None
        elif ed.left_by in ("A01", "A06"):
            outcome = "hospitalise"
        elif visit.left_at is not None and visit.outcome:
            outcome = visit.outcome  # already known from the discharge message
        else:
            outcome = parsed.outcome or "sortie"
        visit.site_id, visit.patient_ref = ed.site_id, row.patient_ref or visit.patient_ref
        visit.arrived_at, visit.admit_decision_at = ed.arrived_at, ed.admit_decision_at
        visit.target_pool_id, visit.left_at, visit.outcome = ed.target_pool_id, ed.left_at, outcome

    stay = session.scalar(
        select(Stay)
        .where(Stay.group_id == group.id, Stay.encounter_ref == encounter)
        .order_by(Stay.id.desc())
    )
    target = state.stay
    if target is None:
        if stay is not None:
            _release(session, stay, cancel=True)
            session.flush()
            session.delete(stay)
        session.flush()
        return warnings
    pool = session.get(BedPool, target.pool_id)
    assert pool is not None
    admission_date = local_date(target.unit_entry_at, zone)
    if stay is None:
        stay = Stay(
            group_id=group.id,
            encounter_ref=encounter,
            source=source,
            created_at=now,
            admission_mode="urgences" if target.from_ed else None,
        )
        session.add(stay)
    stay.site_id, stay.mention = target.site_id, pool.mention
    stay.patient_ref = row.patient_ref or stay.patient_ref
    stay.admission_date, stay.admitted_at = admission_date, target.admitted_at
    stay.discharged_at = target.discharged_at
    stay.discharge_date = local_date(target.discharged_at, zone) if target.discharged_at else None
    if parsed.sex:
        stay.patient_sex = parsed.sex
    if parsed.age is not None:
        stay.patient_age = parsed.age
    stay.updated_at = now
    session.flush()

    wanted = None if target.discharged_at else target.bed_id
    if stay.bed_id != wanted:
        _release(session, stay, cancel=cancel)
    if wanted is not None:
        bed = session.get(Bed, wanted)
        assert bed is not None
        if bed.stay_id not in (None, stay.id):
            warnings.append(f"Lit {bed.label} déjà occupé : séjour enregistré sans lit")
            wanted = None
        else:
            if bed.stay_id is None and bed.status == "bloque":
                warnings.append(f"Lit {bed.label} signalé bloqué")
            warnings += _sex_warnings(session, bed, stay)
            bed.stay_id, bed.status = stay.id, "occupe"
            bed.status_reason = LEAVE_REASON if target.on_leave else None
            bed.updated_at = now
    stay.bed_id = wanted
    session.flush()
    return warnings


def _release(session: Session, stay: Stay, *, cancel: bool) -> None:
    """The stay leaves its bed: to clean after a real move, free again after a cancellation."""
    if stay.bed_id is None:
        return
    bed = session.get(Bed, stay.bed_id)
    if bed is not None and bed.stay_id == stay.id:
        bed.stay_id = None
        bed.status = "libre" if cancel else "a_nettoyer"
        bed.status_reason = None
    stay.bed_id = None


def _sex_warnings(session: Session, bed: Bed, stay: Stay) -> list[str]:
    """The movement is applied anyway (the patient is there); the conflict is flagged."""
    sex = stay.patient_sex
    if sex not in ("F", "M"):
        return []
    out = []
    if bed.sex_constraint in ("F", "M") and bed.sex_constraint != sex:
        who = "femmes" if bed.sex_constraint == "F" else "hommes"
        out.append(f"Lit {bed.label} réservé aux {who}")
    roommates = session.scalars(
        select(Stay.patient_sex)
        .join(Bed, Bed.stay_id == Stay.id)
        .where(Bed.site_id == bed.site_id, Bed.room == bed.room, Bed.id != bed.id)
    )
    if any(s in ("F", "M") and s != sex for s in roommates):
        out.append(f"Chambre {bed.room} partagée avec un patient de l'autre sexe")
    return out


def record_rejection(
    session: Session,
    group: Group,
    source_system: str,
    control_id: str,
    event: str,
    error: str,
    now: datetime,
    message_digest: str,
) -> Movement | None:
    """Journal a refused message (keeps the rejection rate honest).

    A control id already accepted with the same digest is left untouched (a resend). With
    another digest the control id was reused: the rejection gets its own line, under the
    control id suffixed with the start of the digest (the original line stays as it was).
    """
    row = _by_control_id(session, group.id, source_system, control_id)
    if row is not None and row.status != "rejected":
        if row.message_digest == message_digest:
            return None
        control_id = f"{control_id[:51]}~{message_digest[:8]}"
        row = _by_control_id(session, group.id, source_system, control_id)
    row = row or Movement(
        group_id=group.id, source_system=source_system, message_control_id=control_id
    )
    row.event, row.action, row.occurred_at = event[:7] or "?", "INSERT", now
    row.movement_ref = row.site_id = row.pool_id = row.bed_id = None
    row.encounter_ref = row.patient_ref = ""
    row.status, row.error = "rejected", error
    row.message_digest, row.received_at = message_digest, now
    session.add(row)
    session.flush()
    return row
