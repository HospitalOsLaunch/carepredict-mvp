from __future__ import annotations

from hfwm.baselines import HORIZONS_HOURS, TARGETS, adapt_temporal_corpus
from hfwm.corpus import CorpusConfig, build_temporal_corpus


def test_corpus_adapter_reuses_frozen_pit_windows_targets_and_splits() -> None:
    corpus = build_temporal_corpus(
        CorpusConfig(
            organization_count=2,
            episodes_per_unit=5,
            episode_hours=120,
            history_hours=24,
            horizons_hours=HORIZONS_HOURS,
            purge_gap_hours=1,
            window_stride_hours=24,
        )
    )
    splits = adapt_temporal_corpus(corpus)
    rows = (*splits.train, *splits.validation, *splits.test)

    assert len(rows) == len(corpus.windows)
    assert {row.row_id for row in rows} == {
        f"{window.episode_id}@{window.origin_at.isoformat()}" for window in corpus.windows
    }
    assert all(
        point.observed_at <= row.origin_at and point.available_at <= row.origin_at
        for row in rows
        for point in row.history
    )
    assert all(tuple(row.future_targets) == TARGETS for row in rows)
    assert all(
        tuple(row.future_targets[target]) == HORIZONS_HOURS
        for row in rows
        for target in TARGETS
    )
