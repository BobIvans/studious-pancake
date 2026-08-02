"""Canonical watermarked market-truth and derived-state primitives."""

from .cache import DerivedCacheEntry, DerivedCacheKey, GenerationBoundCache
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
from .streams import DurableCursorStore, FanoutMatrix, WatermarkedObservationBuffer

__all__ = [
    "CompletenessPolicy",
    "CompletenessState",
    "CorrectionKind",
    "DerivedCacheEntry",
    "DerivedCacheKey",
    "DurableCursorStore",
    "FanoutMatrix",
    "GenerationBoundCache",
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
    "WatermarkedObservationBuffer",
    "coerce_observation_batch",
    "coerce_snapshot_set",
]
