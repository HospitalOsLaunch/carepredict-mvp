from __future__ import annotations

from datetime import date

from services.admissions_smr.domain.imports import PoolRow, RequestRow, StayRow, parse_csv


def test_pools_semicolon_bom_and_accented_headers() -> None:
    text = (
        "﻿Site;FINESS;Ville;Mention;Lits installés;Lits ouverts;Chambres isolement;Capacités\n"
        "SMR A;690000011;Lyon;Gériatrie;40;36;4;oxygene|Nutrition entérale\n"
    )
    result = parse_csv("lits", text)
    assert result.ok, result.errors
    row = result.rows[0]
    assert isinstance(row, PoolRow)
    assert row.mention == "geriatrie"
    assert row.capabilities == frozenset({"oxygene", "nutrition_enterale"})


def test_stays_comma_separator_and_date_formats() -> None:
    text = (
        "site,mention,patient_ref,date_entree,date_sortie_prevue,date_sortie\n"
        "SMR A,polyvalent,PAT-1,2026-10-01,15/10/2026,\n"
    )
    result = parse_csv("sejours", text)
    assert result.ok, result.errors
    row = result.rows[0]
    assert isinstance(row, StayRow)
    assert row.admission_date == date(2026, 10, 1)
    assert row.planned_discharge_date == date(2026, 10, 15)
    assert row.discharge_date is None


def test_nir_like_patient_reference_is_refused() -> None:
    text = (
        "site;mention;patient_ref;date_entree\nSMR A;polyvalent;1 84 12 75 123 456 78;01/10/2026\n"
    )
    result = parse_csv("sejours", text)
    assert not result.ok
    assert result.errors[0].column == "patient_ref"
    assert "NIR" in result.errors[0].message


def test_fail_closed_lists_every_error_with_line_numbers() -> None:
    text = (
        "site;mention;patient_ref;date_entree;date_sortie\n"
        "SMR A;polyvalent;PAT-1;01/10/2026;\n"
        "SMR A;inconnue;PAT-2;32/10/2026;\n"
        "SMR A;polyvalent;PAT-3;05/10/2026;01/10/2026\n"
    )
    result = parse_csv("sejours", text)
    assert not result.ok
    lines = sorted({e.line for e in result.errors})
    assert lines == [3, 4]
    assert len(result.rows) == 1


def test_missing_and_unknown_columns() -> None:
    assert "manquantes" in parse_csv("lits", "site;mention\nA;polyvalent\n").errors[0].message
    unknown = parse_csv(
        "sejours", "site;mention;patient_ref;date_entree;nom\nA;polyvalent;P-1;01/10/2026;Dupont\n"
    )
    assert "non reconnues" in unknown.errors[0].message


def test_requests_parse_source_datetime_and_needs() -> None:
    text = (
        "source;ref_externe;recue_le;etablissement_adresseur;service_adresseur;patient_ref;age;sexe;"
        "mention;categorie_clinique;niveau_soins;isolement;besoins;date_souhaitee\n"
        "ViaTrajectoire;VT-1;24/10/2026 14:05;CH X;Médecine;PAT-9;84;F;geriatrie;Chute;3;oui;"
        "oxygene;28/10/2026\n"
    )
    result = parse_csv("demandes", text, "Europe/Paris")
    assert result.ok, result.errors
    row = result.rows[0]
    assert isinstance(row, RequestRow)
    assert row.source == "viatrajectoire"
    assert row.received_at.isoformat() == "2026-10-24T12:05:00+00:00"
    assert row.isolation_required is True
    assert row.needs == frozenset({"oxygene"})
    assert row.care_level == 3
