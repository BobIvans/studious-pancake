"""MEGA-PR-01 V4 multi-process paper-runtime repair gate.

This module is an offline, sender-free acceptance contract for the V4
production-readiness audit.  It validates materialized evidence for
multi-process ownership, provider handoff, capital reservation and durable
terminal/result coupling before operational paper trading can be promoted.

It does not open databases, call providers, read secrets, construct
transactions, sign, submit, migrate runtime state or enable live execution.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import math
import re
from typing import Any


SCHEMA_VERSION = "mega-pr-01.v4.multiprocess-paper-runtime-gate.v1"

MEGA_PR01_V4_FINDINGS: tuple[str, ...] = (
    "IMPL-42",
    "IMPL-43",
    "IMPL-44",
    "IMPL-45",
    "IMPL-46",
    "IMPL-47",
    "IMPL-48",
    "IMPL-49",
    "IMPL-50",
    "IMPL-51",
    "IMPL-52",
    "IMPL-53",
    "IMPL-54",
    "IMPL-55",
    "IMPL-56",
    "IMPL-57",
    "IMPL-60",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=-]{0,127}$")


class MegaPR01V4State(StrEnum):
    """Review-only verdict for the V4 MEGA-PR-01 checkpoint."""

    READY_FOR_MULTIPROCESS_REPAIR_REVIEW = "ready_for_multiprocess_repair_review"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """Content-addressed materialized evidence reference."""

    label: str
    sha256: str
    path: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OwnershipEvidence:
    """Evidence for synchronized time, owner-bound fencing and terminality."""

    synchronized_time_required_for_sensitive_writes: bool
    degraded_time_closes_readiness: bool
    owner_bound_fences_on_every_mutation: bool
    active_foreign_owner_rejected: bool
    takeover_allocates_new_fencing_token: bool
    terminal_states_irreversible: bool
    legal_state_transition_table_hash: str
    terminal_result_committed_atomically: bool
    failed_result_persistence_leaves_retryable_work: bool
    cycle_sequence_allocation_atomic: bool
    lease_ttl_exceeds_deadline_with_margin: bool
    ownership_renewal_supervised: bool
    recovery_fence_for_timeout_cancel_lease_loss: bool


@dataclass(frozen=True, slots=True)
class ProviderHandoffEvidence:
    """Evidence for provider inbox, handoff and raw-evidence ownership."""

    inbox_claim_lease_ack_nack_dlq_state_machine: bool
    handoff_claim_lease_ack_nack_retry_state_machine: bool
    exact_claimed_handoff_set_acknowledged_with_cycle_terminal: bool
    poison_event_retry_budget_and_backoff: bool
    oldest_poison_event_cannot_block_queue: bool
    original_event_age_bounded_by_trusted_time: bool
    stale_events_routed_to_backfill_or_rejected: bool
    rpc_quorum_constructed_inside_transport: bool
    endpoint_identity_and_raw_response_bound_to_hash: bool
    duplicate_infrastructure_rejected: bool
    immutable_content_addressed_raw_evidence: bool
    raw_evidence_no_update_delete_enforced: bool


@dataclass(frozen=True, slots=True)
class CapitalEvidence:
    """Evidence for wallet-bound, atomic capital reservation."""

    atomic_compare_and_reserve_transaction: bool
    aggregate_active_reservation_db_invariant: bool
    wallet_snapshot_bound_to_payer_genesis_slot_provider_time: bool
    wallet_snapshot_max_age_ms: int
    reservation_identity_collision_free: bool
    reservation_identity_includes_generation_and_candidate_hash: bool
    release_then_reattempt_collision_tested: bool
    reservation_saga_covers_exception_cancel_timeout: bool
    cleanup_failure_freezes_for_recovery: bool
    stranded_active_reservation_recovery_tested: bool


@dataclass(frozen=True, slots=True)
class BatchRuntimeEvidence:
    """Evidence for positive generations and durable per-item progress."""

    attempt_generation_minimum_one_everywhere: bool
    generation_zero_rejected_at_all_boundaries: bool
    per_item_deadlines: bool
    durable_partial_progress_checkpoints: bool
    slow_candidate_cannot_erase_completed_results: bool
    restart_resumes_only_unfinished_fenced_items: bool
    no_duplicate_cycle_multi_instance: bool
    no_foreign_fence_mutation_multi_process: bool
    no_over_reservation_two_coordinators: bool
    no_lost_terminal_result_under_sink_failure: bool
    bounded_queue_progress_under_poison_and_sqlite_busy: bool


@dataclass(frozen=True, slots=True)
class MultiProcessChaosEvidence:
    """Evidence from the new V4 merge-gate chaos matrix."""

    service_instances: int
    capital_coordinators: int
    injected_faults: tuple[str, ...]
    no_duplicate_cycle: bool
    no_foreign_fence_mutation: bool
    no_over_reservation: bool
    no_lost_terminal_result: bool
    bounded_queue_progress: bool
    evidence_artifact: EvidenceRef


@dataclass(frozen=True, slots=True)
class MegaPR01V4Evidence:
    """Complete V4 MEGA-PR-01 evidence bundle."""

    schema_version: str
    covered_findings: tuple[str, ...]
    ownership: OwnershipEvidence
    provider_handoff: ProviderHandoffEvidence
    capital: CapitalEvidence
    batch_runtime: BatchRuntimeEvidence
    chaos: MultiProcessChaosEvidence
    evidence_refs: tuple[EvidenceRef, ...]
    operational_paper_ready_requested: bool = False
    live_execution_requested: bool = False
    signer_requested: bool = False
    sender_requested: bool = False


@dataclass(frozen=True, slots=True)
class MegaPR01V4Violation:
    """Stable fail-closed blocker code."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class MegaPR01V4Report:
    """Deterministic review report for the V4 MEGA-PR-01 gate."""

    schema_version: str
    state: MegaPR01V4State
    blockers: tuple[MegaPR01V4Violation, ...]
    covered_findings: tuple[str, ...]
    evidence_hash: str
    multiprocess_repair_review_allowed: bool
    operational_paper_ready_allowed: bool
    live_execution_allowed: bool
    signer_allowed: bool
    sender_allowed: bool

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["state"] = self.state.value
        return payload


