"""HL7 v2.5 IHE PAM France (ITI-31) patient movements: parse, acknowledge, project.

Pure functions, no I/O. Sources and assumptions: ``docs/liscop/HL7_PAM.md``.

* ``decode`` / ``parse`` read one ER7 message (MLLP framing tolerated) into a typed
  ``ParsedMovement``. Clear identifiers (IPP, NDA) stay in memory only (``repr=False``);
  the birth date is used to compute the age in years, then dropped.
* ``build_ack`` writes the HL7 v2.5 original-mode acknowledgement (MSA, and ERR on error).
* ``project`` replays the effective movements of one encounter into the state the
  ``stays`` / ``ed_visits`` / ``beds`` tables must show. Applying, cancelling and correcting
  a movement all go through it, so the three always agree.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

import hl7  # type: ignore[import-untyped]

DEFAULT_MAX_BYTES = 64 * 1024
ENCODING = "^~\\&"

# Events that change where a patient is (ITI-31, French extension §2.2).
STATEFUL_EVENTS = frozenset({"A01", "A02", "A03", "A04", "A06", "A21", "A22"})
# Cancellation event -> events it cancels (§2.2 and §5.3.5: A07 cancels A06).
CANCELS: dict[str, tuple[str, ...]] = {
    "A11": ("A01", "A04"),
    "A12": ("A02",),
    "A13": ("A03",),
    "A52": ("A21",),
    "A53": ("A22",),
    "A07": ("A06",),
}
# Event -> its cancellation event (used by the structured JSON path).
CANCEL_EVENT = {"A01": "A11", "A04": "A11", "A02": "A12", "A03": "A13", "A21": "A52"}
CANCEL_EVENT |= {"A22": "A53", "A06": "A07"}
SUPPORTED_EVENTS = STATEFUL_EVENTS | frozenset(CANCELS) | {"Z99"}
ED_CLASS = "E"  # PV1-2: urgences (§6.10.1)

EVENT_LABELS: dict[str, str] = {
    "A01": "Admission",
    "A02": "Mutation",
    "A03": "Sortie",
    "A04": "Passage aux urgences ou consultation",
    "A06": "Hospitalisation depuis les urgences",
    "A07": "Retour en externe ou urgences",
    "A11": "Annulation d'admission",
    "A12": "Annulation de mutation",
    "A13": "Annulation de sortie",
    "A21": "Absence provisoire",
    "A22": "Retour d'absence provisoire",
    "A52": "Annulation d'absence provisoire",
    "A53": "Annulation de retour d'absence",
    "Z99": "Correction de mouvement",
}

# PV1-36 "mode de sortie" (PMSI codes, assumption documented in HL7_PAM.md) -> ED outcome.
ED_OUTCOME_BY_DISCHARGE_MODE = {"6": "hospitalise", "7": "transfert", "8": "sortie", "9": "deces"}
_HL7_TS = re.compile(
    r"^(\d{4})(\d{2})(\d{2})(?:(\d{2})(\d{2})(?:(\d{2})(?:\.\d{1,4})?)?)?([+-]\d{4})?$"
)
_TRIGGER = re.compile(r"^[A-Z]\d{2}$")
_FINESS = re.compile(r"^\d{2}[0-9AB]\d{6}$")
_CODE = re.compile(r"^(?=.*\d)[A-Z0-9]{1,12}$")
# C0 control characters, segment separator excepted (after decoding and normalisation).
_CONTROL = re.compile(r"[\x00-\x0c\x0e-\x1f]")
# PID-3 identifier types that are national identifiers (INS, NIR): never used, never kept.
_NATIONAL_ID_TYPES = frozenset({"INS", "INS-C", "INS-NIR", "INS-NIA", "NH", "SS", "NNFRA"})


class Hl7Error(Exception):
    """A message we refuse. ``ack_code``: AR (cannot be processed) or AE (content error)."""

    def __init__(
        self,
        ack_code: Literal["AE", "AR"],
        message: str,
        hl7_code: int = 207,
        location: str = "",
        header: Header | None = None,
    ) -> None:
        super().__init__(message)
        self.ack_code = ack_code
        self.message = message
        self.hl7_code = hl7_code  # HL7 table 0357
        self.location = location
        self.header = header


@dataclass(frozen=True)
class Header:
    control_id: str
    sending_app: str
    sending_facility: str
    receiving_app: str
    receiving_facility: str
    message_type: str
    trigger: str
    version: str

    @property
    def source_system(self) -> str:
        return f"{self.sending_app}/{self.sending_facility}"[:60]


@dataclass(frozen=True)
class ParsedMovement:
    source_system: str
    control_id: str
    event: str
    action: str  # INSERT | UPDATE | CANCEL
    movement_ref: str | None
    occurred_at: datetime
    patient_class: str | None = None
    uf_code: str | None = None
    room: str | None = None
    bed: str | None = None
    facility: str | None = None  # FINESS
    sex: str | None = None  # F | M | U
    age: int | None = None
    outcome: str | None = None  # emergency department outcome on A03
    original_event: str | None = None  # ZBE-6, for Z99
    historic: bool = False  # ZBE-5
    digest: str = ""  # keyed digest, set by the caller (domain.pseudonym.keyed_digest)
    # Identification domains (assigning authorities PV1-19.4 / PID-3.4), may be empty.
    encounter_domain: str = ""
    patient_domain: str = ""
    # Clear identifiers: memory only, pseudonymised before anything is written.
    encounter_id: str = field(default="", repr=False)
    patient_id: str = field(default="", repr=False)
    header: Header | None = field(default=None, repr=False, compare=False)

    @property
    def supported(self) -> bool:
        return self.event in SUPPORTED_EVENTS


# --- parsing ---------------------------------------------------------------------------------


def decode(raw: bytes, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
    """Bytes -> one ER7 message with ``\\r`` separators. MLLP framing is stripped."""
    if len(raw) > max_bytes:
        raise Hl7Error("AR", f"Message trop volumineux (plus de {max_bytes} octets)", 100)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")  # many French ADT feeds are ISO 8859-1
    text = text.strip().lstrip("\x0b").rstrip("\x1c\r\n").strip()
    text = text.replace("\r\n", "\r").replace("\n", "\r")
    if _CONTROL.search(text):  # NUL and friends: refused before anything is read or stored
        raise Hl7Error("AR", "Caractère de contrôle interdit dans le message", 100)
    return "\r".join(line for line in text.split("\r") if line.strip())


def code_token(value: str) -> str:
    """A sender value echoed in an ACK or the journal only if it looks like a code
    (``[A-Z0-9]``, at most 12, with a digit): never a name typed in the wrong field."""
    return value if _CODE.match(value) else ""


def _get(segment: Any, field_num: int, component: int = 1, sub: int = 1, rep: int = 1) -> str:
    try:
        value = segment.extract_field(1, field_num, rep, component, sub)
    except (IndexError, KeyError, AttributeError, TypeError):
        return ""
    return str(value).strip()


def _segment(message: Any, name: str) -> Any | None:
    try:
        return message.segment(name)
    except (KeyError, IndexError):
        return None


def _repetitions(segment: Any, field_num: int) -> int:
    try:
        return len(segment(field_num)) if field_num < len(segment) else 0
    except (IndexError, TypeError):
        return 0


def parse_ts(value: str, zone: ZoneInfo) -> datetime | None:
    """HL7 TS (YYYYMMDD[HHMM[SS[.S]]][+/-ZZZZ]); no offset means local time of ``zone``."""
    match = _HL7_TS.match(value.strip())
    if not match:
        return None
    y, mo, d, h, mi, s, offset = match.groups()
    try:
        naive = datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(s or 0))
    except ValueError:
        return None
    try:
        if offset:
            sign = 1 if offset[0] == "+" else -1
            minutes = int(offset[1:3]) * 60 + int(offset[3:5])
            stamp = naive.replace(tzinfo=timezone(sign * timedelta(minutes=minutes)))
        else:
            stamp = naive.replace(tzinfo=zone)
        stamp.astimezone(UTC)  # must be representable in UTC (stored as UTC)
    except (ValueError, OverflowError):
        return None
    return stamp


def _age(birth: str, at: datetime, zone: ZoneInfo) -> int | None:
    born = parse_ts(birth[:8], zone) if len(birth) >= 8 else None
    if born is None:
        return None
    day = at.astimezone(zone).date()
    years = day.year - born.year - ((day.month, day.day) < (born.month, born.day))
    return years if 0 <= years <= 130 else None


def parse_header(text: str) -> tuple[Any, Header]:
    if not text.startswith("MSH|" + ENCODING + "|"):
        raise Hl7Error("AR", "Segment MSH absent ou caractères d'encodage non standard", 100)
    try:
        message = hl7.parse(text)
        msh = message.segment("MSH")
    except Exception as exc:  # noqa: BLE001 - malformed input must never crash the API
        raise Hl7Error("AR", "Message HL7 illisible", 100) from exc
    header = Header(
        control_id=_get(msh, 10)[:60],
        sending_app=_get(msh, 3)[:40],
        sending_facility=_get(msh, 4)[:40],
        receiving_app=_get(msh, 5)[:40],
        receiving_facility=_get(msh, 6)[:40],
        message_type=_get(msh, 9, 1),
        trigger=_get(msh, 9, 2),
        version=_get(msh, 12),
    )
    if not header.control_id:
        raise Hl7Error("AR", "MSH-10 (identifiant du message) manquant", 101, "MSH^1^10")
    if not header.sending_app:
        raise Hl7Error("AR", "MSH-3 (application émettrice) manquant", 101, "MSH^1^3", header)
    if not header.version.startswith("2."):
        raise Hl7Error("AR", "Version HL7 non prise en charge", 203, "MSH^1^12", header)
    if header.message_type != "ADT" or not _TRIGGER.match(header.trigger):
        raise Hl7Error("AR", "Type de message non pris en charge (MSH-9)", 200, "MSH^1^9", header)
    return message, header


def parse(raw: bytes, zone: ZoneInfo, max_bytes: int = DEFAULT_MAX_BYTES) -> ParsedMovement:
    """Validate and read one ADT message. Raises ``Hl7Error`` (with the header when known)."""
    message, header = parse_header(decode(raw, max_bytes))
    try:
        return replace(_movement(message, header, zone), header=header)
    except Hl7Error as exc:
        exc.header = header
        raise


def _authority(segment: Any, field_num: int, rep: int = 1) -> str:
    """CX-4 assigning authority (HD): universal id (HD-2), else namespace id (HD-1)."""
    return (_get(segment, field_num, 4, 2, rep) or _get(segment, field_num, 4, 1, rep))[:60]


def _movement(message: Any, header: Header, zone: ZoneInfo) -> ParsedMovement:
    event = header.trigger
    evn, pid, pv1, zbe = (_segment(message, s) for s in ("EVN", "PID", "PV1", "ZBE"))
    msh = message.segment("MSH")
    occurred = None
    sources = (("ZBE", zbe, 2), ("EVN", evn, 6), ("EVN", evn, 2), ("MSH", msh, 7))
    for name, segment, number in sources:
        if segment is not None and (stamp := _get(segment, number)):
            occurred = parse_ts(stamp, zone)
            if occurred is None:
                where = f"{name}^1^{number}"
                raise Hl7Error("AE", f"Date invalide ({name}-{number})", 102, where)
            break
    if occurred is None:
        raise Hl7Error("AE", "Date du mouvement absente (ZBE-2, EVN-6, EVN-2, MSH-7)", 101)
    base = ParsedMovement(header.source_system, header.control_id, event, "INSERT", None, occurred)
    if event not in SUPPORTED_EVENTS:
        return base  # recorded as ignored, nothing else is read
    if pid is None or pv1 is None:
        raise Hl7Error("AE", "Segments PID et PV1 obligatoires", 100)

    action = _get(zbe, 4).upper() if zbe is not None else ""
    expected = "CANCEL" if event in CANCELS else "UPDATE" if event == "Z99" else "INSERT"
    if event == "A07" and action != "CANCEL":
        expected = "INSERT"  # an A07 that is not a cancellation: hospitalised -> outpatient
    action = action or expected
    if action != expected:
        raise Hl7Error("AE", f"ZBE-4 incohérent avec l'événement {event}", 103, "ZBE^1^4")
    historic = (_get(zbe, 5).upper() == "Y") if zbe is not None else False
    if historic and event != "Z99":  # REVIEW T-4: only a correction may touch the past
        raise Hl7Error("AE", "Mouvement historique (ZBE-5 = Y) non pris en charge", 103, "ZBE^1^5")

    patient_id = patient_domain = ""
    for rep in range(1, _repetitions(pid, 3) + 1):
        kind = _get(pid, 3, 5, rep=rep).upper()
        if kind in _NATIONAL_ID_TYPES:
            continue
        value = _get(pid, 3, 1, rep=rep)
        if value and (kind == "PI" or not patient_id):
            patient_id, patient_domain = value, _authority(pid, 3, rep)
    encounter_id = _get(pv1, 19)
    if not patient_id:
        raise Hl7Error("AE", "PID-3 : identifiant patient (IPP) manquant", 101, "PID^1^3")
    if not encounter_id:
        raise Hl7Error("AE", "PV1-19 : numéro de venue (NDA) manquant", 101, "PV1^1^19")

    facility = next(
        (v for s in (1, 2) if _FINESS.match(v := _get(pv1, 3, 4, s))),
        None,
    )
    sex = _get(pid, 8).upper()[:1]
    uf = _get(pv1, 3, 1) or (_get(zbe, 7, 10) if zbe is not None else "")
    original = _get(zbe, 6).upper() if zbe is not None else ""
    return ParsedMovement(
        source_system=header.source_system,
        control_id=header.control_id,
        event=event,
        action=action,
        movement_ref=(_get(zbe, 1) if zbe is not None else "")[:60] or None,
        occurred_at=occurred,
        patient_class=_get(pv1, 2).upper()[:1] or None,
        uf_code=uf[:20] or None,
        room=_get(pv1, 3, 2)[:40] or None,
        bed=_get(pv1, 3, 3)[:40] or None,
        facility=facility,
        sex=sex if sex in ("F", "M") else "U" if sex else None,
        age=_age(_get(pid, 7), occurred, zone),
        outcome=ED_OUTCOME_BY_DISCHARGE_MODE.get(_get(pv1, 36)),
        original_event=original or None,
        historic=historic,
        encounter_domain=_authority(pv1, 19),
        patient_domain=patient_domain,
        encounter_id=encounter_id[:64],
        patient_id=patient_id[:64],
    )


# --- acknowledgement ------------------------------------------------------------------------


def _escape(text: str) -> str:
    out = text.replace("\\", "\\E\\").replace("|", "\\F\\").replace("^", "\\S\\")
    out = out.replace("&", "\\T\\").replace("~", "\\R\\")
    return " ".join(out.split())  # no segment separator can leak in


def build_ack(
    header: Header | None,
    code: Literal["AA", "AE", "AR"],
    text: str,
    now: datetime,
    ack_control_id: str,
    hl7_code: int = 0,
    location: str = "",
) -> str:
    """HL7 v2.5 original-mode ACK (chapter 2): MSH, MSA, and ERR when not accepted."""
    h = header or Header("", "", "", "", "", "", "", "2.5")
    msh = "|".join(
        [
            "MSH",
            ENCODING,
            _escape(h.receiving_app or "HOSPITALOS"),
            _escape(h.receiving_facility or "HOSPITALOS"),
            _escape(h.sending_app),
            _escape(h.sending_facility),
            now.strftime("%Y%m%d%H%M%S%z"),
            "",
            f"ACK^{_escape(h.trigger)}^ACK",
            _escape(ack_control_id),
            "P",
            "2.5",
        ]
    )
    segments = [msh, "|".join(["MSA", code, _escape(h.control_id), _escape(text[:80])])]
    if code != "AA":
        severity = "E"
        where = "^".join(_escape(part) for part in location.split("^"))  # ERL components
        segments.append(f"ERR||{where}|{hl7_code}^{_escape(text)}^HL70357|{severity}")
    return "\r".join(segments) + "\r"


# --- projection -------------------------------------------------------------------------------


class MovementConflict(Exception):
    """The movement does not fit the encounter's history (French message for the sender)."""


