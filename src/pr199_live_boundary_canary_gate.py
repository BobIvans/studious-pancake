"""PR-199 live boundary, canary and finality acceptance gate.

The pass-3 seven-PR roadmap defines PR-199 as the first minimal live boundary:
isolated signer, exactly-once intent, no-blind-retry submission, finalized
reconciliation, charged-fee accounting and hard canary latches.  This module is
an offline evidence validator only.  It never imports a signer backend, loads a
private key, submits a transaction or enables live trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Mapping

SCHEMA_VERSION = "pr199.live-boundary-canary-gate.v1"
PRODUCT_ID = "studious-pancake.pr199.live-boundary-canary-gate"
LIVE_CAPABILITY_ALLOWED = False
SIGNER_BACKEND_ALLOWED = False
SENDER_TRANSPORT_ALLOWED = False

MIN_BLOCKHEIGHT_VALIDITY_RECHECKS = 1
MIN_CRASH_DRILLS = 3
MAX_IN_FLIGHT_INTENTS = 1

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_STATUS_STATES = (
    "received",
    "pending",
    "landed",
    "finalized",
    "failed",
    "expired",
    "unknown",
)

REQUIRED_CRASH_DRILLS = (
    "crash_before_send",
    "timeout_after_provider_acceptance",
    "crash_after_send_before_db_commit",
)

REQUIRED_CANARY_BUDGETS = (
    "wallet_allowlist",
    "per_attempt_loss_lamports",
    "daily_loss_lamports",
    "one_in_flight_intent",
    "emergency_latch",
)


class PR199Requirement(StrEnum):
    """Reviewable acceptance requirements for PR-199."""

    ACCEPTED_PR198_EVIDENCE = "accepted_pr198_evidence"
    ISOLATED_SIGNER_POLICY = "isolated_signer_policy"
    DIGEST_AND_PAYLOAD_BINDING = "digest_and_payload_binding"
    ATOMIC_INTENT_CONSUMPTION = "atomic_intent_consumption"
    BLOCKHEIGHT_RECHECK_AND_NO_BLIND_RETRY = "blockheight_recheck_and_no_blind_retry"
    FINALIZED_RECONCILIATION = "finalized_reconciliation"
    FEE_ACCOUNTING_AND_LATCHES = "fee_accounting_and_latches"
    LIMITED_CANARY_BUDGETS = "limited_canary_budgets"


class PR199Failure(StrEnum):
    INVALID_EVIDENCE = "invalid_evidence"
    REQUIREMENT_BLOCKED = "requirement_blocked"


class PR199BoundaryError(RuntimeError):
    """Raised for malformed PR-199 evidence that cannot be evaluated."""

    def __init__(self, failure: PR199Failure, message: str) -> None:
        super().__init__(message)
        self.failure = failure


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """Content-addressed artifact reference for live-boundary evidence."""

    label: str
    sha256: str
    relative_path: str

    def __post_init__(self) -> None:
        identifier(self.label, "label")
        sha256_digest(self.sha256, "sha256")
        if not is_normalized_relative_path(self.relative_path):
            raise PR199BoundaryError(
                PR199Failure.INVALID_EVIDENCE,
                "evidence artifact path must be a normalized relative path",
            )

    @property
    def ref_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/evidence-ref",
                "label": self.label,
                "sha256": self.sha256,
                "relative_path": self.relative_path,
            }
        )


@dataclass(frozen=True, slots=True)
class SignerIsolationEvidence:
    """Evidence that the general runtime cannot access signing material."""

    separate_signer_process: bool
    runtime_has_private_key_bytes: bool
    signer_backend_importable_from_runtime: bool
    signer_has_general_internet_egress: bool
    signer_accepts_only_policy_permit: bool
    signer_rejects_unsigned_or_unbound_payload: bool
    signer_policy_hash: str
    signer_release_hash: str

    def __post_init__(self) -> None:
        sha256_digest(self.signer_policy_hash, "signer_policy_hash")
        sha256_digest(self.signer_release_hash, "signer_release_hash")

    @property
    def passed(self) -> bool:
        return (
            self.separate_signer_process
            and not self.runtime_has_private_key_bytes
            and not self.signer_backend_importable_from_runtime
            and not self.signer_has_general_internet_egress
            and self.signer_accepts_only_policy_permit
            and self.signer_rejects_unsigned_or_unbound_payload
        )

    @property
    def evidence_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/signer-isolation",
                "separate_signer_process": self.separate_signer_process,
                "runtime_has_private_key_bytes": self.runtime_has_private_key_bytes,
                "signer_backend_importable_from_runtime": self.signer_backend_importable_from_runtime,
                "signer_has_general_internet_egress": self.signer_has_general_internet_egress,
                "signer_accepts_only_policy_permit": self.signer_accepts_only_policy_permit,
                "signer_rejects_unsigned_or_unbound_payload": self.signer_rejects_unsigned_or_unbound_payload,
                "signer_policy_hash": self.signer_policy_hash,
                "signer_release_hash": self.signer_release_hash,
            }
        )


@dataclass(frozen=True, slots=True)
class DigestBindingEvidence:
    """Evidence that replay/mix-up of any digest field is rejected."""

    attempt_generation_message_bound: bool
    config_wallet_provider_market_bound: bool
    reservation_nonce_expiry_bound: bool
    local_signature_verification_passed: bool
    signed_payload_hash_matches_message: bool
    replay_field_mutation_rejections: int
    signer_request_digest: str
    signed_payload_digest: str

    def __post_init__(self) -> None:
        if self.replay_field_mutation_rejections < 1:
            raise PR199BoundaryError(
                PR199Failure.INVALID_EVIDENCE,
                "digest binding evidence must include at least one mutation rejection",
            )
        sha256_digest(self.signer_request_digest, "signer_request_digest")
        sha256_digest(self.signed_payload_digest, "signed_payload_digest")

    @property
    def passed(self) -> bool:
        return (
            self.attempt_generation_message_bound
            and self.config_wallet_provider_market_bound
            and self.reservation_nonce_expiry_bound
            and self.local_signature_verification_passed
            and self.signed_payload_hash_matches_message
            and self.replay_field_mutation_rejections > 0
        )

    @property
    def evidence_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/digest-binding",
                "attempt_generation_message_bound": self.attempt_generation_message_bound,
                "config_wallet_provider_market_bound": self.config_wallet_provider_market_bound,
                "reservation_nonce_expiry_bound": self.reservation_nonce_expiry_bound,
                "local_signature_verification_passed": self.local_signature_verification_passed,
                "signed_payload_hash_matches_message": self.signed_payload_hash_matches_message,
                "replay_field_mutation_rejections": self.replay_field_mutation_rejections,
                "signer_request_digest": self.signer_request_digest,
                "signed_payload_digest": self.signed_payload_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class IntentConsumptionEvidence:
    """Evidence that permit, reservation and submission intent are atomic."""

    atomic_permit_reservation_intent_consume: bool
    durable_before_first_network_byte: bool
    receipt_unique_per_message_hash: bool
    transport_receipt_ownership_conflicts: int
    outstanding_intents: int
    duplicate_send_recovery_proven: bool

    def __post_init__(self) -> None:
        for field in (
            "transport_receipt_ownership_conflicts",
            "outstanding_intents",
        ):
            value = getattr(self, field)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")

    @property
    def passed(self) -> bool:
        return (
            self.atomic_permit_reservation_intent_consume
            and self.durable_before_first_network_byte
            and self.receipt_unique_per_message_hash
            and self.transport_receipt_ownership_conflicts == 0
            and self.outstanding_intents <= MAX_IN_FLIGHT_INTENTS
            and self.duplicate_send_recovery_proven
        )

    @property
    def evidence_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/intent-consumption",
                "atomic_permit_reservation_intent_consume": self.atomic_permit_reservation_intent_consume,
                "durable_before_first_network_byte": self.durable_before_first_network_byte,
                "receipt_unique_per_message_hash": self.receipt_unique_per_message_hash,
                "transport_receipt_ownership_conflicts": self.transport_receipt_ownership_conflicts,
                "outstanding_intents": self.outstanding_intents,
                "duplicate_send_recovery_proven": self.duplicate_send_recovery_proven,
            }
        )


@dataclass(frozen=True, slots=True)
class SubmissionRecoveryEvidence:
    """Evidence for no-blind-retry send and ambiguous outcome recovery."""

    immediate_blockheight_recheck_count: int
    no_blind_retry_policy: bool
    one_atomic_flash_transaction: bool
    required_status_states: tuple[str, ...]
    crash_drills_passed: tuple[str, ...]
    history_search_used: bool
    finalized_transaction_fetch_used: bool
    jito_ack_treated_as_success: bool
    unknown_outcome_escalation_proven: bool

    def __post_init__(self) -> None:
        if self.immediate_blockheight_recheck_count < 0:
            raise ValueError("immediate_blockheight_recheck_count must be non-negative")
        object.__setattr__(self, "required_status_states", tuple(self.required_status_states))
        object.__setattr__(self, "crash_drills_passed", tuple(self.crash_drills_passed))
        for state in self.required_status_states:
            identifier(state, "required_status_state")
        for drill in self.crash_drills_passed:
            identifier(drill, "crash_drill")
        if len(set(self.required_status_states)) != len(self.required_status_states):
            raise PR199BoundaryError(
                PR199Failure.INVALID_EVIDENCE,
                "required status states must be unique",
            )
        if len(set(self.crash_drills_passed)) != len(self.crash_drills_passed):
            raise PR199BoundaryError(
                PR199Failure.INVALID_EVIDENCE,
                "crash drills must be unique",
            )

    @property
    def passed(self) -> bool:
        return (
            self.immediate_blockheight_recheck_count >= MIN_BLOCKHEIGHT_VALIDITY_RECHECKS
            and self.no_blind_retry_policy
            and self.one_atomic_flash_transaction
            and set(REQUIRED_STATUS_STATES).issubset(self.required_status_states)
            and set(REQUIRED_CRASH_DRILLS).issubset(self.crash_drills_passed)
            and self.history_search_used
            and self.finalized_transaction_fetch_used
            and not self.jito_ack_treated_as_success
            and self.unknown_outcome_escalation_proven
        )

    @property
    def evidence_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/submission-recovery",
                "immediate_blockheight_recheck_count": self.immediate_blockheight_recheck_count,
                "no_blind_retry_policy": self.no_blind_retry_policy,
                "one_atomic_flash_transaction": self.one_atomic_flash_transaction,
                "required_status_states": list(self.required_status_states),
                "crash_drills_passed": list(self.crash_drills_passed),
                "history_search_used": self.history_search_used,
                "finalized_transaction_fetch_used": self.finalized_transaction_fetch_used,
                "jito_ack_treated_as_success": self.jito_ack_treated_as_success,
                "unknown_outcome_escalation_proven": self.unknown_outcome_escalation_proven,
            }
        )


@dataclass(frozen=True, slots=True)
class FeeAndLatchEvidence:
    """Evidence for landed-failed fee accounting and fail-closed latches."""

    landed_failed_fee_accounted_from_finalized_meta: bool
    charged_fee_lamports: int
    projected_fee_lamports: int
    settled_native_delta_bound: bool
    failed_landing_profit_forced_zero: bool
    loss_latch_armed_on_fee_or_capital_violation: bool
    emergency_latch_clear_for_canary: bool

    def __post_init__(self) -> None:
        for field in ("charged_fee_lamports", "projected_fee_lamports"):
            value = getattr(self, field)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")

    @property
    def passed(self) -> bool:
        return (
            self.landed_failed_fee_accounted_from_finalized_meta
            and self.charged_fee_lamports >= self.projected_fee_lamports
            and self.settled_native_delta_bound
            and self.failed_landing_profit_forced_zero
            and self.loss_latch_armed_on_fee_or_capital_violation
            and self.emergency_latch_clear_for_canary
        )

    @property
    def evidence_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/fee-latch",
                "landed_failed_fee_accounted_from_finalized_meta": self.landed_failed_fee_accounted_from_finalized_meta,
                "charged_fee_lamports": self.charged_fee_lamports,
                "projected_fee_lamports": self.projected_fee_lamports,
                "settled_native_delta_bound": self.settled_native_delta_bound,
                "failed_landing_profit_forced_zero": self.failed_landing_profit_forced_zero,
                "loss_latch_armed_on_fee_or_capital_violation": self.loss_latch_armed_on_fee_or_capital_violation,
                "emergency_latch_clear_for_canary": self.emergency_latch_clear_for_canary,
            }
        )


@dataclass(frozen=True, slots=True)
class CanaryBudgetEvidence:
    """Evidence that any future canary is tiny, allowlisted and latch-bound."""

    budget_controls_present: tuple[str, ...]
    wallet_allowlist_hash: str
    max_per_attempt_loss_lamports: int
    max_daily_loss_lamports: int
    runtime_budget_override_possible: bool
    operator_approval_hash: str
    emergency_latch_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "budget_controls_present", tuple(self.budget_controls_present))
        for control in self.budget_controls_present:
            identifier(control, "budget_control")
        if len(set(self.budget_controls_present)) != len(self.budget_controls_present):
            raise PR199BoundaryError(
                PR199Failure.INVALID_EVIDENCE,
                "canary budget controls must be unique",
            )
        sha256_digest(self.wallet_allowlist_hash, "wallet_allowlist_hash")
        sha256_digest(self.operator_approval_hash, "operator_approval_hash")
        sha256_digest(self.emergency_latch_hash, "emergency_latch_hash")
        for field in ("max_per_attempt_loss_lamports", "max_daily_loss_lamports"):
            value = getattr(self, field)
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field} must be a positive integer")

    @property
    def passed(self) -> bool:
        return (
            set(REQUIRED_CANARY_BUDGETS).issubset(self.budget_controls_present)
            and self.max_per_attempt_loss_lamports <= self.max_daily_loss_lamports
            and not self.runtime_budget_override_possible
        )

    @property
    def evidence_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/canary-budget",
                "budget_controls_present": list(self.budget_controls_present),
                "wallet_allowlist_hash": self.wallet_allowlist_hash,
                "max_per_attempt_loss_lamports": self.max_per_attempt_loss_lamports,
                "max_daily_loss_lamports": self.max_daily_loss_lamports,
                "runtime_budget_override_possible": self.runtime_budget_override_possible,
                "operator_approval_hash": self.operator_approval_hash,
                "emergency_latch_hash": self.emergency_latch_hash,
            }
        )


@dataclass(frozen=True, slots=True)
class PR199LiveBoundaryEvidence:
    """Complete evidence envelope for PR-199 acceptance."""

    release_id: str
    pr198_evidence_hash: str
    pr198_sender_free_evidence_accepted: bool
    signer: SignerIsolationEvidence
    digest_binding: DigestBindingEvidence
    intent: IntentConsumptionEvidence
    recovery: SubmissionRecoveryEvidence
    fee_latch: FeeAndLatchEvidence
    canary: CanaryBudgetEvidence
    signed_evidence_package: EvidenceRef
    signer_policy_artifact: EvidenceRef
    reconciliation_artifact: EvidenceRef
    live_capability_enabled: bool = False
    signer_backend_enabled: bool = False
    sender_transport_enabled: bool = False

    def __post_init__(self) -> None:
        identifier(self.release_id, "release_id")
        sha256_digest(self.pr198_evidence_hash, "pr198_evidence_hash")

    @property
    def evidence_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/live-boundary-evidence",
                "release_id": self.release_id,
                "pr198_evidence_hash": self.pr198_evidence_hash,
                "pr198_sender_free_evidence_accepted": self.pr198_sender_free_evidence_accepted,
                "signer": self.signer.evidence_hash,
                "digest_binding": self.digest_binding.evidence_hash,
                "intent": self.intent.evidence_hash,
                "recovery": self.recovery.evidence_hash,
                "fee_latch": self.fee_latch.evidence_hash,
                "canary": self.canary.evidence_hash,
                "signed_evidence_package": self.signed_evidence_package.ref_hash,
                "signer_policy_artifact": self.signer_policy_artifact.ref_hash,
                "reconciliation_artifact": self.reconciliation_artifact.ref_hash,
                "live_capability_enabled": self.live_capability_enabled,
                "signer_backend_enabled": self.signer_backend_enabled,
                "sender_transport_enabled": self.sender_transport_enabled,
            }
        )


@dataclass(frozen=True, slots=True)
class PR199LiveBoundaryReport:
    """Deterministic PR-199 gate report."""

    schema_version: str
    product_id: str
    evidence_hash: str
    passed: bool
    requirement_results: Mapping[str, bool]
    blockers: tuple[str, ...]
    live_capability_allowed: bool = LIVE_CAPABILITY_ALLOWED
    signer_backend_allowed: bool = SIGNER_BACKEND_ALLOWED
    sender_transport_allowed: bool = SENDER_TRANSPORT_ALLOWED

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "product_id": self.product_id,
            "evidence_hash": self.evidence_hash,
            "passed": self.passed,
            "requirement_results": dict(sorted(self.requirement_results.items())),
            "blockers": list(self.blockers),
            "live_capability_allowed": self.live_capability_allowed,
            "signer_backend_allowed": self.signer_backend_allowed,
            "sender_transport_allowed": self.sender_transport_allowed,
        }

    @property
    def report_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr199/live-boundary-report",
                **self.to_json_dict(),
            }
        )


def evaluate_pr199_live_boundary(evidence: PR199LiveBoundaryEvidence) -> PR199LiveBoundaryReport:
    """Evaluate PR-199 live-boundary acceptance evidence without side effects."""

    blockers: list[str] = []
    results: dict[str, bool] = {}

    def record(requirement: PR199Requirement, condition: bool, message: str) -> None:
        results[requirement.value] = condition
        if not condition:
            blockers.append(f"{requirement.value}: {message}")

    record(
        PR199Requirement.ACCEPTED_PR198_EVIDENCE,
        evidence.pr198_sender_free_evidence_accepted,
        "PR-199 cannot start until PR-198 sender-free evidence is accepted",
    )
    record(
        PR199Requirement.ISOLATED_SIGNER_POLICY,
        evidence.signer.passed
        and not evidence.signer_backend_enabled
        and not evidence.live_capability_enabled,
        "runtime must not hold private keys or import signer backend",
    )
    record(
        PR199Requirement.DIGEST_AND_PAYLOAD_BINDING,
        evidence.digest_binding.passed,
        "signer request and signed payload must bind every reviewed digest field",
    )
    record(
        PR199Requirement.ATOMIC_INTENT_CONSUMPTION,
        evidence.intent.passed,
        "permit, reservation and submission intent must consume atomically",
    )
    record(
        PR199Requirement.BLOCKHEIGHT_RECHECK_AND_NO_BLIND_RETRY,
        evidence.recovery.immediate_blockheight_recheck_count
        >= MIN_BLOCKHEIGHT_VALIDITY_RECHECKS
        and evidence.recovery.no_blind_retry_policy
        and not evidence.sender_transport_enabled,
        "blockheight must be rechecked before sign/send and blind retries forbidden",
    )
    record(
        PR199Requirement.FINALIZED_RECONCILIATION,
        evidence.recovery.passed,
        "status history and finalized getTransaction must drive terminal truth",
    )
    record(
        PR199Requirement.FEE_ACCOUNTING_AND_LATCHES,
        evidence.fee_latch.passed,
        "failed landed transaction fee and loss/capital latches must be proven",
    )
    record(
        PR199Requirement.LIMITED_CANARY_BUDGETS,
        evidence.canary.passed
        and evidence.intent.outstanding_intents <= MAX_IN_FLIGHT_INTENTS
        and not evidence.live_capability_enabled,
        "canary must be allowlisted, one-in-flight and runtime-budget immutable",
    )

    return PR199LiveBoundaryReport(
        schema_version=SCHEMA_VERSION,
        product_id=PRODUCT_ID,
        evidence_hash=evidence.evidence_hash,
        passed=not blockers,
        requirement_results=results,
        blockers=tuple(blockers),
    )


def pr199_live_boundary_status_payload() -> dict[str, object]:
    """Return a stable fail-closed package-smoke payload."""

    return {
        "schema_version": SCHEMA_VERSION,
        "roadmap_pr": "PR-199",
        "seven_pr_scope": "isolated_signer_exactly_once_submission_finality_canary",
        "live_capability_allowed": LIVE_CAPABILITY_ALLOWED,
        "signer_backend_allowed": SIGNER_BACKEND_ALLOWED,
        "sender_transport_allowed": SENDER_TRANSPORT_ALLOWED,
        "required_status_states": list(REQUIRED_STATUS_STATES),
        "required_crash_drills": list(REQUIRED_CRASH_DRILLS),
        "required_canary_budgets": list(REQUIRED_CANARY_BUDGETS),
    }


def identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{field} must be a bounded structured identifier")
    return value


def sha256_digest(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value) or len(set(value)) == 1:
        raise ValueError(f"{field} must be a non-placeholder lowercase sha256")
    return value


def is_normalized_relative_path(path: str) -> bool:
    return (
        isinstance(path, str)
        and bool(path)
        and not path.startswith("/")
        and "\\" not in path
        and all(part not in {"", ".", ".."} for part in path.split("/"))
    )


def hash_json(payload: object) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()
