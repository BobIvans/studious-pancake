"""PR-168 external dependency resilience evidence gate.

This module is intentionally side-effect free. It does not call providers, RPC,
Jito, signer, Alertmanager, backup stores, or trading code. It evaluates whether
review evidence proves that external dependencies are isolated by purpose,
bounded by shared retry/deadline budgets, protected by persistent circuit
breakers, and degraded without weakening safety/economic guarantees.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum
import hashlib
import json
import re
from typing import Iterable, Mapping

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_BULKHEAD_PURPOSES: tuple[str, ...] = (
    "discovery",
    "finalization",
    "rpc_account_reads",
    "exact_simulation",
    "settlement_polling",
    "jito",
    "webhook_backfill",
    "telemetry_backup",
)

REQUIRED_OUTAGE_DRILLS: tuple[str, ...] = (
    "provider_hangs",
    "retry_after_429",
    "auth_revoked",
    "schema_changed",
    "dns_failure",
    "tls_failure",
    "partial_json",
    "one_rpc_on_fork",
    "all_exact_finalizers_down",
    "signer_alertmanager_object_store_unavailable",
)

FORBIDDEN_FALLBACK_CAPABILITY_DROPS: tuple[tuple[str, str], ...] = (
    ("composable_instructions", "assembled_transaction"),
    ("exact_amount_quote", "estimated_amount_quote"),
    ("program_attested", "program_unattested"),
    ("rooted_rpc_quorum", "single_unrooted_rpc"),
)

class DependencyCriticality(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    FINALIZER = "finalizer"
    SAFETY_CRITICAL = "safety_critical"

class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"
    FORCED_OPEN = "forced_open"

class FailureKind(StrEnum):
    AUTH = "auth"
    SCHEMA_DRIFT = "schema_drift"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    DNS_TLS = "dns_tls"
    SERVER_5XX = "server_5xx"
    BUSINESS_REJECTION = "business_rejection"
    INVALID_EVIDENCE = "invalid_evidence"

FATAL_FAILURES = {
    FailureKind.AUTH,
    FailureKind.SCHEMA_DRIFT,
    FailureKind.INVALID_EVIDENCE,
}

class ResilienceDecisionState(StrEnum):
    READY = "dependency-resilience-review-ready"
    BLOCKED = "blocked"

@dataclass(frozen=True, slots=True)
class DependencyCatalogEntry:
    dependency_id: str
    purpose: str
    criticality: DependencyCriticality
    provider_identity_hash: str
    endpoint_identity_hash: str
    credential_ref_hash: str
    quota_policy_hash: str
    timeout_ms: int
    retry_policy_hash: str
    circuit_policy_hash: str
    fallback_ids: tuple[str, ...]
    consistency_contract_hash: str
    maximum_outage_ms: int
    manual_override_policy_hash: str

@dataclass(frozen=True, slots=True)
class BulkheadEvidence:
    purpose: str
    max_concurrent_tasks: int
    max_connections: int
    max_memory_bytes: int
    independent_pool: bool
    preserves_finalization_capacity: bool
    queue_bound: int
    policy_hash: str

@dataclass(frozen=True, slots=True)
class RetryDeadlineBudget:
    operation_id: str
    absolute_deadline_ns: int
    issued_at_ns: int
    max_total_attempts: int
    max_cumulative_delay_ms: int
    max_provider_switches: int
    nested_components_share_budget: bool
    expires_before_candidate_ns: int
    retry_after_expiry_allowed: bool
    policy_hash: str

@dataclass(frozen=True, slots=True)
class CircuitBreakerEvidence:
    dependency_id: str
    purpose: str
    state: CircuitState
    rolling_window_ms: int
    failure_rate_threshold_ppm: int
    slow_call_threshold_ppm: int
    minimum_sample_count: int
    half_open_concurrency: int
    exponential_open_duration: bool
    open_duration_cap_ms: int
    persisted_state: bool
    persisted_last_cause: bool
    manual_force_open_supported: bool
    resets_only_on_policy_change: bool
    differentiates_failures: frozenset[FailureKind]
    fatal_failures_auto_recover_by_cooldown: bool
    policy_hash: str

@dataclass(frozen=True, slots=True)
class FallbackEvidence:
    source_dependency_id: str
    fallback_dependency_id: str
    source_capabilities: frozenset[str]
    fallback_capabilities: frozenset[str]
    same_security_domain: bool
    same_economic_guarantees: bool
    same_atomicity_role: bool
    preserves_min_out: bool
    preserves_slot_freshness: bool
    preserves_program_attestation: bool
    equivalence_hash: str

@dataclass(frozen=True, slots=True)
class GracefulDegradationEvidence:
    scenario: str
    degraded_state_code: str
    optional_loss_is_bounded: bool
    required_loss_blocks_trade: bool
    settlement_capacity_preserved: bool
    reconciliation_capacity_preserved: bool
    finalization_capacity_preserved: bool
    new_attempts_stopped_before_reconciliation: bool
    explicit_operator_alert: bool
    policy_hash: str

@dataclass(frozen=True, slots=True)
class OutageDrillEvidence:
    drill_id: str
    passed: bool
    report_hash: str
    stable_memory: bool
    stable_fd: bool
    stable_queue: bool
    readiness_reflects_dependency_matrix: bool
    alerting_reflects_dependency_matrix: bool

@dataclass(frozen=True, slots=True)
class DependencyResilienceEvidence:
    catalog: tuple[DependencyCatalogEntry, ...]
    bulkheads: tuple[BulkheadEvidence, ...]
    retry_budgets: tuple[RetryDeadlineBudget, ...]
    circuits: tuple[CircuitBreakerEvidence, ...]
    fallbacks: tuple[FallbackEvidence, ...]
    degradations: tuple[GracefulDegradationEvidence, ...]
    outage_drills: tuple[OutageDrillEvidence, ...]
    dependency_matrix_hash: str
    readiness_policy_hash: str
    alerting_policy_hash: str
    unresolved_blockers: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class DependencyResilienceDecision:
    state: ResilienceDecisionState
    blockers: tuple[str, ...]
    dependency_matrix_hash: str
    evidence_hash: str
    degraded_modes: tuple[str, ...]
    live_claim_allowed: bool = False
    sender_submission_allowed: bool = False

    @property
    def review_ready(self) -> bool:
        return self.state == ResilienceDecisionState.READY

class DependencyResilienceBlocked(RuntimeError):
    def __init__(self, decision: DependencyResilienceDecision) -> None:
        super().__init__("PR-168 dependency resilience evidence is blocked")
        self.decision = decision

def evaluate_pr168_dependency_resilience(
    evidence: DependencyResilienceEvidence,
) -> DependencyResilienceDecision:
    blockers: list[str] = []
    _validate_top_level(evidence, blockers)
    _validate_catalog(evidence.catalog, blockers)
    _validate_bulkheads(evidence.bulkheads, blockers)
    _validate_retry_budgets(evidence.retry_budgets, blockers)
    _validate_circuits(evidence.circuits, blockers)
    _validate_fallbacks(evidence.fallbacks, blockers)
    _validate_degradations(evidence.degradations, blockers)
    _validate_outage_drills(evidence.outage_drills, blockers)
    for item in evidence.unresolved_blockers:
        blockers.append(f"UNRESOLVED_BLOCKER:{item}")

    state = ResilienceDecisionState.READY if not blockers else ResilienceDecisionState.BLOCKED
    degraded = tuple(sorted({d.degraded_state_code for d in evidence.degradations}))
    return DependencyResilienceDecision(
        state=state,
        blockers=tuple(dict.fromkeys(blockers)),
        dependency_matrix_hash=evidence.dependency_matrix_hash,
        evidence_hash=stable_hash(_canonical_evidence(evidence)),
        degraded_modes=degraded,
    )

def assert_pr168_dependency_resilience_ready(
    evidence: DependencyResilienceEvidence,
) -> DependencyResilienceDecision:
    decision = evaluate_pr168_dependency_resilience(evidence)
    if not decision.review_ready:
        raise DependencyResilienceBlocked(decision)
    return decision

def stable_hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def _is_hash(value: str) -> bool:
    return bool(_SHA256_RE.fullmatch(value))

def _require_hash(name: str, value: str, blockers: list[str]) -> None:
    if not _is_hash(value):
        blockers.append(f"BAD_HASH:{name}")

def _has_dupes(values: Iterable[str]) -> bool:
    items = list(values)
    return len(set(items)) != len(items)

def _validate_top_level(evidence: DependencyResilienceEvidence, blockers: list[str]) -> None:
    _require_hash("dependency_matrix_hash", evidence.dependency_matrix_hash, blockers)
    _require_hash("readiness_policy_hash", evidence.readiness_policy_hash, blockers)
    _require_hash("alerting_policy_hash", evidence.alerting_policy_hash, blockers)

def _validate_catalog(catalog: tuple[DependencyCatalogEntry, ...], blockers: list[str]) -> None:
    if not catalog:
        blockers.append("MISSING_DEPENDENCY_CATALOG")
        return
    if _has_dupes(c.dependency_id for c in catalog):
        blockers.append("DUPLICATE_DEPENDENCY_ID")
    for entry in catalog:
        if not entry.dependency_id or not entry.purpose:
            blockers.append("CATALOG_ENTRY_MISSING_ID_OR_PURPOSE")
        for name in (
            "provider_identity_hash",
            "endpoint_identity_hash",
            "credential_ref_hash",
            "quota_policy_hash",
            "retry_policy_hash",
            "circuit_policy_hash",
            "consistency_contract_hash",
            "manual_override_policy_hash",
        ):
            _require_hash(f"catalog.{entry.dependency_id}.{name}", getattr(entry, name), blockers)
        if entry.timeout_ms <= 0:
            blockers.append(f"NON_POSITIVE_TIMEOUT:{entry.dependency_id}")
        if entry.maximum_outage_ms < 0:
            blockers.append(f"NEGATIVE_OUTAGE_WINDOW:{entry.dependency_id}")

def _validate_bulkheads(items: tuple[BulkheadEvidence, ...], blockers: list[str]) -> None:
    by_purpose = {item.purpose: item for item in items}
    for purpose in REQUIRED_BULKHEAD_PURPOSES:
        if purpose not in by_purpose:
            blockers.append(f"MISSING_BULKHEAD:{purpose}")
    if _has_dupes(item.purpose for item in items):
        blockers.append("DUPLICATE_BULKHEAD_PURPOSE")
    for item in items:
        _require_hash(f"bulkhead.{item.purpose}.policy_hash", item.policy_hash, blockers)
        if item.max_concurrent_tasks <= 0 or item.max_connections <= 0:
            blockers.append(f"UNBOUNDED_OR_ZERO_BULKHEAD:{item.purpose}")
        if item.max_memory_bytes <= 0 or item.queue_bound <= 0:
            blockers.append(f"MISSING_RESOURCE_BOUND:{item.purpose}")
        if not item.independent_pool:
            blockers.append(f"BULKHEAD_NOT_INDEPENDENT:{item.purpose}")
        if item.purpose in {"discovery", "webhook_backfill"} and not item.preserves_finalization_capacity:
            blockers.append(f"FINALIZATION_CAPACITY_NOT_PRESERVED:{item.purpose}")

def _validate_retry_budgets(items: tuple[RetryDeadlineBudget, ...], blockers: list[str]) -> None:
    if not items:
        blockers.append("MISSING_SHARED_RETRY_DEADLINE_BUDGET")
    if _has_dupes(item.operation_id for item in items):
        blockers.append("DUPLICATE_RETRY_BUDGET")
    for item in items:
        _require_hash(f"retry.{item.operation_id}.policy_hash", item.policy_hash, blockers)
        if item.absolute_deadline_ns <= item.issued_at_ns:
            blockers.append(f"BAD_ABSOLUTE_DEADLINE:{item.operation_id}")
        if item.expires_before_candidate_ns > item.absolute_deadline_ns:
            blockers.append(f"BUDGET_OUTLIVES_CANDIDATE:{item.operation_id}")
        if item.max_total_attempts <= 0:
            blockers.append(f"NO_ATTEMPT_BUDGET:{item.operation_id}")
        if item.max_provider_switches < 0 or item.max_cumulative_delay_ms < 0:
            blockers.append(f"NEGATIVE_RETRY_BUDGET:{item.operation_id}")
        if not item.nested_components_share_budget:
            blockers.append(f"NESTED_RETRIES_NOT_SHARED:{item.operation_id}")
        if item.retry_after_expiry_allowed:
            blockers.append(f"RETRY_AFTER_EXPIRY_ALLOWED:{item.operation_id}")

def _validate_circuits(items: tuple[CircuitBreakerEvidence, ...], blockers: list[str]) -> None:
    if not items:
        blockers.append("MISSING_CIRCUIT_BREAKERS")
    keys = [f"{item.dependency_id}:{item.purpose}" for item in items]
    if _has_dupes(keys):
        blockers.append("DUPLICATE_CIRCUIT_SCOPE")
    for item in items:
        _require_hash(f"circuit.{item.dependency_id}.{item.purpose}.policy_hash", item.policy_hash, blockers)
        if item.rolling_window_ms <= 0 or item.minimum_sample_count <= 1:
            blockers.append(f"CIRCUIT_NOT_ROLLING:{item.dependency_id}:{item.purpose}")
        if item.failure_rate_threshold_ppm <= 0 or item.slow_call_threshold_ppm <= 0:
            blockers.append(f"CIRCUIT_THRESHOLDS_MISSING:{item.dependency_id}:{item.purpose}")
        if item.half_open_concurrency <= 0:
            blockers.append(f"HALF_OPEN_PROBES_MISSING:{item.dependency_id}:{item.purpose}")
        if not item.exponential_open_duration or item.open_duration_cap_ms <= 0:
            blockers.append(f"OPEN_DURATION_NOT_BOUNDED:{item.dependency_id}:{item.purpose}")
        if not item.persisted_state or not item.persisted_last_cause:
            blockers.append(f"CIRCUIT_STATE_NOT_DURABLE:{item.dependency_id}:{item.purpose}")
        if not item.manual_force_open_supported:
            blockers.append(f"MANUAL_FORCE_OPEN_MISSING:{item.dependency_id}:{item.purpose}")
        if not item.resets_only_on_policy_change:
            blockers.append(f"CIRCUIT_RESETS_WITHOUT_POLICY_CHANGE:{item.dependency_id}:{item.purpose}")
        if not FATAL_FAILURES.issubset(set(item.differentiates_failures)):
            blockers.append(f"FATAL_FAILURES_NOT_DIFFERENTIATED:{item.dependency_id}:{item.purpose}")
        if item.fatal_failures_auto_recover_by_cooldown:
            blockers.append(f"FATAL_FAILURE_AUTO_RECOVERS:{item.dependency_id}:{item.purpose}")

def _validate_fallbacks(items: tuple[FallbackEvidence, ...], blockers: list[str]) -> None:
    if not items:
        blockers.append("MISSING_FALLBACK_EQUIVALENCE_EVIDENCE")
    for item in items:
        _require_hash(
            f"fallback.{item.source_dependency_id}.{item.fallback_dependency_id}.equivalence_hash",
            item.equivalence_hash,
            blockers,
        )
        if not item.same_security_domain:
            blockers.append(f"FALLBACK_SECURITY_DOMAIN_MISMATCH:{item.source_dependency_id}")
        if not item.same_economic_guarantees or not item.same_atomicity_role:
            blockers.append(f"FALLBACK_WEAKENS_ECONOMIC_OR_ATOMICITY:{item.source_dependency_id}")
        if not item.preserves_min_out or not item.preserves_slot_freshness:
            blockers.append(f"FALLBACK_WEAKENS_EXECUTION_PROOF:{item.source_dependency_id}")
        if not item.preserves_program_attestation:
            blockers.append(f"FALLBACK_DROPS_PROGRAM_ATTESTATION:{item.source_dependency_id}")
        for required, weaker in FORBIDDEN_FALLBACK_CAPABILITY_DROPS:
            if required in item.source_capabilities and weaker in item.fallback_capabilities:
                blockers.append(f"FORBIDDEN_FALLBACK_CAPABILITY_DROP:{required}->{weaker}")
        missing = sorted(set(item.source_capabilities) - set(item.fallback_capabilities))
        if missing:
            blockers.append(f"FALLBACK_CAPABILITY_NOT_EQUIVALENT:{item.source_dependency_id}:{','.join(missing)}")

def _validate_degradations(items: tuple[GracefulDegradationEvidence, ...], blockers: list[str]) -> None:
    required = {
        "optional_provider_down",
        "required_finalizer_down",
        "one_rpc_down",
        "signer_down",
        "alerting_down",
        "object_store_down",
        "backup_down",
    }
    seen = {item.scenario for item in items}
    for scenario in sorted(required - seen):
        blockers.append(f"MISSING_DEGRADATION_SCENARIO:{scenario}")
    for item in items:
        _require_hash(f"degradation.{item.scenario}.policy_hash", item.policy_hash, blockers)
        if not item.degraded_state_code:
            blockers.append(f"MISSING_DEGRADED_STATE:{item.scenario}")
        if item.scenario.startswith("optional") and not item.optional_loss_is_bounded:
            blockers.append(f"OPTIONAL_LOSS_NOT_BOUNDED:{item.scenario}")
        if "required" in item.scenario and not item.required_loss_blocks_trade:
            blockers.append(f"REQUIRED_LOSS_DOES_NOT_BLOCK_TRADE:{item.scenario}")
        if not item.settlement_capacity_preserved or not item.reconciliation_capacity_preserved:
            blockers.append(f"SETTLEMENT_RECONCILIATION_NOT_PRESERVED:{item.scenario}")
        if not item.finalization_capacity_preserved:
            blockers.append(f"FINALIZATION_NOT_PRESERVED:{item.scenario}")
        if not item.new_attempts_stopped_before_reconciliation:
            blockers.append(f"NEW_ATTEMPTS_NOT_STOPPED_FIRST:{item.scenario}")
        if not item.explicit_operator_alert:
            blockers.append(f"NO_OPERATOR_ALERT_FOR_DEGRADATION:{item.scenario}")

def _validate_outage_drills(items: tuple[OutageDrillEvidence, ...], blockers: list[str]) -> None:
    by_id = {item.drill_id: item for item in items}
    for drill in REQUIRED_OUTAGE_DRILLS:
        if drill not in by_id:
            blockers.append(f"MISSING_OUTAGE_DRILL:{drill}")
    for item in items:
        _require_hash(f"drill.{item.drill_id}.report_hash", item.report_hash, blockers)
        if not item.passed:
            blockers.append(f"OUTAGE_DRILL_FAILED:{item.drill_id}")
        if not (item.stable_memory and item.stable_fd and item.stable_queue):
            blockers.append(f"OUTAGE_DRILL_RESOURCE_UNSTABLE:{item.drill_id}")
        if not item.readiness_reflects_dependency_matrix:
            blockers.append(f"READINESS_IGNORES_DEPENDENCY_MATRIX:{item.drill_id}")
        if not item.alerting_reflects_dependency_matrix:
            blockers.append(f"ALERTING_IGNORES_DEPENDENCY_MATRIX:{item.drill_id}")

def _slot_dict(obj: object) -> dict[str, object]:
    result: dict[str, object] = {}
    for field in fields(obj):
        value = getattr(obj, field.name)
        if isinstance(value, StrEnum):
            result[field.name] = str(value)
        elif isinstance(value, frozenset):
            result[field.name] = sorted(str(item) for item in value)
        elif isinstance(value, tuple):
            result[field.name] = [str(item) if isinstance(item, StrEnum) else item for item in value]
        else:
            result[field.name] = value
    return result

def _canonical_evidence(evidence: DependencyResilienceEvidence) -> Mapping[str, object]:
    return {
        "catalog": [_slot_dict(entry) for entry in evidence.catalog],
        "bulkheads": [_slot_dict(entry) for entry in evidence.bulkheads],
        "retry_budgets": [_slot_dict(entry) for entry in evidence.retry_budgets],
        "circuits": [_slot_dict(entry) for entry in evidence.circuits],
        "fallbacks": [_slot_dict(entry) for entry in evidence.fallbacks],
        "degradations": [_slot_dict(entry) for entry in evidence.degradations],
        "outage_drills": [_slot_dict(entry) for entry in evidence.outage_drills],
        "dependency_matrix_hash": evidence.dependency_matrix_hash,
        "readiness_policy_hash": evidence.readiness_policy_hash,
        "alerting_policy_hash": evidence.alerting_policy_hash,
        "unresolved_blockers": list(evidence.unresolved_blockers),
    }
