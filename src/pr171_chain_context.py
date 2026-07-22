"""PR-171 chain-time, commitment, slot and fork-consistency contract.

This module is deliberately side-effect free. It does not call Solana RPC,
simulate transactions, fetch fees, mutate caches, or change live/runtime paths.
It models the chain-context evidence that critical artifacts must carry before
real paper proof or live execution can treat them as coherent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


PR171_CHAIN_CONTEXT_SCHEMA = "pr171.chain-context.v1"
_HEX = frozenset("0123456789abcdefABCDEF")


class PR171ChainContextError(ValueError):
    """Raised when PR-171 chain-context evidence is malformed."""


class Commitment(StrEnum):
    """Solana commitment level used by a critical artifact."""

    PROCESSED = "processed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"


class ChainStage(StrEnum):
    """Critical pipeline stage that consumes chain-time evidence."""

    DISCOVERY_HINT = "fast-discovery-hint"
    EXECUTABLE_STATE = "executable-state"
    CAPITAL_PROOF = "capital-proof"
    PRE_STATE = "pre-state"
    SIMULATION = "simulation"
    BLOCKHASH_ALT = "blockhash-alt"
    FEE_QUERY = "fee-query"
    SIGNATURE_PROGRESS = "signature-progress"
    ACCOUNTING = "accounting"
    SETTLEMENT = "settlement"


class ChainConsistencyStatus(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class StageCommitmentRule:
    """Reviewed minimum finality requirements for one stage."""

    stage: ChainStage
    minimum_commitment: Commitment
    require_context_slot: bool = True
    require_min_context_slot: bool = False
    require_root_slot: bool = True
    require_finalized_slot: bool = False
    execution_evidence: bool = False
    accounting_evidence: bool = False

    def __post_init__(self) -> None:
        if self.accounting_evidence and self.minimum_commitment != Commitment.FINALIZED:
            raise PR171ChainContextError("accounting evidence must require finalized")
        if self.require_min_context_slot and not self.require_context_slot:
            raise PR171ChainContextError("minContextSlot requires response context")

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "minimum_commitment": self.minimum_commitment.value,
            "require_context_slot": self.require_context_slot,
            "require_min_context_slot": self.require_min_context_slot,
            "require_root_slot": self.require_root_slot,
            "require_finalized_slot": self.require_finalized_slot,
            "execution_evidence": self.execution_evidence,
            "accounting_evidence": self.accounting_evidence,
        }


@dataclass(frozen=True, slots=True)
class ChainContext:
    """One coherent chain-time and fork identity snapshot for an artifact."""

    cluster_genesis: str
    endpoint_identity: str
    correlation_group: str
    request_method: str
    request_hash: str
    commitment: Commitment
    current_slot: int
    wall_time_ns: int
    monotonic_time_ns: int
    fork_fingerprint: str
    context_slot: int | None = None
    min_context_slot: int | None = None
    root_slot: int | None = None
    finalized_slot: int | None = None
    block_height: int | None = None
    response_context_present: bool = True
    evidence_expires_at_ns: int | None = None
    provenance: Mapping[str, str] = field(default_factory=dict)
    schema_version: str = PR171_CHAIN_CONTEXT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PR171_CHAIN_CONTEXT_SCHEMA:
            raise PR171ChainContextError("unsupported chain context schema")
        _require_text(self.cluster_genesis, field="cluster_genesis")
        _require_text(self.endpoint_identity, field="endpoint_identity")
        _require_text(self.correlation_group, field="correlation_group")
        _require_text(self.request_method, field="request_method")
        _require_sha256(self.request_hash, field="request_hash")
        _require_text(self.fork_fingerprint, field="fork_fingerprint")
        _non_negative(self.current_slot, field="current_slot")
        _non_negative(self.wall_time_ns, field="wall_time_ns")
        _non_negative(self.monotonic_time_ns, field="monotonic_time_ns")
        for field_name in (
            "context_slot",
            "min_context_slot",
            "root_slot",
            "finalized_slot",
            "block_height",
            "evidence_expires_at_ns",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _non_negative(value, field=field_name)
        if self.response_context_present and self.context_slot is None:
            raise PR171ChainContextError("response context is present but context_slot is missing")
        if not self.response_context_present and self.context_slot is not None:
            raise PR171ChainContextError("context_slot cannot be supplied when response context is absent")
        if self.min_context_slot is not None and self.context_slot is not None:
            if self.context_slot < self.min_context_slot:
                raise PR171ChainContextError("context_slot is below minContextSlot")
        if self.root_slot is not None and self.root_slot > self.current_slot:
            raise PR171ChainContextError("root_slot cannot exceed current_slot")
        if self.finalized_slot is not None and self.finalized_slot > self.current_slot:
            raise PR171ChainContextError("finalized_slot cannot exceed current_slot")
        if self.context_slot is not None and self.context_slot > self.current_slot:
            raise PR171ChainContextError("context_slot cannot exceed current_slot")
        if self.evidence_expires_at_ns is not None:
            if self.evidence_expires_at_ns <= self.wall_time_ns:
                raise PR171ChainContextError("evidence expiry must be after observation time")
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "cluster_genesis": self.cluster_genesis,
            "endpoint_identity": self.endpoint_identity,
            "correlation_group": self.correlation_group,
            "request_method": self.request_method,
            "request_hash": self.request_hash,
            "commitment": self.commitment.value,
            "current_slot": self.current_slot,
            "context_slot": self.context_slot,
            "min_context_slot": self.min_context_slot,
            "root_slot": self.root_slot,
            "finalized_slot": self.finalized_slot,
            "block_height": self.block_height,
            "wall_time_ns": self.wall_time_ns,
            "monotonic_time_ns": self.monotonic_time_ns,
            "fork_fingerprint": self.fork_fingerprint,
            "response_context_present": self.response_context_present,
            "evidence_expires_at_ns": self.evidence_expires_at_ns,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True, slots=True)
class AccountSetEvidence:
    """Ordered account evidence for a request that must not silently truncate."""

    requested_addresses: Sequence[str]
    returned_addresses: Sequence[str]
    context: ChainContext
    null_addresses: Sequence[str] = ()

    def __post_init__(self) -> None:
        requested = tuple(self.requested_addresses)
        returned = tuple(self.returned_addresses)
        nulls = tuple(self.null_addresses)
        if not requested:
            raise PR171ChainContextError("account evidence requires at least one address")
        for address in requested:
            _require_text(address, field="requested account address")
        for address in returned:
            _require_text(address, field="returned account address")
        for address in nulls:
            _require_text(address, field="null account address")
        if len(set(requested)) != len(requested):
            raise PR171ChainContextError("duplicate requested account address")
        if len(set(returned)) != len(returned):
            raise PR171ChainContextError("duplicate returned account address")
        if len(set(nulls)) != len(nulls):
            raise PR171ChainContextError("duplicate null account address")
        if set(nulls) - set(requested):
            raise PR171ChainContextError("null account must belong to request set")
        if len(returned) + len(nulls) != len(requested):
            raise PR171ChainContextError("account response cardinality mismatch")
        if tuple(address for address in requested if address not in nulls) != returned:
            raise PR171ChainContextError("account response order does not bind request order")
        object.__setattr__(self, "requested_addresses", requested)
        object.__setattr__(self, "returned_addresses", returned)
        object.__setattr__(self, "null_addresses", nulls)

    @property
    def complete(self) -> bool:
        return not self.null_addresses

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_addresses": list(self.requested_addresses),
            "returned_addresses": list(self.returned_addresses),
            "null_addresses": list(self.null_addresses),
            "complete": self.complete,
            "context": self.context.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SimulationEvidenceBundle:
    """Coherent context bundle for pre-state, simulation, fees and blockhash/ALT."""

    pre_state: ChainContext
    simulation: ChainContext
    fee: ChainContext | None = None
    blockhash_alt: ChainContext | None = None
    account_set: AccountSetEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pre_state": self.pre_state.to_dict(),
            "simulation": self.simulation.to_dict(),
            "fee": self.fee.to_dict() if self.fee else None,
            "blockhash_alt": self.blockhash_alt.to_dict() if self.blockhash_alt else None,
            "account_set": self.account_set.to_dict() if self.account_set else None,
        }


@dataclass(frozen=True, slots=True)
class ChainCacheKey:
    """Commitment-aware cache key for critical chain evidence."""

    cluster_genesis: str
    commitment: Commitment
    min_context_slot: int | None
    root_slot: int | None
    fork_fingerprint: str
    request_hash: str

    def to_tuple(self) -> tuple[str, str, int | None, int | None, str, str]:
        return (
            self.cluster_genesis,
            self.commitment.value,
            self.min_context_slot,
            self.root_slot,
            self.fork_fingerprint,
            self.request_hash,
        )


@dataclass(frozen=True, slots=True)
class ChainConsistencyReport:
    """Fail-closed PR-171 evaluation report."""

    status: ChainConsistencyStatus
    reasons: tuple[str, ...]
    stage_contexts: Mapping[str, dict[str, Any]]
    runtime_live_enabled: bool = False
    schema_version: str = PR171_CHAIN_CONTEXT_SCHEMA

    @property
    def ready(self) -> bool:
        return self.status == ChainConsistencyStatus.READY

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "ready": self.ready,
            "runtime_live_enabled": self.runtime_live_enabled,
            "reasons": list(self.reasons),
            "stage_contexts": dict(self.stage_contexts),
            "metrics": {
                "reason_count": len(self.reasons),
                "stage_context_count": len(self.stage_contexts),
            },
        }


def default_stage_policy() -> Mapping[ChainStage, StageCommitmentRule]:
    """Return the reviewed PR-171 minimum commitment matrix."""

    return MappingProxyType(
        {
            ChainStage.DISCOVERY_HINT: StageCommitmentRule(
                ChainStage.DISCOVERY_HINT,
                Commitment.PROCESSED,
                require_context_slot=True,
                require_root_slot=False,
            ),
            ChainStage.EXECUTABLE_STATE: StageCommitmentRule(
                ChainStage.EXECUTABLE_STATE,
                Commitment.CONFIRMED,
                require_min_context_slot=True,
                execution_evidence=True,
            ),
            ChainStage.CAPITAL_PROOF: StageCommitmentRule(
                ChainStage.CAPITAL_PROOF,
                Commitment.CONFIRMED,
                require_min_context_slot=True,
                execution_evidence=True,
            ),
            ChainStage.PRE_STATE: StageCommitmentRule(
                ChainStage.PRE_STATE,
                Commitment.CONFIRMED,
                require_min_context_slot=True,
                execution_evidence=True,
            ),
            ChainStage.SIMULATION: StageCommitmentRule(
                ChainStage.SIMULATION,
                Commitment.CONFIRMED,
                require_min_context_slot=True,
                execution_evidence=True,
            ),
            ChainStage.BLOCKHASH_ALT: StageCommitmentRule(
                ChainStage.BLOCKHASH_ALT,
                Commitment.CONFIRMED,
                require_min_context_slot=True,
                execution_evidence=True,
            ),
            ChainStage.FEE_QUERY: StageCommitmentRule(
                ChainStage.FEE_QUERY,
                Commitment.CONFIRMED,
                require_min_context_slot=True,
                execution_evidence=True,
            ),
            ChainStage.SIGNATURE_PROGRESS: StageCommitmentRule(
                ChainStage.SIGNATURE_PROGRESS,
                Commitment.PROCESSED,
                require_root_slot=False,
            ),
            ChainStage.ACCOUNTING: StageCommitmentRule(
                ChainStage.ACCOUNTING,
                Commitment.FINALIZED,
                require_min_context_slot=True,
                require_finalized_slot=True,
                accounting_evidence=True,
            ),
            ChainStage.SETTLEMENT: StageCommitmentRule(
                ChainStage.SETTLEMENT,
                Commitment.FINALIZED,
                require_min_context_slot=True,
                require_finalized_slot=True,
                accounting_evidence=True,
            ),
        }
    )


def evaluate_context_for_stage(
    context: ChainContext,
    stage: ChainStage,
    policy: Mapping[ChainStage, StageCommitmentRule] | None = None,
) -> tuple[str, ...]:
    """Return fail-closed reasons for one context/stage pair."""

    active_policy = default_stage_policy() if policy is None else policy
    if stage not in active_policy:
        raise PR171ChainContextError(f"missing commitment rule for {stage.value}")
    rule = active_policy[stage]
    reasons: list[str] = []
    if _commitment_rank(context.commitment) < _commitment_rank(rule.minimum_commitment):
        reasons.append(
            f"{stage.value}:commitment-below-{rule.minimum_commitment.value}"
        )
    if rule.require_context_slot:
        if not context.response_context_present or context.context_slot is None:
            reasons.append(f"{stage.value}:missing-response-context-slot")
    if rule.require_min_context_slot and context.min_context_slot is None:
        reasons.append(f"{stage.value}:missing-min-context-slot")
    if rule.require_root_slot and context.root_slot is None:
        reasons.append(f"{stage.value}:missing-root-slot")
    if rule.require_finalized_slot and context.finalized_slot is None:
        reasons.append(f"{stage.value}:missing-finalized-slot")
    if context.min_context_slot is not None and context.context_slot is not None:
        if context.context_slot < context.min_context_slot:
            reasons.append(f"{stage.value}:context-below-min-context-slot")
    if context.evidence_expires_at_ns is not None:
        if context.evidence_expires_at_ns <= context.wall_time_ns:
            reasons.append(f"{stage.value}:expired-evidence")
    return _dedupe(reasons)


def evaluate_simulation_bundle(
    bundle: SimulationEvidenceBundle,
    policy: Mapping[ChainStage, StageCommitmentRule] | None = None,
) -> ChainConsistencyReport:
    """Evaluate pre-state/simulation/fee/blockhash coherence without side effects."""

    reasons: list[str] = []
    contexts: dict[str, ChainContext] = {
        ChainStage.PRE_STATE.value: bundle.pre_state,
        ChainStage.SIMULATION.value: bundle.simulation,
    }
    if bundle.fee is not None:
        contexts[ChainStage.FEE_QUERY.value] = bundle.fee
    if bundle.blockhash_alt is not None:
        contexts[ChainStage.BLOCKHASH_ALT.value] = bundle.blockhash_alt
    for stage_value, context in contexts.items():
        reasons.extend(
            evaluate_context_for_stage(context, ChainStage(stage_value), policy=policy)
        )
    reasons.extend(_coherence_reasons(tuple(contexts.values())))
    if bundle.account_set is None:
        reasons.append("account-set:missing")
    else:
        reasons.extend(
            evaluate_context_for_stage(bundle.account_set.context, ChainStage.PRE_STATE)
        )
        if not bundle.account_set.complete:
            reasons.append("account-set:contains-null-account")
        reasons.extend(_coherence_reasons((bundle.pre_state, bundle.account_set.context)))
    clean_reasons = _dedupe(reasons)
    status = (
        ChainConsistencyStatus.READY
        if not clean_reasons
        else ChainConsistencyStatus.BLOCKED
    )
    return ChainConsistencyReport(
        status=status,
        reasons=clean_reasons,
        stage_contexts={name: context.to_dict() for name, context in contexts.items()},
    )


def evaluate_finalized_accounting_context(context: ChainContext) -> ChainConsistencyReport:
    """Evaluate whether a context can be used for finalized accounting/settlement."""

    reasons = evaluate_context_for_stage(context, ChainStage.SETTLEMENT)
    status = ChainConsistencyStatus.READY if not reasons else ChainConsistencyStatus.BLOCKED
    return ChainConsistencyReport(
        status=status,
        reasons=reasons,
        stage_contexts={ChainStage.SETTLEMENT.value: context.to_dict()},
    )


def build_cache_key(context: ChainContext) -> ChainCacheKey:
    """Build a cache key that cannot cross commitment/fork/minContextSlot."""

    return ChainCacheKey(
        cluster_genesis=context.cluster_genesis,
        commitment=context.commitment,
        min_context_slot=context.min_context_slot,
        root_slot=context.root_slot,
        fork_fingerprint=context.fork_fingerprint,
        request_hash=context.request_hash,
    )


def reorg_invalidation_reasons(before: ChainContext, after: ChainContext) -> tuple[str, ...]:
    """Return dependent-artifact invalidation reasons across fork/root changes."""

    reasons: list[str] = []
    if before.cluster_genesis != after.cluster_genesis:
        reasons.append("cluster-genesis-changed")
    if before.correlation_group != after.correlation_group:
        reasons.append("endpoint-correlation-group-changed")
    if before.fork_fingerprint != after.fork_fingerprint:
        reasons.append("fork-fingerprint-changed")
    if before.root_slot is not None and after.root_slot is not None:
        if after.root_slot < before.root_slot:
            reasons.append("root-regressed")
        elif after.root_slot > before.root_slot:
            reasons.append("root-advanced")
    if before.finalized_slot is not None and after.finalized_slot is not None:
        if after.finalized_slot < before.finalized_slot:
            reasons.append("finalized-slot-regressed")
    return _dedupe(reasons)


def require_no_implicit_commitment(
    *,
    method: str,
    commitment: Commitment | None,
) -> Commitment:
    """Fail closed when a critical RPC call omits commitment."""

    _require_text(method, field="method")
    if commitment is None:
        raise PR171ChainContextError(f"{method}: implicit commitment is forbidden")
    return commitment


def require_simulation_context_slot(
    *,
    response_context_slot: int | None,
    blockhash_source_slot: int | None,
) -> int:
    """Reject missing simulation context instead of inventing one from blockhash."""

    if response_context_slot is None:
        if blockhash_source_slot is not None:
            raise PR171ChainContextError(
                "simulation context missing; blockhash source slot is not simulation slot"
            )
        raise PR171ChainContextError("simulation context missing")
    _non_negative(response_context_slot, field="response_context_slot")
    return response_context_slot


def _coherence_reasons(contexts: Sequence[ChainContext]) -> tuple[str, ...]:
    if not contexts:
        return ()
    first = contexts[0]
    reasons: list[str] = []
    for context in contexts[1:]:
        if context.cluster_genesis != first.cluster_genesis:
            reasons.append("coherence:cluster-genesis-mismatch")
        if context.commitment != first.commitment:
            reasons.append("coherence:commitment-mismatch")
        if context.correlation_group != first.correlation_group:
            reasons.append("coherence:endpoint-correlation-group-mismatch")
        if context.fork_fingerprint != first.fork_fingerprint:
            reasons.append("coherence:fork-fingerprint-mismatch")
        if context.root_slot != first.root_slot:
            reasons.append("coherence:root-slot-mismatch")
        if context.min_context_slot != first.min_context_slot:
            reasons.append("coherence:min-context-slot-mismatch")
    return _dedupe(reasons)


def _commitment_rank(commitment: Commitment) -> int:
    return {
        Commitment.PROCESSED: 0,
        Commitment.CONFIRMED: 1,
        Commitment.FINALIZED: 2,
    }[commitment]


def _require_text(value: str, *, field: str) -> None:
    if not value or not value.strip():
        raise PR171ChainContextError(f"{field} must be non-empty")


def _require_sha256(value: str, *, field: str) -> None:
    _require_text(value, field=field)
    if len(value) != 64 or any(char not in _HEX for char in value):
        raise PR171ChainContextError(f"{field} must be a sha256 hex digest")
    if len(set(value)) == 1:
        raise PR171ChainContextError(f"{field} must not be a placeholder digest")


def _non_negative(value: int, *, field: str) -> None:
    if value < 0:
        raise PR171ChainContextError(f"{field} must be non-negative")


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


__all__ = [
    "PR171_CHAIN_CONTEXT_SCHEMA",
    "AccountSetEvidence",
    "ChainCacheKey",
    "ChainConsistencyReport",
    "ChainConsistencyStatus",
    "ChainContext",
    "ChainStage",
    "Commitment",
    "PR171ChainContextError",
    "SimulationEvidenceBundle",
    "StageCommitmentRule",
    "build_cache_key",
    "default_stage_policy",
    "evaluate_context_for_stage",
    "evaluate_finalized_accounting_context",
    "evaluate_simulation_bundle",
    "reorg_invalidation_reasons",
    "require_no_implicit_commitment",
    "require_simulation_context_slot",
]
