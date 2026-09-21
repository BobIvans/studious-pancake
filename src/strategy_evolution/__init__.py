"""PR-353 strategy-evolution laboratory."""

from .core import (
    CorrelationHypothesis,
    CoverageCell,
    EventClock,
    EvolutionError,
    EvolutionEvidenceRef,
    EvolutionState,
    QualificationArtifact,
    ResearchCandidate,
    TypedBlocker,
    ValueBand,
)

LIVE_ENABLED = False
SIGNING_ENABLED = False
SUBMISSION_ENABLED = False
AUTO_PROMOTION_ENABLED = False

__all__ = [
    "AUTO_PROMOTION_ENABLED",
    "CorrelationHypothesis",
    "CoverageCell",
    "EventClock",
    "EvolutionError",
    "EvolutionEvidenceRef",
    "EvolutionState",
    "LIVE_ENABLED",
    "QualificationArtifact",
    "ResearchCandidate",
    "SIGNING_ENABLED",
    "SUBMISSION_ENABLED",
    "TypedBlocker",
    "ValueBand",
]
