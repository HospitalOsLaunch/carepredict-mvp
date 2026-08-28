"""First-party deterministic synthetic temporal corpus for HFWM-R0."""

from .generator import (
    build_contamination_records,
    build_htl_registry,
    build_temporal_corpus,
)
from .model import (
    BUILD_CODE_VERSION,
    CORPUS_SCHEMA,
    SOURCE_ID,
    CorpusConfig,
    RecordingInterval,
    TemporalCorpus,
)

__all__ = [
    "BUILD_CODE_VERSION",
    "CORPUS_SCHEMA",
    "SOURCE_ID",
    "CorpusConfig",
    "RecordingInterval",
    "TemporalCorpus",
    "build_contamination_records",
    "build_htl_registry",
    "build_temporal_corpus",
]
