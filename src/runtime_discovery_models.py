"""Models and packaged universe for PR-056 runtime discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
import json
from typing import Any, Mapping, Protocol

from src.market.snapshots import MarketQuoteSnapshot, SnapshotSet
from src.routing.models import DiscoveryBatch, QuoteRequest
from src.strategy.detectors import DetectorPair
from src.strategy.domain import Opportunity


class RuntimeDiscoveryError(ValueError):
    """Raised when the packaged discovery universe is invalid."""


class DiscoveryClient(Protocol):
    async def discover(self, request: QuoteRequest) -> DiscoveryBatch: ...


@dataclass(frozen=True, slots=True)
class RuntimeDiscoveryPair:
    pair: DetectorPair
    base_decimals: int
    intermediate_decimals: int
    required: bool = False


@dataclass(frozen=True, slots=True)
class RuntimeDiscoveryUniverse:
    schema_version: str
    pairs: tuple[RuntimeDiscoveryPair, ...]
    slippage_bps: int = 50
    cycle_timeout_seconds: float = 20.0
    provider_timeout_seconds: float = 8.0
    max_concurrent_pairs: int = 2
    max_candidates: int = 64

    def __post_init__(self) -> None:
        if self.schema_version != "pr056.discovery-universe.v1":
            raise RuntimeDiscoveryError("unsupported discovery universe schema")
        if not self.pairs:
            raise RuntimeDiscoveryError(
                "discovery universe must contain at least one pair"
            )
        if not any(item.required for item in self.pairs):
            raise RuntimeDiscoveryError(
                "discovery universe needs a required route pair"
            )
        if not 0 <= self.slippage_bps <= 10_000:
            raise RuntimeDiscoveryError("slippage_bps must be between 0 and 10000")
        if self.cycle_timeout_seconds <= 0 or self.provider_timeout_seconds <= 0:
            raise RuntimeDiscoveryError("discovery deadlines must be positive")
        if self.max_concurrent_pairs <= 0 or self.max_candidates <= 0:
            raise RuntimeDiscoveryError("discovery bounds must be positive")
        pair_ids = tuple(item.pair.pair_id for item in self.pairs)
        if len(pair_ids) != len(set(pair_ids)):
            raise RuntimeDiscoveryError("discovery pair IDs must be unique")

    @classmethod
    def load_default(cls) -> "RuntimeDiscoveryUniverse":
        payload = json.loads(
            resources.files("src.resources")
            .joinpath("discovery_universe.json")
            .read_text(encoding="utf-8")
        )
        try:
            pairs = tuple(
                RuntimeDiscoveryPair(
                    pair=DetectorPair(
                        pair_id=str(item["pair_id"]),
                        base_mint=str(item["base_mint"]),
                        intermediate_mint=str(item["intermediate_mint"]),
                        probe_amount_base_units=int(item["probe_amount_base_units"]),
                        min_gross_profit_base_units=int(
                            item["min_gross_profit_base_units"]
                        ),
                        max_snapshot_age_seconds=float(
                            item["max_snapshot_age_seconds"]
                        ),
                        ttl_seconds=float(item["ttl_seconds"]),
                        cooldown_seconds=float(item["cooldown_seconds"]),
                        max_slot_skew=int(item["max_slot_skew"]),
                    ),
                    base_decimals=int(item["base_decimals"]),
                    intermediate_decimals=int(item["intermediate_decimals"]),
                    required=bool(item.get("required", False)),
                )
                for item in payload["pairs"]
            )
            return cls(
                schema_version=str(payload["schema_version"]),
                pairs=pairs,
                slippage_bps=int(payload.get("slippage_bps", 50)),
                cycle_timeout_seconds=float(payload.get("cycle_timeout_seconds", 20.0)),
                provider_timeout_seconds=float(
                    payload.get("provider_timeout_seconds", 8.0)
                ),
                max_concurrent_pairs=int(payload.get("max_concurrent_pairs", 2)),
                max_candidates=int(payload.get("max_candidates", 64)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeDiscoveryError(
                "invalid packaged PR-056 discovery universe"
            ) from exc


@dataclass(frozen=True, slots=True)
class RuntimeDiscoveryEvidence:
    cycle_id: str
    cycle_succeeded: bool
    terminal_reason: str
    commitment: str
    started_at: float
    completed_at: float
    configured_pairs: int
    required_pairs: tuple[str, ...]
    completed_required_pairs: tuple[str, ...]
    requests_attempted: int
    batches_completed: int
    snapshots_created: int
    candidates_created: int
    duplicate_snapshots_dropped: int = 0
    duplicate_candidates_dropped: int = 0
    candidates_dropped_backpressure: int = 0
    provider_failures: Mapping[str, int] = field(default_factory=dict)
    detector_rejections: Mapping[str, str] = field(default_factory=dict)
    degraded_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "pr056.discovery-evidence.v1",
            "cycle_id": self.cycle_id,
            "cycle_succeeded": self.cycle_succeeded,
            "terminal_reason": self.terminal_reason,
            "commitment": self.commitment,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": round((self.completed_at - self.started_at) * 1000, 3),
            "configured_pairs": self.configured_pairs,
            "required_pairs": list(self.required_pairs),
            "completed_required_pairs": list(self.completed_required_pairs),
            "requests_attempted": self.requests_attempted,
            "batches_completed": self.batches_completed,
            "snapshots_created": self.snapshots_created,
            "candidates_created": self.candidates_created,
            "duplicate_snapshots_dropped": self.duplicate_snapshots_dropped,
            "duplicate_candidates_dropped": self.duplicate_candidates_dropped,
            "candidates_dropped_backpressure": self.candidates_dropped_backpressure,
            "provider_failures": dict(self.provider_failures),
            "detector_rejections": dict(self.detector_rejections),
            "degraded_reasons": list(self.degraded_reasons),
        }


@dataclass(frozen=True, slots=True)
class RuntimeDiscoveryReport:
    opportunities: tuple[Opportunity, ...]
    snapshots: SnapshotSet
    evidence: RuntimeDiscoveryEvidence


@dataclass(frozen=True, slots=True)
class _PairCycleResult:
    pair_id: str
    required: bool
    snapshots: tuple[MarketQuoteSnapshot, ...]
    requests_attempted: int
    batches_completed: int
    complete: bool
    provider_failures: Mapping[str, int]
    degraded_reasons: tuple[str, ...] = ()
