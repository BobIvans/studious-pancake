"""Multi-RPC consistency without first-response or blind-majority trust."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
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


class RootedRpcQuorumReason(str, Enum):
    OK = "PR136_OK"
    NO_DATA = "PR136_NO_DATA"
    ENDPOINT_IDENTITY_MISMATCH = "PR136_ENDPOINT_IDENTITY_MISMATCH"
    GENESIS_MISMATCH = "PR136_GENESIS_MISMATCH"
    REQUEST_MISMATCH = "PR136_REQUEST_MISMATCH"
    LOW_COMMITMENT = "PR136_LOW_COMMITMENT"
    BELOW_MIN_CONTEXT_SLOT = "PR136_BELOW_MIN_CONTEXT_SLOT"
    STALE_OBSERVATION = "PR136_STALE_OBSERVATION"
    FUTURE_OBSERVATION = "PR136_FUTURE_OBSERVATION"
    NOT_ROOTED = "PR136_NOT_ROOTED"
    ROOT_SLOT_LAG = "PR136_ROOT_SLOT_LAG"
    SAME_SLOT_CONFLICT = "PR136_SAME_SLOT_CONFLICT"
    SLOT_DIVERGENCE = "PR136_SLOT_DIVERGENCE"
    CORRELATED_RPC_SOURCES = "PR136_CORRELATED_RPC_SOURCES"
    INSUFFICIENT_INDEPENDENT_EVIDENCE = "PR136_INSUFFICIENT_INDEPENDENT_EVIDENCE"
    UNSUPPORTED_TX_VERSION = "PR136_UNSUPPORTED_TX_VERSION"
    FEATURE_SET_MISMATCH = "PR136_FEATURE_SET_MISMATCH"


@dataclass(frozen=True, slots=True)
class RpcEndpointIdentity:
    endpoint_id: str
    provider: str
    operator: str
    correlation_group: str
    region: str
    endpoint_account: str
    genesis_hash: str
    node_version: str
    feature_set: int
    max_supported_transaction_version: int
    observed_wall_ms: int
    observed_monotonic_ms: int
    evidence_expires_at_monotonic_ms: int

    def __post_init__(self) -> None:
        non_empty(self.endpoint_id, "endpoint_id")
        non_empty(self.provider, "provider")
        non_empty(self.operator, "operator")
        non_empty(self.correlation_group, "correlation_group")
        non_empty(self.region, "region")
        non_empty(self.endpoint_account, "endpoint_account")
        non_empty(self.genesis_hash, "genesis_hash")
        non_empty(self.node_version, "node_version")
        non_negative_int(self.feature_set, "feature_set")
        non_negative_int(
            self.max_supported_transaction_version,
            "max_supported_transaction_version",
        )
        non_negative_int(self.observed_wall_ms, "observed_wall_ms")
        non_negative_int(self.observed_monotonic_ms, "observed_monotonic_ms")
        non_negative_int(
            self.evidence_expires_at_monotonic_ms,
            "evidence_expires_at_monotonic_ms",
        )
        if self.evidence_expires_at_monotonic_ms < self.observed_monotonic_ms:
            raise ValueError(
                "endpoint identity evidence cannot expire before observation"
            )


@dataclass(frozen=True, slots=True)
class RootedRpcSample:
    sample: RpcSample
    identity: RpcEndpointIdentity
    current_slot: int
    finalized_slot: int
    root_slot: int
    block_hash: str

    def __post_init__(self) -> None:
        if self.sample.endpoint_id != self.identity.endpoint_id:
            raise ValueError("sample and identity endpoint_id must match")
        if self.sample.genesis_hash != self.identity.genesis_hash:
            raise ValueError("sample and identity genesis_hash must match")
        non_negative_int(self.current_slot, "current_slot")
        non_negative_int(self.finalized_slot, "finalized_slot")
        non_negative_int(self.root_slot, "root_slot")
        non_empty(self.block_hash, "block_hash")
        if not self.root_slot <= self.finalized_slot <= self.current_slot:
            raise ValueError("root/finalized/current slots must be monotonic")


@dataclass(frozen=True, slots=True)
class RootedRpcQuorumPolicy:
    required_commitment: CommitmentLevel = CommitmentLevel.FINALIZED
    minimum_independent_correlation_groups: int = 2
    max_observation_age_ms: int = 2_000
    max_future_clock_skew_ms: int = 1_000
    max_rpc_slot_delta: int = 2
    max_root_lag_slots: int = 4
    min_supported_transaction_version: int = 0
    require_matching_feature_set: bool = True

    def __post_init__(self) -> None:
        positive = (
            self.minimum_independent_correlation_groups,
            self.max_observation_age_ms,
            self.max_rpc_slot_delta,
            self.max_root_lag_slots,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in positive
        ):
            raise ValueError("PR-136 quorum policy limits must be positive integers")
        if (
            isinstance(self.max_future_clock_skew_ms, bool)
            or not isinstance(self.max_future_clock_skew_ms, int)
            or self.max_future_clock_skew_ms < 0
        ):
            raise ValueError("max_future_clock_skew_ms must be a non-negative integer")
        if (
            isinstance(self.min_supported_transaction_version, bool)
            or not isinstance(self.min_supported_transaction_version, int)
            or self.min_supported_transaction_version < 0
        ):
            raise ValueError(
                "min_supported_transaction_version must be a non-negative integer"
            )
        if not isinstance(self.require_matching_feature_set, bool):
            raise ValueError("require_matching_feature_set must be boolean")


@dataclass(frozen=True, slots=True)
class RootedRpcQuorumDecision:
    accepted: bool
    reason: RootedRpcQuorumReason
    canonical_endpoint_id: str | None
    canonical_slot: int | None
    payload_hash: str | None
    independent_correlation_groups: tuple[str, ...]
    matching_endpoints: tuple[str, ...]
    rejected_endpoints: tuple[tuple[str, str], ...]
    evidence_hash: str


class RootedRpcQuorumGate:
    """PR-136 fork/finality-aware quorum that counts independent backends."""

    def __init__(self, policy: RootedRpcQuorumPolicy) -> None:
        self.policy = policy

    def evaluate(
        self,
        samples: Sequence[RootedRpcSample],
        *,
        expected_genesis_hash: str,
        expected_method: str,
        expected_request_hash: str,
        min_context_slot: int,
        now_wall_ms: int,
        now_monotonic_ms: int,
    ) -> RootedRpcQuorumDecision:
        non_empty(expected_genesis_hash, "expected_genesis_hash")
        non_empty(expected_method, "expected_method")
        sha256_hex(expected_request_hash, "expected_request_hash")
        non_negative_int(min_context_slot, "min_context_slot")
        if not samples:
            return self._result(False, RootedRpcQuorumReason.NO_DATA)

        valid: list[RootedRpcSample] = []
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
            if sample.sample.endpoint_id in seen:
                reason = RootedRpcQuorumReason.ENDPOINT_IDENTITY_MISMATCH
            seen.add(sample.sample.endpoint_id)
            if reason is None:
                valid.append(sample)
            else:
                rejected.append((sample.sample.endpoint_id, reason.value))

        if not valid:
            return self._result(
                False,
                _dominant_pr136(rejected),
                rejected=tuple(rejected),
            )

        highest_slot = max(item.sample.context_slot for item in valid)
        slot_delta = highest_slot - min(item.sample.context_slot for item in valid)
        if slot_delta > self.policy.max_rpc_slot_delta:
            return self._result(
                False,
                RootedRpcQuorumReason.SLOT_DIVERGENCE,
                slot=highest_slot,
                rejected=tuple(rejected),
            )

        highest = [item for item in valid if item.sample.context_slot == highest_slot]
        if len({item.sample.payload_hash for item in highest}) != 1:
            return self._result(
                False,
                RootedRpcQuorumReason.SAME_SLOT_CONFLICT,
                slot=highest_slot,
                rejected=tuple(rejected),
            )

        feature_sets = {item.identity.feature_set for item in highest}
        if self.policy.require_matching_feature_set and len(feature_sets) != 1:
            return self._result(
                False,
                RootedRpcQuorumReason.FEATURE_SET_MISMATCH,
                slot=highest_slot,
                rejected=tuple(rejected),
            )

        matches = sorted(
            highest,
            key=lambda item: (
                item.sample.latency_ms,
                item.identity.provider,
                item.sample.endpoint_id,
            ),
        )
        groups = tuple(sorted({item.identity.correlation_group for item in matches}))
        endpoints = tuple(item.sample.endpoint_id for item in matches)
        payload_hash = matches[0].sample.payload_hash

        if len(matches) < self.policy.minimum_independent_correlation_groups:
            return self._result(
                False,
                RootedRpcQuorumReason.INSUFFICIENT_INDEPENDENT_EVIDENCE,
                slot=highest_slot,
                payload_hash=payload_hash,
                matches=endpoints,
                groups=groups,
                rejected=tuple(rejected),
            )
        if len(groups) < self.policy.minimum_independent_correlation_groups:
            return self._result(
                False,
                RootedRpcQuorumReason.CORRELATED_RPC_SOURCES,
                slot=highest_slot,
                payload_hash=payload_hash,
                matches=endpoints,
                groups=groups,
                rejected=tuple(rejected),
            )

        canonical = matches[0]
        return self._result(
            True,
            RootedRpcQuorumReason.OK,
            endpoint=canonical.sample.endpoint_id,
            slot=highest_slot,
            payload_hash=payload_hash,
            matches=endpoints,
            groups=groups,
            rejected=tuple(rejected),
        )

    def _reject_reason(
        self,
        rooted: RootedRpcSample,
        genesis: str,
        method: str,
        request_hash: str,
        min_slot: int,
        now_wall_ms: int,
        now_monotonic_ms: int,
    ) -> RootedRpcQuorumReason | None:
        sample = rooted.sample
        identity = rooted.identity
        if sample.endpoint_id != identity.endpoint_id:
            return RootedRpcQuorumReason.ENDPOINT_IDENTITY_MISMATCH
        if sample.genesis_hash != genesis or identity.genesis_hash != genesis:
            return RootedRpcQuorumReason.GENESIS_MISMATCH
        if sample.method != method or sample.request_hash != request_hash:
            return RootedRpcQuorumReason.REQUEST_MISMATCH
        if sample.commitment.rank < self.policy.required_commitment.rank:
            return RootedRpcQuorumReason.LOW_COMMITMENT
        if sample.context_slot < min_slot:
            return RootedRpcQuorumReason.BELOW_MIN_CONTEXT_SLOT
        if (
            identity.max_supported_transaction_version
            < self.policy.min_supported_transaction_version
        ):
            return RootedRpcQuorumReason.UNSUPPORTED_TX_VERSION
        if rooted.root_slot < sample.context_slot:
            return RootedRpcQuorumReason.NOT_ROOTED
        if rooted.current_slot - rooted.root_slot > self.policy.max_root_lag_slots:
            return RootedRpcQuorumReason.ROOT_SLOT_LAG

        sample_time_reason = time_reason(
            observed_wall_ms=sample.observed_wall_ms,
            observed_monotonic_ms=sample.observed_monotonic_ms,
            now_wall_ms=now_wall_ms,
            now_monotonic_ms=now_monotonic_ms,
            max_age_ms=self.policy.max_observation_age_ms,
            max_future_skew_ms=self.policy.max_future_clock_skew_ms,
        )
        if sample_time_reason is DataPlaneReason.FUTURE_OBSERVATION:
            return RootedRpcQuorumReason.FUTURE_OBSERVATION
        if sample_time_reason is DataPlaneReason.STALE_OBSERVATION:
            return RootedRpcQuorumReason.STALE_OBSERVATION
        if identity.evidence_expires_at_monotonic_ms < now_monotonic_ms:
            return RootedRpcQuorumReason.STALE_OBSERVATION
        if identity.observed_monotonic_ms > now_monotonic_ms:
            return RootedRpcQuorumReason.FUTURE_OBSERVATION
        return None

    @staticmethod
    def _result(
        accepted: bool,
        reason: RootedRpcQuorumReason,
        *,
        endpoint: str | None = None,
        slot: int | None = None,
        payload_hash: str | None = None,
        matches: tuple[str, ...] = (),
        groups: tuple[str, ...] = (),
        rejected: tuple[tuple[str, str], ...] = (),
    ) -> RootedRpcQuorumDecision:
        evidence = canonical_hash(
            {
                "schema": "pr136.rooted-rpc-quorum.v1",
                "accepted": accepted,
                "reason": reason.value,
                "canonical_endpoint_id": endpoint,
                "canonical_slot": slot,
                "payload_hash": payload_hash,
                "independent_correlation_groups": groups,
                "matching_endpoints": matches,
                "rejected_endpoints": rejected,
            }
        )
        return RootedRpcQuorumDecision(
            accepted=accepted,
            reason=reason,
            canonical_endpoint_id=endpoint,
            canonical_slot=slot,
            payload_hash=payload_hash,
            independent_correlation_groups=groups,
            matching_endpoints=matches,
            rejected_endpoints=rejected,
            evidence_hash=evidence,
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


def _dominant_pr136(
    rejected: Sequence[tuple[str, str]],
) -> RootedRpcQuorumReason:
    priorities = (
        RootedRpcQuorumReason.GENESIS_MISMATCH,
        RootedRpcQuorumReason.REQUEST_MISMATCH,
        RootedRpcQuorumReason.LOW_COMMITMENT,
        RootedRpcQuorumReason.BELOW_MIN_CONTEXT_SLOT,
        RootedRpcQuorumReason.NOT_ROOTED,
        RootedRpcQuorumReason.ROOT_SLOT_LAG,
        RootedRpcQuorumReason.FUTURE_OBSERVATION,
        RootedRpcQuorumReason.STALE_OBSERVATION,
        RootedRpcQuorumReason.UNSUPPORTED_TX_VERSION,
    )
    values = {reason for _, reason in rejected}
    return next(
        (reason for reason in priorities if reason.value in values),
        RootedRpcQuorumReason.INSUFFICIENT_INDEPENDENT_EVIDENCE,
    )
