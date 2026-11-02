"""Agent side of docs/liscop/REVIEW.md (fix-ingest): S-M2, C-7, S-L2. No browser needed."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from services.admissions_agent.api_client import ApiError, HospitalOSClient
from services.admissions_agent.config import load_settings
from services.admissions_agent.playbook import Playbook, PlaybookError, Transforms
from services.admissions_agent.router import Router

SCREEN_VALUE = "Mme Rosalie Exemplaire"


class FakeLocator:
    def __init__(self, text: str) -> None:
        self.text = text
        self.first = self

    def count(self) -> int:
        return 1

    def inner_text(self) -> str:
        return self.text


class FakePage:
    def __init__(self, text: str) -> None:
        self.text = text

    def locator(self, _selector: str) -> FakeLocator:
        return FakeLocator(self.text)


class FakeSession:
    def __init__(self, text: str) -> None:
        self.page = FakePage(text)


@pytest.mark.parametrize(
    "spec",
    [
        {"selector": "#age", "transform": "int"},
        {"selector": "#date", "transform": "datetime_fr"},
        {"selector": "#type", "map": {"Entrée": "A01"}},
        {"selector": "#mention", "transform": "mention_label"},
    ],
)
def test_s_m2_unreadable_field_names_the_field_and_format_never_the_value(
    spec: dict[str, Any],
) -> None:
    playbook = Playbook({"name": "test"})
    transforms = Transforms({"mentions": {"geriatrie": "Gériatrie"}})

    with pytest.raises(PlaybookError) as caught:
        playbook.read_fields(FakeSession(SCREEN_VALUE), {"champ": spec}, transforms)  # type: ignore[arg-type]

    assert "champ" in str(caught.value) and "attendu" in str(caught.value)
    assert "Rosalie" not in str(caught.value) and "Exemplaire" not in str(caught.value)


def client(handler: Any) -> HospitalOSClient:
    api = HospitalOSClient(
        httpx.Client(transport=httpx.MockTransport(handler), base_url="http://api"), "a", "b"
    )
    api.token = "t"
    return api


def test_s_m2_api_errors_never_copy_the_response_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        detail = [
            {"loc": ["body", "patient_ref"], "msg": "String should match pattern", "type": "x",
             "input": SCREEN_VALUE}
        ]  # fmt: skip
        return httpx.Response(422, json={"detail": detail})

    with pytest.raises(ApiError) as caught:
        client(handler).ingest({"patient_ref": SCREEN_VALUE})

    assert "Rosalie" not in str(caught.value)
    assert "422" in str(caught.value) and "patient_ref" in str(caught.value)


def test_s_m2_api_error_with_a_text_body_keeps_only_the_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"Internal error near {SCREEN_VALUE}")

    with pytest.raises(ApiError) as caught:
        client(handler).ingest({})

    assert "500" in str(caught.value) and "Rosalie" not in str(caught.value)


class FakeApi:
    def __init__(self, answers: list[dict[str, Any]]) -> None:
        self.answers = answers
        self.sent: list[dict[str, Any]] = []

    def ingest_movements(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.sent = batch
        return self.answers


def router(api: FakeApi) -> Router:
    return Router(
        load_settings(),
        api,  # type: ignore[arg-type]
        Playbook({}),
        Transforms({}),
        lambda *a: None,
        lambda: None,  # type: ignore[arg-type, return-value]
    )


def test_c7_rejected_rows_become_a_note_and_the_rest_is_applied() -> None:
    api = FakeApi(
        [
            {"movement_ref": "BS-1", "status": "applied", "message": "ok", "movement_id": 1},
            {"movement_ref": SCREEN_VALUE, "status": "rejected", "movement_id": None,
             "message": "Mouvement invalide (occurred_at : Input should be a valid datetime)"},
            {"movement_ref": "BS-3", "status": "rejected", "movement_id": 3,
             "message": "Lit inconnu (PV1-3) : séjour enregistré sans lit"},
        ]
    )  # fmt: skip
    items = [
        {"movement_ref": "BS-1", "occurred_at": "2026-10-25T09:00:00+02:00"},
        {"movement_ref": SCREEN_VALUE, "occurred_at": "le 25 octobre"},
        {"movement_ref": "BS-3", "occurred_at": "2026-10-25T10:00:00+02:00"},
    ]

    outcome = router(api)._finish_movements("playbook", items, [])

    assert len(api.sent) == 3  # every row was sent: one bad line blocks nothing
    assert outcome.status == "needs_human" and outcome.error == "2 mouvement(s) rejeté(s)"
    assert outcome.result["movements"] == {"applied": 1, "rejected": 2}
    note = " ".join(outcome.result["rejected"])
    assert "occurred_at" in note and "BS-3" in note
    assert "Rosalie" not in note and "25 octobre" not in note


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://hospitalos.example.fr", True),
        ("http://127.0.0.1:8010", True),
        ("http://localhost:8010", True),
        ("http://[::1]:8010", True),
        ("http://api:8010", True),  # compose service name (internal network)
        ("http://hospitalos.example.fr", False),
        ("http://10.0.0.5:8010", False),
        ("ftp://api", False),
    ],
)
def test_s_l2_api_url_must_be_https_outside_loopback_or_compose(
    monkeypatch: pytest.MonkeyPatch, url: str, ok: bool
) -> None:
    monkeypatch.setenv("AGENT_API_URL", url)
    if ok:
        assert load_settings().api_url == url
    else:
        with pytest.raises(ValueError, match="AGENT_API_URL"):
            load_settings()
