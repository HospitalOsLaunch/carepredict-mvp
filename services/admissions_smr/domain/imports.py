"""CSV parsing and validation for pilot onboarding. Fail-closed: a file with one
invalid row is rejected as a whole, with every error listed by line and column.

Three files are supported (headers are case- and accent-insensitive; ``;`` or
``,`` separators; dates as JJ/MM/AAAA or AAAA-MM-JJ):

* ``lits``     : site, finess, ville, mention, lits_installes, lits_ouverts,
                 chambres_isolement, capacites
* ``sejours``  : site, mention, patient_ref, date_entree, date_sortie_prevue, date_sortie,
                 niveau_soins (1 à 4, facultatif)
* ``demandes`` : source, ref_externe, recue_le, etablissement_adresseur,
                 service_adresseur, patient_ref, age, sexe, mention,
                 categorie_clinique, niveau_soins, isolement, besoins, date_souhaitee
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from services.admissions_smr.vocab import MENTIONS, REQUEST_SOURCES, SPECIAL_NEEDS

TEMPLATES: dict[str, list[str]] = {
    "lits": [
        "site",
        "finess",
        "ville",
        "mention",
        "lits_installes",
        "lits_ouverts",
        "chambres_isolement",
        "capacites",
    ],
    "sejours": [
        "site",
        "mention",
        "patient_ref",
        "date_entree",
        "date_sortie_prevue",
        "date_sortie",
        "niveau_soins",
    ],
    "demandes": [
        "source",
        "ref_externe",
        "recue_le",
        "etablissement_adresseur",
        "service_adresseur",
        "patient_ref",
        "age",
        "sexe",
        "mention",
        "categorie_clinique",
        "niveau_soins",
        "isolement",
        "besoins",
        "date_souhaitee",
    ],
}

REQUIRED: dict[str, set[str]] = {
    "lits": {"site", "mention", "lits_installes", "lits_ouverts"},
    "sejours": {"site", "mention", "patient_ref", "date_entree"},
    "demandes": {"source", "recue_le", "etablissement_adresseur", "patient_ref", "mention"},
}

MAX_ROWS = 50_000

# A French NIR has 13 digits plus a 2-digit key; refuse anything that looks like one.
_NIR_LIKE = re.compile(r"^[12]\s?\d{2}\s?\d{2}\s?(\d{2}|2A|2B)\s?\d{3}\s?\d{3}(\s?\d{2})?$", re.I)
_PATIENT_REF = re.compile(r"^[A-Za-z0-9_\-.]{3,64}$")


@dataclass(frozen=True)
class RowError:
    line: int
    column: str | None
    message: str


@dataclass(frozen=True)
class PoolRow:
    line: int
    site: str
    finess: str | None
    city: str | None
    mention: str
    beds_installed: int
    beds_open: int
    isolation_rooms: int
    capabilities: frozenset[str]


@dataclass(frozen=True)
class StayRow:
    line: int
    site: str
    mention: str
    patient_ref: str
    admission_date: date
    planned_discharge_date: date | None
    discharge_date: date | None
    care_level: int | None = None


@dataclass(frozen=True)
class RequestRow:
    line: int
    source: str
    external_ref: str | None
    received_at: datetime
    referrer_facility: str
    referrer_unit: str | None
    patient_ref: str
    patient_age: int | None
    patient_sex: str | None
    mention: str
    clinical_category: str | None
    care_level: int
    isolation_required: bool
    needs: frozenset[str]
    desired_date: date | None


@dataclass
class ParseResult:
    kind: str
    rows: list[PoolRow | StayRow | RequestRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def normalise_key(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", folded.strip().lower()).strip("_")


def parse_csv(kind: str, text: str, tz: str = "Europe/Paris") -> ParseResult:
    if kind not in TEMPLATES:
        raise ValueError(f"type d'import inconnu : {kind}")
    result = ParseResult(kind=kind)
    text = text.lstrip("﻿")
    if not text.strip():
        result.errors.append(RowError(1, None, "Fichier vide"))
        return result
    first_line = text.splitlines()[0]
    delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if reader.fieldnames is None:
        result.errors.append(RowError(1, None, "En-tête manquant"))
        return result
    headers = [normalise_key(h) for h in reader.fieldnames]
    missing = REQUIRED[kind] - set(headers)
    if missing:
        result.errors.append(
            RowError(1, None, "Colonnes obligatoires manquantes : " + ", ".join(sorted(missing)))
        )
        return result
    unknown = set(headers) - set(TEMPLATES[kind])
    if unknown:
        result.errors.append(
            RowError(1, None, "Colonnes non reconnues : " + ", ".join(sorted(unknown)))
        )
        return result

    zone = ZoneInfo(tz)
    for index, raw in enumerate(reader):
        line = index + 2
        if index >= MAX_ROWS:
            result.errors.append(RowError(line, None, f"Plus de {MAX_ROWS} lignes"))
            break
        row = {normalise_key(k): (v or "").strip() for k, v in raw.items() if k is not None}
        if not any(row.values()):
            continue
        errors: list[RowError] = []
        parsed: PoolRow | StayRow | RequestRow | None
        if kind == "lits":
            parsed = _parse_pool(line, row, errors)
        elif kind == "sejours":
            parsed = _parse_stay(line, row, errors)
        else:
            parsed = _parse_request(line, row, errors, zone)
        if errors:
            result.errors.extend(errors)
        elif parsed is not None:
            result.rows.append(parsed)
    if not result.rows and not result.errors:
        result.errors.append(RowError(2, None, "Aucune ligne de données"))
    return result


def _parse_pool(line: int, row: dict[str, str], errors: list[RowError]) -> PoolRow | None:
    site = _text(row, "site", line, errors, required=True)
    mention = _mention(row, line, errors)
    installed = _int(row, "lits_installes", line, errors, minimum=0, required=True)
    opened = _int(row, "lits_ouverts", line, errors, minimum=0, required=True)
    isolation = _int(row, "chambres_isolement", line, errors, minimum=0) or 0
    finess = row.get("finess") or None
    if finess and not re.fullmatch(r"\d{2}[0-9AB]\d{6}", finess, re.I):
        errors.append(RowError(line, "finess", "FINESS invalide (9 caractères attendus)"))
    capabilities = _needs(row.get("capacites", ""), line, "capacites", errors)
    if installed is not None and opened is not None and opened > installed:
        errors.append(RowError(line, "lits_ouverts", "Plus de lits ouverts que de lits installés"))
    if errors or site is None or mention is None or installed is None or opened is None:
        return None
    return PoolRow(
        line,
        site,
        finess,
        row.get("ville") or None,
        mention,
        installed,
        opened,
        isolation,
        capabilities,
    )


def _parse_stay(line: int, row: dict[str, str], errors: list[RowError]) -> StayRow | None:
    site = _text(row, "site", line, errors, required=True)
    mention = _mention(row, line, errors)
    patient = _patient_ref(row, line, errors)
    admission = _date(row, "date_entree", line, errors, required=True)
    planned = _date(row, "date_sortie_prevue", line, errors)
    discharge = _date(row, "date_sortie", line, errors)
    care = _int(row, "niveau_soins", line, errors, minimum=1, maximum=4)
    if admission and discharge and discharge < admission:
        errors.append(RowError(line, "date_sortie", "Sortie antérieure à l'entrée"))
    if admission and planned and planned < admission:
        errors.append(RowError(line, "date_sortie_prevue", "Sortie prévue antérieure à l'entrée"))
    if errors or site is None or mention is None or patient is None or admission is None:
        return None
    return StayRow(line, site, mention, patient, admission, planned, discharge, care)


def _parse_request(
    line: int, row: dict[str, str], errors: list[RowError], zone: ZoneInfo
) -> RequestRow | None:
    source = normalise_key(row.get("source", ""))
    if source not in REQUEST_SOURCES:
        errors.append(RowError(line, "source", f"Source inconnue : « {row.get('source', '')} »"))
    received = _datetime(row, "recue_le", line, errors, zone)
    referrer = _text(row, "etablissement_adresseur", line, errors, required=True)
    patient = _patient_ref(row, line, errors)
    mention = _mention(row, line, errors)
    age = _int(row, "age", line, errors, minimum=0, maximum=120)
    sex = (row.get("sexe") or "").upper()[:1] or None
    if sex is not None and sex not in {"F", "M", "I"}:
        errors.append(RowError(line, "sexe", "Sexe attendu : F, M ou I"))
    care = _int(row, "niveau_soins", line, errors, minimum=1, maximum=4)
    isolation = _bool(row.get("isolement", ""), line, errors)
    needs = _needs(row.get("besoins", ""), line, "besoins", errors)
    desired = _date(row, "date_souhaitee", line, errors)
    if errors or received is None or referrer is None or patient is None or mention is None:
        return None
    return RequestRow(
        line=line,
        source=source,
        external_ref=row.get("ref_externe") or None,
        received_at=received,
        referrer_facility=referrer,
        referrer_unit=row.get("service_adresseur") or None,
        patient_ref=patient,
        patient_age=age,
        patient_sex=sex,
        mention=mention,
        clinical_category=row.get("categorie_clinique") or None,
        care_level=care or 2,
        isolation_required=isolation,
        needs=needs,
        desired_date=desired,
    )


def _text(
    row: dict[str, str], col: str, line: int, errors: list[RowError], required: bool = False
) -> str | None:
    value = row.get(col, "")
    if not value:
        if required:
            errors.append(RowError(line, col, "Valeur obligatoire"))
        return None
    if len(value) > 200:
        errors.append(RowError(line, col, "Valeur trop longue (200 caractères max.)"))
        return None
    return value


def _mention(row: dict[str, str], line: int, errors: list[RowError]) -> str | None:
    raw = row.get("mention", "")
    key = normalise_key(raw)
    if key in MENTIONS:
        return key
    by_label = {normalise_key(label): code for code, label in MENTIONS.items()}
    if key in by_label:
        return by_label[key]
    errors.append(RowError(line, "mention", f"Mention inconnue : « {raw} »"))
    return None


def _patient_ref(row: dict[str, str], line: int, errors: list[RowError]) -> str | None:
    value = row.get("patient_ref", "")
    if not value:
        errors.append(RowError(line, "patient_ref", "Valeur obligatoire"))
        return None
    if _NIR_LIKE.match(value) or (value.isdigit() and len(value) >= 13):
        errors.append(
            RowError(
                line,
                "patient_ref",
                "Ressemble à un NIR : seule une référence pseudonymisée est acceptée",
            )
        )
        return None
    if not _PATIENT_REF.match(value):
        errors.append(
            RowError(
                line,
                "patient_ref",
                "Référence invalide (3 à 64 caractères : lettres, chiffres, - _ .)",
            )
        )
        return None
    return value


def _int(
    row: dict[str, str],
    col: str,
    line: int,
    errors: list[RowError],
    minimum: int | None = None,
    maximum: int | None = None,
    required: bool = False,
) -> int | None:
    value = row.get(col, "")
    if not value:
        if required:
            errors.append(RowError(line, col, "Valeur obligatoire"))
        return None
    try:
        number = int(value)
    except ValueError:
        errors.append(RowError(line, col, f"Nombre entier attendu : « {value} »"))
        return None
    if (minimum is not None and number < minimum) or (maximum is not None and number > maximum):
        errors.append(RowError(line, col, f"Valeur hors limites : {number}"))
        return None
    return number


def parse_date_text(value: str) -> date:
    value = value.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(value)


def _date(
    row: dict[str, str], col: str, line: int, errors: list[RowError], required: bool = False
) -> date | None:
    value = row.get(col, "")
    if not value:
        if required:
            errors.append(RowError(line, col, "Valeur obligatoire"))
        return None
    try:
        return parse_date_text(value)
    except ValueError:
        errors.append(RowError(line, col, f"Date invalide : « {value} » (JJ/MM/AAAA attendu)"))
        return None


def _datetime(
    row: dict[str, str], col: str, line: int, errors: list[RowError], zone: ZoneInfo
) -> datetime | None:
    value = row.get(col, "")
    if not value:
        errors.append(RowError(line, col, "Valeur obligatoire"))
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=zone).astimezone(UTC)
        except ValueError:
            continue
    try:
        day = parse_date_text(value)
    except ValueError:
        errors.append(RowError(line, col, f"Date/heure invalide : « {value} »"))
        return None
    return datetime.combine(day, time(9, 0), tzinfo=zone).astimezone(UTC)


def _bool(value: str, line: int, errors: list[RowError]) -> bool:
    key = normalise_key(value)
    if key in {"", "0", "non", "n", "false", "faux"}:
        return False
    if key in {"1", "oui", "o", "true", "vrai"}:
        return True
    errors.append(RowError(line, "isolement", f"Oui/non attendu : « {value} »"))
    return False


def _needs(value: str, line: int, col: str, errors: list[RowError]) -> frozenset[str]:
    codes: set[str] = set()
    by_label = {normalise_key(label): code for code, label in SPECIAL_NEEDS.items()}
    for part in re.split(r"[|,/]", value):
        key = normalise_key(part)
        if not key:
            continue
        if key in SPECIAL_NEEDS:
            codes.add(key)
        elif key in by_label:
            codes.add(by_label[key])
        else:
            errors.append(RowError(line, col, f"Besoin inconnu : « {part.strip()} »"))
    return frozenset(codes)