def evaluate_mega_pr01_v4_evidence(evidence: MegaPR01V4Evidence) -> MegaPR01V4Report:
    """Validate V4 evidence and keep runtime promotion fail-closed."""

    blockers: list[MegaPR01V4Violation] = []

    if evidence.schema_version != SCHEMA_VERSION:
        _add(blockers, "MEGA_PR01_V4_SCHEMA_INVALID", "unexpected V4 schema version")
    _finding_coverage(evidence.covered_findings, blockers)
    _evidence_refs(evidence.evidence_refs, blockers)
    _ownership(evidence.ownership, blockers)
    _provider_handoff(evidence.provider_handoff, blockers)
    _capital(evidence.capital, blockers)
    _batch_runtime(evidence.batch_runtime, blockers)
    _chaos(evidence.chaos, blockers)

    if evidence.operational_paper_ready_requested:
        _add(
            blockers,
            "MEGA_PR01_V4_OPERATIONAL_PAPER_PROMOTION_FORBIDDEN",
            "this checkpoint allows repair review only, not operational paper promotion",
        )
    if evidence.live_execution_requested:
        _add(blockers, "MEGA_PR01_V4_LIVE_FORBIDDEN", "live execution remains forbidden")
    if evidence.signer_requested:
        _add(blockers, "MEGA_PR01_V4_SIGNER_FORBIDDEN", "signer access remains forbidden")
    if evidence.sender_requested:
        _add(blockers, "MEGA_PR01_V4_SENDER_FORBIDDEN", "sender access remains forbidden")

    unique = tuple(_dedupe(blockers))
    ready = not unique
    return MegaPR01V4Report(
        schema_version=SCHEMA_VERSION,
        state=(
            MegaPR01V4State.READY_FOR_MULTIPROCESS_REPAIR_REVIEW
            if ready
            else MegaPR01V4State.BLOCKED
        ),
        blockers=unique,
        covered_findings=tuple(evidence.covered_findings),
        evidence_hash=_stable_hash(evidence),
        multiprocess_repair_review_allowed=ready,
        operational_paper_ready_allowed=False,
        live_execution_allowed=False,
        signer_allowed=False,
        sender_allowed=False,
    )


