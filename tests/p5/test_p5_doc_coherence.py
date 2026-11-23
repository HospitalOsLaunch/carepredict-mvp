"""Documentary coherence of P5-PROTO-3.1 with its JSON and with the code (review R-P5-02).

Reads documents and module constants only; generates nothing.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import p5_budget_run as runner  # noqa: E402

from hospitalos.p5 import pilot as P  # noqa: E402

DOCS = ROOT / "docs" / "decision_support"
V31 = json.loads((DOCS / "P5_PROTOCOL_PARAMS_v3_1.json").read_text())
MD31 = (DOCS / "P5_PROTOCOL_v3_1.md").read_text()


def test_abstentions_exclude_invariant_failure_which_is_a_stop():
    ab = V31["population"]["abstentions"]
    assert not any("invariant" in x for x in ab["evaluated_as_HABITUAL_1_and_counted"])
    assert "habitual_practice_invariant_failure" in ab["never_an_abstention_stop_with_failure_receipt"]
    assert V31["execution_controls"]["stop_with_failure_receipt"] == ab["never_an_abstention_stop_with_failure_receipt"]
    src = inspect.getsource(P.run_pilot)
    assert "habitual_practice_invariant_failure" in src and "_stop(" in src
    assert "`habitual_practice_invariant_failure` signalé par la v6" in MD31


def test_pilot_content_is_the_six_fit_a5_benchmark_and_l2_is_28_without_a5():
    lot = V31["budget"]["lots"]["P5.2_timed_pilot"]
    assert "6 timing fits" in lot["content_normative_remaining"] and "1440" in lot["content_normative_remaining"]
    assert "2 costliest" not in lot["content_normative_remaining"]
    assert lot["already_executed_counted_once"]["rerun"] is False and lot["cap_s"] == 40
    assert V31["budget"]["fit_timing_benchmark_A5"]["fits"]["total"] == 6
    assert V31["budget"]["fits_count"] == {"without_L2": 72, "with_L2": 28, "A5_timing_fits_separate": 6}
    assert "NOT counted in these 28" in V31["budget"]["fallback_ladder"]["steps_in_order"][1]
    assert "**6 ajustements de chronométrage**" in MD31 and "**28\n  ajustements P5b**" in MD31


def test_ceilings_thresholds_sizes_unchanged_from_v3():
    v3 = json.loads((DOCS / "P5_PROTOCOL_PARAMS_v3.json").read_text())
    for key in ("analysis", "P5b_design"):
        a, b = dict(v3[key]), dict(V31[key])
        assert a == b, key
    assert {k: v["cap_s"] for k, v in V31["budget"]["lots"].items()} == {k: v["cap_s"] for k, v in v3["budget"]["lots"].items()}
    assert V31["budget"]["cap_total_s"] == 1200 and V31["budget"]["per_command_seconds"] == 30
    for part in ("P5a", "P5b"):
        assert V31["population"][part] == v3["population"][part]


def test_runtime_pair_concordant_with_runner_and_md():
    pair = V31["environment"]["approved_runtime_pair"]
    assert (pair["python"], pair["freeze_sha256"]) == (runner.D3_PYTHON, runner.D3_FREEZE_SHA256)
    assert "Python **3.11.18**" in MD31


def test_status_and_supersession():
    assert V31["status"] == MD31.split("**Statut : `")[1].split("`")[0] == "PROPOSED_NOT_APPROVED"
    assert V31["supersedes"]["approvals_transferred"] is False
    assert V31["supersedes"]["document_sha256"].startswith("dbf517ca")
    assert V31["supersedes"]["params_sha256"].startswith("653a426a")
