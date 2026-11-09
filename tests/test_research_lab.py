import json
from pathlib import Path
from typing import Any

import pytest

from research_lab.cli import (
    STAGES,
    api_error_details,
    load_resume,
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


def test_resume_reuses_prior_stage_without_new_sol_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import research_lab.cli as lab

    class FakeProvider:
        calls: list[str] = []

        def __init__(self) -> None:
            pass

        def complete(
            self, *, stage: lab.Stage, prompt: str, max_output_tokens: int
        ) -> tuple[str, dict[str, Any]]:
            self.calls.append(stage.name)
            if stage.name == 'hypotheses' and len(self.calls) == 2:
                raise ValueError('synthetic truncated first attempt')
            assert prompt and max_output_tokens
            answer = {'claims': [f'Hypothesis {stage.name}'], 'falsifiers': [],
                      'prior_art': [], 'next_steps': [], 'gate': 'NOT_TESTED'}
            return json.dumps(answer), {
                'input_tokens': 5, 'output_tokens': 40, 'reasoning_tokens': 0,
                'response_status': 'completed', 'incomplete_reason': 'none',
            }

    provider = FakeProvider()
    monkeypatch.setattr(lab, 'OpenAIProvider', lambda: provider)
    first = tmp_path / 'old'
    with pytest.raises(ValueError, match='synthetic truncated'):
        lab.run_cycle(BRIEF, first, mode='live', allow_api=True, budget_usd='5')
    assert provider.calls == ['prior_art', 'hypotheses']
    assert lab.verify_journal(first)[-1]['event']['type'] == 'ABORTED'
    carry, spent, source_hash = load_resume(first, BRIEF, 'live')
    assert [name for name, _ in carry] == ['prior_art']
    assert spent > 0 and len(source_hash) == 64
    second = tmp_path / 'new'
    result = lab.run_cycle(BRIEF, second, mode='live', allow_api=True,
                           budget_usd='5', resume_from=first)
    assert result['stages'] == 6
    assert provider.calls.count('prior_art') == 1
    events = [e['event'] for e in lab.verify_journal(second)]
    assert [e['type'] for e in events].count('RESUMED_STAGE') == 1
    assert [e['type'] for e in events].count('STAGE_OUTPUT') == 5
    assert events[-1]['type'] == 'COMPLETE'
    assert lab.verify_journal(first)[-1]['event']['type'] == 'ABORTED'


def test_resume_rejects_changed_brief(tmp_path: Path) -> None:
    import research_lab.cli as lab

    work = tmp_path / 'fixture'
    lab.run_cycle(BRIEF, work, mode='smoke')
    with pytest.raises(ValueError, match='Resume source does not match'):
        load_resume(work, 'changed brief', 'live')


def test_multihop_resume_carries_original_reservations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import research_lab.cli as lab

    class FakeProvider:
        calls: list[str] = []

        def complete(
            self, *, stage: lab.Stage, prompt: str, max_output_tokens: int
        ) -> tuple[str, dict[str, Any]]:
            self.calls.append(stage.name)
            if stage.name in ('hypotheses', 'red_team'):
                raise ValueError('simulated incomplete response')
            answer = {'claims': [], 'falsifiers': [], 'prior_art': [],
                      'next_steps': [], 'gate': 'NOT_TESTED'}
            return json.dumps(answer), {
                'response_status': 'completed', 'incomplete_reason': 'none',
                'input_tokens': 20, 'output_tokens': 30,
            }

    fake = FakeProvider()
    monkeypatch.setattr(lab, 'OpenAIProvider', lambda: fake)
    first = tmp_path / 'first'
    with pytest.raises(ValueError, match='simulated incomplete'):
        lab.run_cycle(BRIEF, first, mode='live', allow_api=True, budget_usd='5')
    second = tmp_path / 'second'
    with pytest.raises(ValueError, match='simulated incomplete'):
        lab.run_cycle(BRIEF, second, mode='live', allow_api=True,
                      budget_usd='5', resume_from=first)
    third = tmp_path / 'third'
    _, first_reserved, _ = lab.load_resume(first, BRIEF, 'live')
    _, second_reserved, _ = lab.load_resume(second, BRIEF, 'live')
    assert second_reserved > first_reserved
    # Previous reservations are inherited even when the second run aborts.
    events = lab.verify_journal(second)
    assert events[0]['event']['carried_reserved_usd'] == str(first_reserved)
    assert fake.calls.count('prior_art') == 1
    assert not third.exists()