@dataclass(slots=True)
class AtomicReservationModel:
    """Tiny serialized reservation model used by focused V4 tests.

    It is not a database implementation.  It demonstrates the invariant the real
    SQLite/PostgreSQL reservation authority must enforce atomically.
    """

    spendable_lamports: int
    reserved_lamports: int = 0

    def reserve(self, amount_lamports: int) -> bool:
        if not _positive_int(amount_lamports):
            raise ValueError("reservation amount must be positive")
        if self.reserved_lamports + amount_lamports > self.spendable_lamports:
            return False
        self.reserved_lamports += amount_lamports
        return True


def validate_cycle_deadline_lease_policy(
    *,
    now_ms: int,
    deadline_ms: int,
    lease_expires_ms: int,
    commit_margin_ms: int,
) -> tuple[bool, str]:
    """Validate that lease ownership can outlive cycle deadline and commit margin."""

    values = (now_ms, deadline_ms, lease_expires_ms, commit_margin_ms)
    if not all(isinstance(item, int) for item in values):
        return False, "TIME_VALUE_NOT_INTEGER"
    if not all(item >= 0 for item in values):
        return False, "TIME_VALUE_NEGATIVE"
    if deadline_ms <= now_ms:
        return False, "DEADLINE_ALREADY_EXPIRED"
    if lease_expires_ms <= deadline_ms + commit_margin_ms:
        return False, "LEASE_DOES_NOT_COVER_COMMIT_MARGIN"
    return True, "READY"


def _finding_coverage(findings: Sequence[str], blockers: list[MegaPR01V4Violation]) -> None:
    missing = [finding for finding in MEGA_PR01_V4_FINDINGS if finding not in findings]
    if missing:
        _add(blockers, "MEGA_PR01_V4_FINDINGS_INCOMPLETE", f"missing findings: {missing}")
    if len(set(findings)) != len(tuple(findings)):
        _add(blockers, "MEGA_PR01_V4_FINDINGS_DUPLICATED", "covered findings must be unique")


def _evidence_refs(refs: Sequence[EvidenceRef], blockers: list[MegaPR01V4Violation]) -> None:
    required = {
        "ownership",
        "provider_handoff",
        "capital",
        "batch_runtime",
        "chaos",
    }
    labels = {ref.label for ref in refs}
    missing = sorted(required - labels)
    if missing:
        _add(blockers, "MEGA_PR01_V4_EVIDENCE_REF_MISSING", f"missing refs: {missing}")
    for ref in refs:
        if not _safe_id(ref.label) or not _sha(ref.sha256) or not _safe_path(ref.path):
            _add(blockers, "MEGA_PR01_V4_EVIDENCE_REF_INVALID", "evidence refs must be content-addressed and relative")


def _ownership(item: OwnershipEvidence, blockers: list[MegaPR01V4Violation]) -> None:
    _require_all(
        blockers,
        "MEGA_PR01_V4_OWNERSHIP_GAP",
        {
            "synchronized_time_required_for_sensitive_writes": item.synchronized_time_required_for_sensitive_writes,
            "degraded_time_closes_readiness": item.degraded_time_closes_readiness,
            "owner_bound_fences_on_every_mutation": item.owner_bound_fences_on_every_mutation,
            "active_foreign_owner_rejected": item.active_foreign_owner_rejected,
            "takeover_allocates_new_fencing_token": item.takeover_allocates_new_fencing_token,
            "terminal_states_irreversible": item.terminal_states_irreversible,
            "terminal_result_committed_atomically": item.terminal_result_committed_atomically,
            "failed_result_persistence_leaves_retryable_work": item.failed_result_persistence_leaves_retryable_work,
            "cycle_sequence_allocation_atomic": item.cycle_sequence_allocation_atomic,
            "lease_ttl_exceeds_deadline_with_margin": item.lease_ttl_exceeds_deadline_with_margin,
            "ownership_renewal_supervised": item.ownership_renewal_supervised,
            "recovery_fence_for_timeout_cancel_lease_loss": item.recovery_fence_for_timeout_cancel_lease_loss,
        },
    )
    if not _sha(item.legal_state_transition_table_hash):
        _add(blockers, "MEGA_PR01_V4_TRANSITION_TABLE_HASH_INVALID", "legal state table hash required")


