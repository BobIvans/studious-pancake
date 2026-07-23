"""Canonical sender-free paper platform introduced by MEGA-PR-01."""
from .model import (
    CandidateDecision,
    DualClock,
    PaperCandidate,
    PaperCycleReport,
    PaperOutcome,
    PaperPlatformError,
    PersistenceError,
    RecordingError,
)
from .platform import CanonicalPaperConfig, CanonicalPaperPlatform
from .source import BoundedRecordedBatchSource, RecordedBatch, digest_config_file
from .store import CanonicalPaperStore

__all__ = [
    "BoundedRecordedBatchSource",
    "CanonicalPaperConfig",
    "CanonicalPaperPlatform",
    "CanonicalPaperStore",
    "CandidateDecision",
    "DualClock",
    "PaperCandidate",
    "PaperCycleReport",
    "PaperOutcome",
    "PaperPlatformError",
    "PersistenceError",
    "RecordedBatch",
    "RecordingError",
    "digest_config_file",
]
