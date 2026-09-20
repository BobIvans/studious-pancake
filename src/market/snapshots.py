"""Compatibility imports for the MPR-042 canonical observation authority.

The historical module path remains stable, but every exported runtime object is
implemented by :mod:`src.market.observations`; no V1 snapshot model remains.
"""

from .observations import (
    CompletenessPolicy,
    CompletenessState,
    CorrectionKind,
    MarketObservationV2,
    MarketQuoteSnapshot,
    MarketSnapshotSource,
    ObservationBatch,
    ObservationError,
    ObservationGeneration,
    ObservationWatermark,
    RecordedSnapshotSource,
    SnapshotSet,
    SnapshotSourceError,
    SourceCursor,
    coerce_observation_batch,
    coerce_snapshot_set,
)

__all__ = [
    "CompletenessPolicy",
    "CompletenessState",
    "CorrectionKind",
    "MarketObservationV2",
    "MarketQuoteSnapshot",
    "MarketSnapshotSource",
    "ObservationBatch",
    "ObservationError",
    "ObservationGeneration",
    "ObservationWatermark",
    "RecordedSnapshotSource",
    "SnapshotSet",
    "SnapshotSourceError",
    "SourceCursor",
    "coerce_observation_batch",
    "coerce_snapshot_set",
]
