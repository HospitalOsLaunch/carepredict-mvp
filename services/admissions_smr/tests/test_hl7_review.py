"""Regression tests for the findings of docs/liscop/REVIEW.md (fix-ingest), one per id."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from services.admissions_smr.models import Group
from services.admissions_smr.tests.test_api import new_request

Login = Callable[[str], dict[str, str]]
MakeGroup = Callable[[str], Group]


def test_c3_smr_request_with_an_mco_unit_code_is_refused_not_a_500(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("g1")
    h = login("coord@g1.fr")

    created = app_client.post(
        "/api/requests", json=new_request(mention_requested="cardiologie"), headers=h
    )

    assert created.status_code == 422
