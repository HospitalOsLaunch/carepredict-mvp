import json
from pathlib import Path

import pytest

from research_lab.cli import (
    STAGES,
    api_error_details,
    digest,
    read_brief,
    run_cycle,
    validate_answer,
    verify_journal,
)

BRIEF = ('Under partial observability, can an action-conditioned latent state '
         'distinguish dynamic information from conditional marginal shortcuts?')


def test_offline_smoke_has_six_agents_and_no_compute(tmp_path: Path) -> None:
    work = tmp_path / 'lab'
    outcome = run_cycle(BRIEF, work, mode='smoke')
    assert outcome['stages'] == len(STAGES) == 6
    assert outcome['verdict'] == 'NOT_TESTED'
    events = [e['event'] for e in verify_journal(work)]
    assert [e['type'] for e in events].count('STAGE_OUTPUT') == 6
    assert all(e['scientific_status'] == 'FIXTURE_NOT_EVIDENCE'
               for e in events if e['type'] == 'STAGE_OUTPUT')
    assert events[-1]['type'] == 'COMPLETE'
    assert not any('train' in event['type'].lower() for event in events)


def test_live_requires_explicit_permission_and_no_workspace_written(tmp_path: Path) -> None:
    work = tmp_path / 'lab'
    with pytest.raises(PermissionError):
        run_cycle(BRIEF, work, mode='live', budget_usd='3')
    assert not work.exists()


def test_live_requires_api_key_before_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    work = tmp_path / 'lab'
    with pytest.raises(ValueError, match='OPENAI_API_KEY'):
        run_cycle(BRIEF, work, mode='live', budget_usd='3', allow_api=True)
    assert not work.exists()


def test_no_duplicate_cycle_workspace(tmp_path: Path) -> None:
    work = tmp_path / 'lab'
    run_cycle(BRIEF, work, mode='smoke')
    with pytest.raises(FileExistsError):
        run_cycle(BRIEF, work, mode='smoke')


def test_tampering_detected(tmp_path: Path) -> None:
    work = tmp_path / 'lab'
    run_cycle(BRIEF, work, mode='smoke')
    journal = work / 'events.jsonl'
    text = journal.read_text()
    journal.write_text(text.replace('NOT_TESTED', 'NO_GO', 1))
    with pytest.raises(ValueError, match='modified'):
        verify_journal(work)


def test_no_model_promotion_in_schema() -> None:
    answer = {'claims': [], 'falsifiers': [], 'prior_art': [], 'next_steps': [], 'gate': 'PROMOTED'}
    with pytest.raises(ValueError, match='cannot authorize'):
        validate_answer(json.dumps(answer))


def test_brief_email_rejected(tmp_path: Path) -> None:
    path = tmp_path / 'brief.txt'
    path.write_text('Patient email someone@example.com')
    with pytest.raises(ValueError, match='private email'):
        read_brief(path)


def test_journal_hash_is_stable() -> None:
    assert digest({'a': 1, 'b': 2}) == digest({'b': 2, 'a': 1})


def test_sanitized_api_429_diagnostics() -> None:
    class FakeError(Exception):
        status_code = 429
        body = {'error': {'code': 'insufficient_quota', 'type': 'insufficient_quota',
                          'message': 'sensitive text'}}

    assert api_error_details(FakeError()) == ('insufficient_quota', 'insufficient_quota')


def test_sanitized_api_error_rejects_untrusted_identifiers() -> None:
    class FakeError(Exception):
        body = {'error': {'code': 'key=secret sk-123', 'type': ['unknown']}}

    assert api_error_details(FakeError()) == ('unknown', 'unknown')