@dataclass(frozen=True)
class Fact:
    """One effective movement of an encounter, as recorded in the ``movements`` journal."""

    id: int
    event: str
    occurred_at: datetime
    site_id: int | None
    pool_id: int | None
    bed_id: int | None


@dataclass
class EdState:
    site_id: int
    arrived_at: datetime
    admit_decision_at: datetime | None = None
    target_pool_id: int | None = None
    left_at: datetime | None = None
    left_by: str | None = None  # event that closed the visit


@dataclass
class StayState:
    site_id: int
    pool_id: int
    bed_id: int | None
    admitted_at: datetime
    unit_entry_at: datetime  # entry into the current unit (stays.admission_date)
    from_ed: bool
    discharged_at: datetime | None = None
    on_leave: bool = False


@dataclass
class EncounterState:
    ed: EdState | None = None
    stay: StayState | None = None


def project(facts: Sequence[Fact], ed_pools: frozenset[int]) -> EncounterState:
    """Replay effective movements in received order. Raises ``MovementConflict``."""
    state = EncounterState()
    for f in facts:
        ed, stay = state.ed, state.stay
        open_stay = stay is not None and stay.discharged_at is None
        open_ed = ed is not None and ed.left_at is None
        if f.event == "A04":
            if ed is not None:
                raise MovementConflict("Passage aux urgences déjà enregistré pour cette venue")
            if f.site_id is None:
                raise MovementConflict("Site du passage aux urgences introuvable")
            state.ed = EdState(f.site_id, f.occurred_at)
        elif f.event in ("A01", "A06"):
            if stay is not None:
                raise MovementConflict("Cette venue a déjà un séjour d'hospitalisation")
            if f.site_id is None or f.pool_id is None:
                raise MovementConflict("Unité d'hospitalisation introuvable")
            if ed is not None and open_ed:
                ed.left_at, ed.left_by = f.occurred_at, f.event
                # REVIEW C-1: admitted elsewhere than decided = hosted; keep the decision's
                # target unit (the admission unit only when there was no decision).
                ed.target_pool_id = ed.target_pool_id or f.pool_id
                ed.admit_decision_at = ed.admit_decision_at or f.occurred_at
            from_ed = f.event == "A06" or ed is not None
            state.stay = StayState(
                f.site_id, f.pool_id, f.bed_id, f.occurred_at, f.occurred_at, from_ed
            )
        elif f.event == "A02":
            if stay is not None and open_stay:
                if f.site_id is None or f.pool_id is None:
                    raise MovementConflict("Unité de destination introuvable")
                stay.site_id, stay.pool_id, stay.bed_id = f.site_id, f.pool_id, f.bed_id
                stay.unit_entry_at, stay.on_leave = f.occurred_at, False
            elif ed is not None and open_ed:
                # Assumption (HL7_PAM.md): a move of an ED visit to a ward unit is the
                # admission decision; the patient stays in the ED until the A06.
                if f.pool_id is not None and f.pool_id not in ed_pools:
                    ed.admit_decision_at, ed.target_pool_id = f.occurred_at, f.pool_id
            else:
                raise MovementConflict("Mutation sans séjour ni passage en cours")
        elif f.event == "A03":
            if stay is not None and open_stay:
                stay.discharged_at, stay.on_leave = f.occurred_at, False
            elif ed is not None and open_ed:
                ed.left_at, ed.left_by = f.occurred_at, "A03"
            else:
                raise MovementConflict("Sortie sans séjour ni passage en cours")
        elif f.event == "A21":
            if stay is None or not open_stay or stay.on_leave:
                raise MovementConflict("Absence provisoire sans séjour en cours")
            stay.on_leave = True
        elif f.event == "A22":
            if stay is None or not open_stay or not stay.on_leave:
                raise MovementConflict("Retour d'absence sans absence en cours")
            stay.on_leave = False
    return state


def local_date(at: datetime, zone: ZoneInfo) -> date:
    return at.astimezone(zone).date()
