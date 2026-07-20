"""Multi-RPC consistency without first-response or blind-majority trust."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .common import (
    CommitmentLevel,
    DataConsistencyPolicy,
    DataPlaneReason,
    SCHEMA_VERSION,
    canonical_hash,
    non_empty,
    non_negative_int,
    sha256_hex,
    time_reason,
)


@dataclass(frozen=True, slots=True)
class RpcSample:
    endpoint_id: str
    genesis_hash: str
    method: str
    request_hash: str
    context_slot: int
    commitment: CommitmentLevel
    payload_hash: str
    observed_wall_ms: int
    observed_monotonic_ms: int
    latency_ms: int
    error_code: str | None = None

    def __post_init__(self) -> None:
        non_empty(self.endpoint_id, "endpoint_id")
        non_empty(self.genesis_hash, "genesis_hash")
        non_empty(self.method, "method")
        sha256_hex(self.request_hash, "request_hash")
        sha256_hex(self.payload_hash, "payload_hash")
        non_negative_int(self.context_slot, "context_slot")
        non_negative_int(self.observed_wall_ms, "observed_wall_ms")
        non_negative_int(self.observed_monotonic_ms, "observed_monotonic_ms")
        non_negative_int(self.latency_ms, "latency_ms")


@dataclass(frozen=True, slots=True)
class RpcConsistencyDecision:
    accepted: bool
    reason: DataPlaneReason
    canonical_endpoint_id: str | None
    canonical_slot: int | None
    payload_hash: str | None
    matching_endpoints: tuple[str, ...]
    rejected_endpoints: tuple[tuple[str, str], ...]
    evidence_hash: str


class RpcConsistencyGate:
    def __init__(self, policy: DataConsistencyPolicy) -> None:
        self.policy = policy

    def evaluate(
        self,
        samples: Sequence[RpcSample],
        *,
        expected_genesis_hash: str,
        expected_method: str,
        expected_request_hash: str,
        min_context_slot: int,
        now_wall_ms: int,
        now_monotonic_ms: int,
    ) -> RpcConsistencyDecision:
        non_empty(expected_genesis_hash, "expected_genesis_hash")
        non_empty(expected_method, "expected_method")
        sha256_hex(expected_request_hash, "expected_request_hash")
        non_negative_int(min_context_slot, "min_context_slot")
        if not samples:
            return self._result(False, DataPlaneReason.NO_DATA)

        valid: list[RpcSample] = []
        rejected: list[tuple[str, str]] = []
        seen: set[str] = set()
        for sample in samples:
            reason = self._reject_reason(
                sample,
                expected_genesis_hash,
                expected_method,
                expected_request_hash,
                min_context_slot,
                now_wall_ms,
                now_monotonic_ms,
            )
            if sample.endpoint_id in seen:
                reason = DataPlaneReason.INVALID_INPUT
            seen.add(sample.endpoint_id)
            if reason is None:
                valid.append(sample)
            else:
                rejected.append((sample.endpoint_id, reason.value))

        if not valid:
            return self._result(False, _dominant(rejected), rejected=tuple(rejected))
        highest_slot = max(sample.context_slot for sample in valid)
        highest = [sample for sample in valid if sample.context_slot == highest_slot]
        if len({sample.payload_hash for sample in highest}) != 1:
            return self._result(
                False,
                DataPlaneReason.RPC_SAME_SLOT_CONFLICT,
                slot=highest_slot,
                rejected=tuple(rejected),
            )
        if (
            highest_slot - min(sample.context_slot for sample in valid)
            > self.policy.max_rpc_slot_delta
        ):
            return self._result(
                False,
                DataPlaneReason.RPC_SLOT_DIVERGENCE,
                slot=highest_slot,
                rejected=tuple(rejected),
            )

        matches = sorted(
            highest, key=lambda sample: (sample.latency_ms, sample.endpoint_id)
        )
        payload_hash = matches[0].payload_hash
        endpoints = tuple(sample.endpoint_id for sample in matches)
        if len(matches) < self.policy.minimum_matching_rpc_sources:
            return self._result(
                False,
                DataPlaneReason.RPC_INSUFFICIENT_EVIDENCE,
                slot=highest_slot,
                payload_hash=payload_hash,
                matches=endpoints,
                rejected=tuple(rejected),
            )
        return self._result(
            True,
            DataPlaneReason.OK,
            endpoint=matches[0].endpoint_id,
            slot=highest_slot,
            payload_hash=payload_hash,
            matches=endpoints,
            rejected=tuple(rejected),
        )

    def _reject_reason(
        self,
        sample: RpcSample,
        genesis: str,
        method: str,
        request_hash: str,
        min_slot: int,
        now_wall_ms: int,
        now_monotonic_ms: int,
    ) -> DataPlaneReason | None:
        if sample.error_code:
            return DataPlaneReason.RPC_INSUFFICIENT_EVIDENCE
        if sample.genesis_hash != genesis:
            return DataPlaneReason.RPC_GENESIS_MISMATCH
        if sample.method != method or sample.request_hash != request_hash:
            return DataPlaneReason.RPC_REQUEST_MISMATCH
        if sample.commitment.rank < self.policy.required_commitment.rank:
            return DataPlaneReason.LOW_COMMITMENT
        if sample.context_slot < min_slot:
            return DataPlaneReason.BELOW_MIN_CONTEXT_SLOT
        return time_reason(
            observed_wall_ms=sample.observed_wall_ms,
            observed_monotonic_ms=sample.observed_monotonic_ms,
            now_wall_ms=now_wall_ms,
            now_monotonic_ms=now_monotonic_ms,
            max_age_ms=self.policy.max_observation_age_ms,
            max_future_skew_ms=self.policy.max_future_clock_skew_ms,
        )

    @staticmethod
    def _result(
        accepted: bool,
        reason: DataPlaneReason,
        *,
        endpoint: str | None = None,
        slot: int | None = None,
        payload_hash: str | None = None,
        matches: tuple[str, ...] = (),
        rejected: tuple[tuple[str, str], ...] = (),
    ) -> RpcConsistencyDecision:
        evidence = canonical_hash(
            {
                "schema": SCHEMA_VERSION,
                "accepted": accepted,
                "reason": reason.value,
                "endpoint": endpoint,
                "slot": slot,
                "payload_hash": payload_hash,
                "matches": matches,
                "rejected": rejected,
            }
        )
        return RpcConsistencyDecision(
            accepted,
            reason,
            endpoint,
            slot,
            payload_hash,
            matches,
            rejected,
            evidence,
        )


def _dominant(rejected: Sequence[tuple[str, str]]) -> DataPlaneReason:
    priorities = (
        DataPlaneReason.RPC_GENESIS_MISMATCH,
        DataPlaneReason.RPC_REQUEST_MISMATCH,
        DataPlaneReason.LOW_COMMITMENT,
        DataPlaneReason.BELOW_MIN_CONTEXT_SLOT,
        DataPlaneReason.FUTURE_OBSERVATION,
        DataPlaneReason.STALE_OBSERVATION,
    )
    values = {reason for _, reason in rejected}
    return next(
        (reason for reason in priorities if reason.value in values),
        DataPlaneReason.RPC_INSUFFICIENT_EVIDENCE,
    )