def _provider_handoff(item: ProviderHandoffEvidence, blockers: list[MegaPR01V4Violation]) -> None:
    _require_all(
        blockers,
        "MEGA_PR01_V4_PROVIDER_HANDOFF_GAP",
        {
            "inbox_claim_lease_ack_nack_dlq_state_machine": item.inbox_claim_lease_ack_nack_dlq_state_machine,
            "handoff_claim_lease_ack_nack_retry_state_machine": item.handoff_claim_lease_ack_nack_retry_state_machine,
            "exact_claimed_handoff_set_acknowledged_with_cycle_terminal": item.exact_claimed_handoff_set_acknowledged_with_cycle_terminal,
            "poison_event_retry_budget_and_backoff": item.poison_event_retry_budget_and_backoff,
            "oldest_poison_event_cannot_block_queue": item.oldest_poison_event_cannot_block_queue,
            "original_event_age_bounded_by_trusted_time": item.original_event_age_bounded_by_trusted_time,
            "stale_events_routed_to_backfill_or_rejected": item.stale_events_routed_to_backfill_or_rejected,
            "rpc_quorum_constructed_inside_transport": item.rpc_quorum_constructed_inside_transport,
            "endpoint_identity_and_raw_response_bound_to_hash": item.endpoint_identity_and_raw_response_bound_to_hash,
            "duplicate_infrastructure_rejected": item.duplicate_infrastructure_rejected,
            "immutable_content_addressed_raw_evidence": item.immutable_content_addressed_raw_evidence,
            "raw_evidence_no_update_delete_enforced": item.raw_evidence_no_update_delete_enforced,
        },
    )


def _capital(item: CapitalEvidence, blockers: list[MegaPR01V4Violation]) -> None:
    _require_all(
        blockers,
        "MEGA_PR01_V4_CAPITAL_GAP",
        {
            "atomic_compare_and_reserve_transaction": item.atomic_compare_and_reserve_transaction,
            "aggregate_active_reservation_db_invariant": item.aggregate_active_reservation_db_invariant,
            "wallet_snapshot_bound_to_payer_genesis_slot_provider_time": item.wallet_snapshot_bound_to_payer_genesis_slot_provider_time,
            "reservation_identity_collision_free": item.reservation_identity_collision_free,
            "reservation_identity_includes_generation_and_candidate_hash": item.reservation_identity_includes_generation_and_candidate_hash,
            "release_then_reattempt_collision_tested": item.release_then_reattempt_collision_tested,
            "reservation_saga_covers_exception_cancel_timeout": item.reservation_saga_covers_exception_cancel_timeout,
            "cleanup_failure_freezes_for_recovery": item.cleanup_failure_freezes_for_recovery,
            "stranded_active_reservation_recovery_tested": item.stranded_active_reservation_recovery_tested,
        },
    )
    if not _positive_int(item.wallet_snapshot_max_age_ms):
        _add(blockers, "MEGA_PR01_V4_WALLET_SNAPSHOT_AGE_INVALID", "wallet snapshot max age must be positive")


