"""A green check means the expected outcome, not merely a finished task."""

from copy import deepcopy

import pytest

from tools.demo_check import check_outcome


def test_v2_human_check_rejects_any_portal_write() -> None:
    task = {
        "status": "needs_human",
        "cost_usd": 0,
        "route": [{"engine": "playbook", "decision": "failure"}],
    }
    before = {"status": "En attente", "message": None}
    check_outcome(task, before, before, 0, "v2", False)
    with pytest.raises(ValueError, match="sans écriture"):
        check_outcome(task, {"status": "Refusé"}, before, 1, "v2", False)
    with pytest.raises(ValueError, match="aucun coût"):
        check_outcome({**task, "cost_usd": 0.1}, before, before, 0, "v2", False)


def test_model_check_requires_exact_decision_message_cost_and_one_send() -> None:
    task = {
        "status": "done",
        "engine_used": "closed_best",
        "cost_usd": 0.144,
        "payload": {"proposed_date": "2026-11-02", "message": "Bonjour\nAccord."},
        "route": [
            {"engine": "playbook", "decision": "failure"},
            {"engine": "closed_best", "decision": "success"},
        ],
    }
    observed = {"status": "Accord donné", "proposed": "2026-11-02", "message": "Bonjour\nAccord."}
    check_outcome(task, observed, {}, 1, "v2", True)
    check_outcome(task, {**observed, "message": "Bonjour\r\nAccord."}, {}, 1, "v2", True)
    for field, value in (("status", "Refusé"), ("proposed", "2026-11-03"), ("message", "Autre")):
        with pytest.raises(ValueError, match="exactement"):
            check_outcome(task, {**observed, field: value}, {}, 1, "v2", True)
    with pytest.raises(ValueError, match="seule réponse"):
        check_outcome(task, observed, {}, 2, "v2", True)
    no_cost = deepcopy(task)
    no_cost["cost_usd"] = 0
    with pytest.raises(ValueError, match="coût enregistré"):
        check_outcome(no_cost, observed, {}, 1, "v2", True)
    script = {**task, "engine_used": "playbook", "cost_usd": 0}
    check_outcome(script, observed, {}, 1, "v1", False)
    with pytest.raises(ValueError, match="moteur à modèle"):
        check_outcome(script, observed, {}, 1, "v2", True)
