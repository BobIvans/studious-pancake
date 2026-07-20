"""Integer-only oracle freshness, source, slot and confidence admission."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .common import (
    DataConsistencyPolicy,
    DataPlaneReason,
    SCHEMA_VERSION,
    canonical_hash,
    non_empty,
    non_negative_int,
    sha256_hex,
    time_reason,
)


class OracleStatus(str, Enum):
    TRADING = "trading"
    HALTED = "halted"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class OracleSample:
    source: str
    feed_id: str
    status: OracleStatus
    price_mantissa: int
    exponent: int
    confidence_mantissa: int
    publish_slot: int
    publish_wall_ms: int
    observed_monotonic_ms: int
    payload_hash: str

    def __post_init__(self) -> None:
        non_empty(self.source, "source")
        non_empty(self.feed_id, "feed_id")
        if isinstance(self.price_mantissa, bool) or not isinstance(
            self.price_mantissa, int
        ):
            raise ValueError("price_mantissa must be an integer")
        if isinstance(self.exponent, bool) or not isinstance(self.exponent, int):
            raise ValueError("exponent must be an integer")
        if not -18 <= self.exponent <= 18:
            raise ValueError("oracle exponent is outside the supported range")
        non_negative_int(self.confidence_mantissa, "confidence_mantissa")
        non_negative_int(self.publish_slot, "publish_slot")
        non_negative_int(self.publish_wall_ms, "publish_wall_ms")
        non_negative_int(self.observed_monotonic_ms, "observed_monotonic_ms")
        sha256_hex(self.payload_hash, "payload_hash")


@dataclass(frozen=True, slots=True)
class OraclePolicy:
    allowed_sources: tuple[str, ...]
    max_age_ms: int = 5_000
    max_confidence_bps: int = 100

    def __post_init__(self) -> None:
        if not self.allowed_sources or any(
            not source.strip() for source in self.allowed_sources
        ):
            raise ValueError("allowed_sources must contain non-empty values")
        if len(set(self.allowed_sources)) != len(self.allowed_sources):
            raise ValueError("allowed_sources must be unique")
        if self.max_age_ms <= 0 or not 0 <= self.max_confidence_bps <= 10_000:
            raise ValueError("invalid oracle age/confidence policy")


@dataclass(frozen=True, slots=True)
class OracleDecision:
    accepted: bool
    reason: DataPlaneReason
    confidence_bps: int | None
    min_context_slot: int
    evidence_hash: str


class OracleConsistencyGate:
    def __init__(
        self, data_policy: DataConsistencyPolicy, oracle_policy: OraclePolicy
    ) -> None:
        self.data_policy = data_policy
        self.oracle_policy = oracle_policy

    def evaluate(
        self,
        sample: OracleSample,
        *,
        min_context_slot: int,
        now_wall_ms: int,
        now_monotonic_ms: int,
    ) -> OracleDecision:
        non_negative_int(min_context_slot, "min_context_slot")
        reason = DataPlaneReason.OK
        confidence_bps: int | None = None
        if sample.source not in self.oracle_policy.allowed_sources:
            reason = DataPlaneReason.ORACLE_SOURCE_NOT_ALLOWED
        elif sample.status is not OracleStatus.TRADING:
            reason = DataPlaneReason.ORACLE_NOT_TRADING
        elif sample.publish_slot < min_context_slot:
            reason = DataPlaneReason.BELOW_MIN_CONTEXT_SLOT
        else:
            timing = time_reason(
                observed_wall_ms=sample.publish_wall_ms,
                observed_monotonic_ms=sample.observed_monotonic_ms,
                now_wall_ms=now_wall_ms,
                now_monotonic_ms=now_monotonic_ms,
                max_age_ms=self.oracle_policy.max_age_ms,
                max_future_skew_ms=self.data_policy.max_future_clock_skew_ms,
            )
            if timing:
                reason = timing
            elif sample.price_mantissa == 0:
                reason = DataPlaneReason.ORACLE_INVALID_PRICE
            else:
                confidence_bps = (
                    sample.confidence_mantissa * 10_000 + abs(sample.price_mantissa) - 1
                ) // abs(sample.price_mantissa)
                if confidence_bps > self.oracle_policy.max_confidence_bps:
                    reason = DataPlaneReason.ORACLE_CONFIDENCE_TOO_WIDE
        accepted = reason is DataPlaneReason.OK
        evidence = canonical_hash(
            {
                "schema": SCHEMA_VERSION,
                "accepted": accepted,
                "reason": reason.value,
                "source": sample.source,
                "feed_id": sample.feed_id,
                "slot": sample.publish_slot,
                "min_context_slot": min_context_slot,
                "confidence_bps": confidence_bps,
                "payload_hash": sample.payload_hash,
            }
        )
        return OracleDecision(
            accepted, reason, confidence_bps, min_context_slot, evidence
        )
