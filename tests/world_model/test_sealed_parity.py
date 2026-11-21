"""Drive the shipped API against the held-out synthetic H4 reference stored with the tests."""

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import BaseModel

from hospitalos.world_model.contracts import Session
from services.api.hybrid_app import create_app


class ForecastReference(BaseModel):
    by_ward: list[float]
    jepa_total: float


class ReviewReference(BaseModel):
    selected_id: str
    observed_by_ward: list[float | None]
    reconstructed_by_option: dict[str, list[float]]


class CaseReference(BaseModel):
    feed: str
    published_hour: int
    options: dict[str, ForecastReference]
    reviews: list[ReviewReference]


class ReferenceBundle(BaseModel):
    cases: dict[str, CaseReference]


REFERENCES = ReferenceBundle.model_validate_json(
    (Path(__file__).parent / "fixtures" / "balestriero_h4.json").read_bytes(), strict=True
).cases


def ok(response: Response) -> Session:
    assert response.is_success, response.text
    return Session.model_validate_json(response.content, strict=True)


@pytest.mark.parametrize("context", sorted(REFERENCES))
def test_http_forecasts_reports_and_reconstructions_match_the_sealed_study(
    tmp_path: Path, context: str
) -> None:
    expected = REFERENCES[context]
    with TestClient(create_app(world_model_db=tmp_path / "parity.sqlite")) as client:
        for example in expected.reviews:
            path = f"/world-model/sessions/{uuid4()}"
            opened = ok(client.put(path, json={"context_id": context}))
            assert opened.observation is None
            assert opened.context.feed == expected.feed
            assert opened.publication_hour == expected.published_hour
            assert {o.id for o in opened.options} == expected.options.keys()
            for option in opened.options:
                golden = expected.options[option.id]
                assert option.by_ward == pytest.approx(golden.by_ward, abs=1e-7, rel=1e-8)
                assert option.forecast == pytest.approx(sum(golden.by_ward), abs=1e-7, rel=1e-8)
                # The frozen neural net uses float32 matrix multiplies across supported CPUs.
                assert option.jepa_forecast == pytest.approx(golden.jepa_total, abs=3e-5, rel=1e-7)
            selected = example.selected_id
            ok(client.post(f"{path}/confirm", json={"option_id": selected}))
            completed = ok(client.post(f"{path}/advance", json={"from_hour": 12}))
            if expected.published_hour == 18:
                assert completed.observation is None
                completed = ok(client.post(f"{path}/advance", json={"from_hour": 16}))
            assert completed.selected_id == selected
            assert completed.phase == "review"
            observation = completed.observation
            assert observation is not None
            assert observation.sample_hour == 16
            assert observation.published_hour == expected.published_hour
            for actual, expected_value in zip(
                observation.by_ward, example.observed_by_ward, strict=True
            ):
                if expected_value is None:
                    assert actual is None
                else:
                    assert actual == pytest.approx(expected_value, abs=1e-7, rel=1e-8)
            for option in completed.options:
                reference = example.reconstructed_by_option[option.id]
                assert option.reconstructed_by_ward == pytest.approx(reference, abs=1e-7, rel=1e-8)
                assert option.reconstruction == pytest.approx(sum(reference), abs=1e-7, rel=1e-8)