def _batch_runtime(item: BatchRuntimeEvidence, blockers: list[MegaPR01V4Violation]) -> None:
    _require_all(
        blockers,
        "MEGA_PR01_V4_BATCH_RUNTIME_GAP",
        {
            "attempt_generation_minimum_one_everywhere": item.attempt_generation_minimum_one_everywhere,
            "generation_zero_rejected_at_all_boundaries": item.generation_zero_rejected_at_all_boundaries,
            "per_item_deadlines": item.per_item_deadlines,
            "durable_partial_progress_checkpoints": item.durable_partial_progress_checkpoints,
            "slow_candidate_cannot_erase_completed_results": item.slow_candidate_cannot_erase_completed_results,
            "restart_resumes_only_unfinished_fenced_items": item.restart_resumes_only_unfinished_fenced_items,
            "no_duplicate_cycle_multi_instance": item.no_duplicate_cycle_multi_instance,
            "no_foreign_fence_mutation_multi_process": item.no_foreign_fence_mutation_multi_process,
            "no_over_reservation_two_coordinators": item.no_over_reservation_two_coordinators,
            "no_lost_terminal_result_under_sink_failure": item.no_lost_terminal_result_under_sink_failure,
            "bounded_queue_progress_under_poison_and_sqlite_busy": item.bounded_queue_progress_under_poison_and_sqlite_busy,
        },
    )


def _chaos(item: MultiProcessChaosEvidence, blockers: list[MegaPR01V4Violation]) -> None:
    if item.service_instances < 2:
        _add(blockers, "MEGA_PR01_V4_CHAOS_SERVICE_INSTANCES", "at least two service instances required")
    if item.capital_coordinators < 2:
        _add(blockers, "MEGA_PR01_V4_CHAOS_CAPITAL_COORDINATORS", "at least two capital coordinators required")
    required_faults = {
        "kill-9",
        "lease-expiry",
        "sqlite-busy",
        "provider-poison",
    }
    missing_faults = sorted(required_faults - set(item.injected_faults))
    if missing_faults:
        _add(blockers, "MEGA_PR01_V4_CHAOS_FAULTS_INCOMPLETE", f"missing faults: {missing_faults}")
    _require_all(
        blockers,
        "MEGA_PR01_V4_CHAOS_INVARIANT_FAILED",
        {
            "no_duplicate_cycle": item.no_duplicate_cycle,
            "no_foreign_fence_mutation": item.no_foreign_fence_mutation,
            "no_over_reservation": item.no_over_reservation,
            "no_lost_terminal_result": item.no_lost_terminal_result,
            "bounded_queue_progress": item.bounded_queue_progress,
        },
    )
    if (
        not _safe_id(item.evidence_artifact.label)
        or not _sha(item.evidence_artifact.sha256)
        or not _safe_path(item.evidence_artifact.path)
    ):
        _add(
            blockers,
            "MEGA_PR01_V4_CHAOS_EVIDENCE_INVALID",
            "chaos artifact must be content-addressed and relative",
        )


def _require_all(
    blockers: list[MegaPR01V4Violation],
    code: str,
    checks: Mapping[str, bool],
) -> None:
    missing = [name for name, ok in checks.items() if not ok]
    if missing:
        _add(blockers, code, f"missing/false checks: {missing}")


def _add(blockers: list[MegaPR01V4Violation], code: str, message: str) -> None:
    blockers.append(MegaPR01V4Violation(code, message))


def _dedupe(items: Sequence[MegaPR01V4Violation]) -> tuple[MegaPR01V4Violation, ...]:
    seen: set[tuple[str, str]] = set()
    result: list[MegaPR01V4Violation] = []
    for item in items:
        key = (item.code, item.message)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return tuple(result)


def _stable_hash(value: object) -> str:
    payload = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _jsonable(value: object) -> object:
    if hasattr(value, "to_dict"):
        return value.to_dict()  # type: ignore[no-any-return]
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _sha(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _safe_id(value: object) -> bool:
    return isinstance(value, str) and bool(_SAFE_ID_RE.fullmatch(value))


def _safe_path(value: object) -> bool:
    if not isinstance(value, str) or value.startswith("/") or ".." in value.split("/"):
        return False
    return bool(value) and "\x00" not in value


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def is_finite_nonnegative_seconds(value: object) -> bool:
    """Validate public config inputs that represent bounded non-negative seconds."""

    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
