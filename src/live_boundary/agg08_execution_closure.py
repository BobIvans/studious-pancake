"""AGG-08 closure over existing signer, sender, lifecycle and settlement owners.

This module is deliberately default-off. It owns only the final integration
checks between already-accepted authorities; it does not own a private key,
network sender, capital store, lifecycle database, or economic ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re

from src.execution.core_v1_finalized_settlement import CoreV1FinalizedCommit
from src.execution.finalized_economic_ledger import FinalizedEconomicOutcome
from src.live_boundary.pr202_isolated_signer_settlement import (
    IsolatedSignerBoundaryEvidence,
    ReviewedPermit,
    TransportKind as ReviewedTransportKind,
)
from src.live_canary.models import CanaryMode, CanaryReport
from src.submission.permit_bound import (
    PermitRequest,
    SignedPayload,
    TransportKind,
    permit_request_from_payload,
)

AGG08_SCHEMA_VERSION = "agg08.execution-closure.v1"
AGG08_COMPILE_TIME_LIVE_ENABLED = False
AGG08_REQUIRED_FINANCING = ("slumlord",)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class Agg08Error(ValueError):
    """Stable, redaction-safe AGG-08 validation failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CoverageStatus(StrEnum):
    INTEGRATED = "integrated"
    REUSED = "reused"
    BLOCKED_PREREQUISITE = "blocked_prerequisite"


@dataclass(frozen=True, slots=True)
class ExecutionProfile:
    """Exact execution scope. This is not live authorization."""

    profile_id: str
    generation: int
    qualification_hash: str
    release_hash: str
    config_hash: str
    policy_hash: str
    risk_budget_hash: str
    cluster_genesis_hash: str
    wallet_pubkey: str
    asset_ids: tuple[str, ...]
    program_ids: tuple[str, ...]
    financing_ids: tuple[str, ...]
    route_ids: tuple[str, ...]
    transport: TransportKind
    max_principal_base_units: int
    max_native_debit_lamports: int
    max_tip_lamports: int
    failure_budget_lamports: int
    expires_at_ms: int
    required_financing_ids: tuple[str, ...] = AGG08_REQUIRED_FINANCING
    live_default_enabled: bool = False

    def __post_init__(self) -> None:
        _safe_id(self.profile_id, "profile_id")
        _positive_int(self.generation, "generation")
        for label, value in (
            ("qualification_hash", self.qualification_hash),
            ("release_hash", self.release_hash),
            ("config_hash", self.config_hash),
            ("policy_hash", self.policy_hash),
            ("risk_budget_hash", self.risk_budget_hash),
            ("cluster_genesis_hash", self.cluster_genesis_hash),
        ):
            _sha256(value, label)
        _nonblank(self.wallet_pubkey, "wallet_pubkey")
        for label, values in (
            ("asset_ids", self.asset_ids),
            ("program_ids", self.program_ids),
            ("financing_ids", self.financing_ids),
            ("route_ids", self.route_ids),
            ("required_financing_ids", self.required_financing_ids),
        ):
            _nonempty_unique(values, label)
        if not set(AGG08_REQUIRED_FINANCING).issubset(
            set(self.required_financing_ids)
        ):
            raise Agg08Error("AGG08_GLOBAL_FINANCING_REQUIREMENT_REMOVED")
        _positive_int(self.max_principal_base_units, "max_principal_base_units")
        _positive_int(self.max_native_debit_lamports, "max_native_debit_lamports")
        _nonnegative_int(self.max_tip_lamports, "max_tip_lamports")
        _positive_int(self.failure_budget_lamports, "failure_budget_lamports")
        _positive_int(self.expires_at_ms, "expires_at_ms")
        if self.max_tip_lamports > self.max_native_debit_lamports:
            raise Agg08Error("AGG08_TIP_EXCEEDS_NATIVE_DEBIT_CAP")
        if self.live_default_enabled:
            raise Agg08Error("AGG08_LIVE_MUST_DEFAULT_OFF")

    @property
    def profile_hash(self) -> str:
        return _hash_json(
            {
                "schema_version": AGG08_SCHEMA_VERSION,
                "profile_id": self.profile_id,
                "generation": self.generation,
                "qualification_hash": self.qualification_hash,
                "release_hash": self.release_hash,
                "config_hash": self.config_hash,
                "policy_hash": self.policy_hash,
                "risk_budget_hash": self.risk_budget_hash,
                "cluster_genesis_hash": self.cluster_genesis_hash,
                "wallet_pubkey": self.wallet_pubkey,
                "asset_ids": self.asset_ids,
                "program_ids": self.program_ids,
                "financing_ids": self.financing_ids,
                "route_ids": self.route_ids,
                "transport": self.transport.value,
                "max_principal_base_units": self.max_principal_base_units,
                "max_native_debit_lamports": self.max_native_debit_lamports,
                "max_tip_lamports": self.max_tip_lamports,
                "failure_budget_lamports": self.failure_budget_lamports,
                "expires_at_ms": self.expires_at_ms,
                "required_financing_ids": self.required_financing_ids,
                "live_default_enabled": False,
            }
        )


@dataclass(frozen=True, slots=True)
class AuthorizationRecord:
    """Evidence emitted by an existing human/release authorization authority."""

    authorization_id: str
    actor_id: str
    source_reference: str
    profile_hash: str
    qualification_hash: str
    release_hash: str
    risk_budget_hash: str
    reviewer_hash: str
    wallet_pubkey: str
    cluster_genesis_hash: str
    maximum_native_debit_lamports: int
    issued_at_ms: int
    expires_at_ms: int
    allow_sign: bool
    allow_submit: bool
    revoked: bool = False

    def __post_init__(self) -> None:
        _safe_id(self.authorization_id, "authorization_id")
        _safe_id(self.actor_id, "actor_id")
        _nonblank(self.source_reference, "source_reference")
        for label, value in (
            ("profile_hash", self.profile_hash),
            ("qualification_hash", self.qualification_hash),
            ("release_hash", self.release_hash),
            ("risk_budget_hash", self.risk_budget_hash),
            ("reviewer_hash", self.reviewer_hash),
            ("cluster_genesis_hash", self.cluster_genesis_hash),
        ):
            _sha256(value, label)
        _nonblank(self.wallet_pubkey, "wallet_pubkey")
        _positive_int(
            self.maximum_native_debit_lamports,
            "maximum_native_debit_lamports",
        )
        _nonnegative_int(self.issued_at_ms, "issued_at_ms")
        _positive_int(self.expires_at_ms, "expires_at_ms")
        if self.expires_at_ms <= self.issued_at_ms:
            raise Agg08Error("AGG08_AUTH_EXPIRY_NOT_AFTER_ISSUE")


@dataclass(frozen=True, slots=True)
class FreshExecutionEvidence:
    """Effect-adjacent state, budget, and exact-message binding."""

    attempt_id: str
    profile_generation: int
    qualification_hash: str
    release_hash: str
    config_hash: str
    policy_hash: str
    risk_budget_hash: str
    cluster_genesis_hash: str
    wallet_pubkey: str
    asset_ids: tuple[str, ...]
    program_ids: tuple[str, ...]
    financing_ids: tuple[str, ...]
    route_id: str
    candidate_hash: str
    plan_hash: str
    state_frame_hash: str
    message_hash: str
    exact_simulation_hash: str
    blockhash: str
    repayment_evidence_hash: str
    principal_base_units: int
    failure_cost_lamports: int
    available_native_lamports: int
    other_active_reserved_lamports: int
    reserved_for_attempt_lamports: int
    requested_native_debit_lamports: int
    tip_lamports: int
    observed_at_ms: int
    expires_at_ms: int
    unresolved_attempt_ids: tuple[str, ...] = ()
    kill_switch_active: bool = False

    def __post_init__(self) -> None:
        _safe_id(self.attempt_id, "attempt_id")
        _positive_int(self.profile_generation, "profile_generation")
        for label, value in (
            ("qualification_hash", self.qualification_hash),
            ("release_hash", self.release_hash),
            ("config_hash", self.config_hash),
            ("policy_hash", self.policy_hash),
            ("risk_budget_hash", self.risk_budget_hash),
            ("cluster_genesis_hash", self.cluster_genesis_hash),
            ("candidate_hash", self.candidate_hash),
            ("plan_hash", self.plan_hash),
            ("state_frame_hash", self.state_frame_hash),
            ("message_hash", self.message_hash),
            ("exact_simulation_hash", self.exact_simulation_hash),
            ("repayment_evidence_hash", self.repayment_evidence_hash),
        ):
            _sha256(value, label)
        _nonblank(self.wallet_pubkey, "wallet_pubkey")
        for label, values in (
            ("asset_ids", self.asset_ids),
            ("program_ids", self.program_ids),
            ("financing_ids", self.financing_ids),
        ):
            _nonempty_unique(values, label)
        _nonblank(self.route_id, "route_id")
        _nonblank(self.blockhash, "blockhash")
        for label, value in (
            ("principal_base_units", self.principal_base_units),
            ("failure_cost_lamports", self.failure_cost_lamports),
            ("available_native_lamports", self.available_native_lamports),
            ("other_active_reserved_lamports", self.other_active_reserved_lamports),
            ("reserved_for_attempt_lamports", self.reserved_for_attempt_lamports),
            ("requested_native_debit_lamports", self.requested_native_debit_lamports),
            ("tip_lamports", self.tip_lamports),
            ("observed_at_ms", self.observed_at_ms),
        ):
            _nonnegative_int(value, label)
        _positive_int(self.expires_at_ms, "expires_at_ms")
        for attempt_id in self.unresolved_attempt_ids:
            _safe_id(attempt_id, "unresolved_attempt_id")


@dataclass(frozen=True, slots=True)
class CanaryReservationEvidence:
    """Identity captured from the existing canary reservation owner."""

    attempt_id: str
    message_hash: str
    candidate_hash: str
    reserved_at_ms: int

    def __post_init__(self) -> None:
        _safe_id(self.attempt_id, "attempt_id")
        _sha256(self.message_hash, "message_hash")
        _sha256(self.candidate_hash, "candidate_hash")
        _nonnegative_int(self.reserved_at_ms, "reserved_at_ms")


@dataclass(frozen=True, slots=True)
class PreSignAdmission:
    schema_version: str
    accepted: bool
    attempt_id: str
    profile_hash: str
    permit_hash: str
    message_hash: str
    evaluated_at_ms: int
    expires_at_ms: int
    blockers: tuple[str, ...]
    effect_gate_enabled: bool

    @property
    def decision_hash(self) -> str:
        return _hash_json(
            {
                "schema_version": self.schema_version,
                "accepted": self.accepted,
                "attempt_id": self.attempt_id,
                "profile_hash": self.profile_hash,
                "permit_hash": self.permit_hash,
                "message_hash": self.message_hash,
                "evaluated_at_ms": self.evaluated_at_ms,
                "expires_at_ms": self.expires_at_ms,
                "blockers": self.blockers,
                "effect_gate_enabled": self.effect_gate_enabled,
            }
        )


class Agg08ExecutionGate:
    """Final admission consumer; no key, sender, or database is owned here."""

    def __init__(
        self,
        *,
        effect_gate_enabled: bool = AGG08_COMPILE_TIME_LIVE_ENABLED,
    ) -> None:
        self.effect_gate_enabled = effect_gate_enabled

    def admit_pre_sign(
        self,
        *,
        profile: ExecutionProfile,
        authorization: AuthorizationRecord,
        permit: ReviewedPermit,
        signer_boundary: IsolatedSignerBoundaryEvidence,
        canary_report: CanaryReport,
        canary_reservation: CanaryReservationEvidence,
        evidence: FreshExecutionEvidence,
        now_ms: int,
    ) -> PreSignAdmission:
        _nonnegative_int(now_ms, "now_ms")
        blockers: list[str] = []

        if not self.effect_gate_enabled:
            blockers.append("AGG08_EFFECT_GATE_CLOSED")
        missing = sorted(
            set(profile.required_financing_ids) - set(profile.financing_ids)
        )
        blockers.extend(
            f"AGG08_REQUIRED_FINANCING_NOT_QUALIFIED:{item}" for item in missing
        )
        if now_ms >= profile.expires_at_ms:
            blockers.append("AGG08_PROFILE_EXPIRED")

        if authorization.revoked:
            blockers.append("AGG08_AUTH_REVOKED")
        if not authorization.allow_sign:
            blockers.append("AGG08_SIGN_NOT_AUTHORIZED")
        if not authorization.allow_submit:
            blockers.append("AGG08_SUBMIT_NOT_AUTHORIZED")
        if not authorization.issued_at_ms <= now_ms < authorization.expires_at_ms:
            blockers.append("AGG08_AUTH_NOT_CURRENT")
        for actual, expected, code in (
            (
                authorization.profile_hash,
                profile.profile_hash,
                "AGG08_AUTH_PROFILE_MISMATCH",
            ),
            (
                authorization.qualification_hash,
                profile.qualification_hash,
                "AGG08_AUTH_QUALIFICATION_MISMATCH",
            ),
            (
                authorization.release_hash,
                profile.release_hash,
                "AGG08_AUTH_RELEASE_MISMATCH",
            ),
            (
                authorization.risk_budget_hash,
                profile.risk_budget_hash,
                "AGG08_AUTH_RISK_BUDGET_MISMATCH",
            ),
            (
                authorization.reviewer_hash,
                permit.reviewer_hash,
                "AGG08_AUTH_REVIEWER_MISMATCH",
            ),
            (
                authorization.wallet_pubkey,
                profile.wallet_pubkey,
                "AGG08_AUTH_WALLET_MISMATCH",
            ),
            (
                authorization.cluster_genesis_hash,
                profile.cluster_genesis_hash,
                "AGG08_AUTH_CLUSTER_MISMATCH",
            ),
        ):
            _mismatch(blockers, actual, expected, code)

        signer = signer_boundary.evaluate()
        if not bool(signer["signer_boundary_healthy"]):
            blockers.extend(str(item) for item in signer["blockers"])
        _mismatch(
            blockers,
            signer_boundary.release_hash,
            profile.release_hash,
            "AGG08_SIGNER_RELEASE_MISMATCH",
        )
        _mismatch(
            blockers,
            permit.signer_service_id,
            signer_boundary.signer_service_id,
            "AGG08_SIGNER_SERVICE_MISMATCH",
        )

        if not canary_report.armed or canary_report.mode is not CanaryMode.LIMITED_LIVE:
            blockers.append("AGG08_CANARY_NOT_ARMED")
        if (
            canary_report.armed_until_ms is None
            or now_ms >= canary_report.armed_until_ms
        ):
            blockers.append("AGG08_CANARY_ARM_EXPIRED")
        if canary_report.ai_authority:
            blockers.append("AGG08_AI_AUTHORITY_FORBIDDEN")
        if canary_report.active_latches:
            blockers.append("AGG08_ACTIVE_KILL_OR_RISK_LATCH")
        if canary_report.outstanding_attempt_id != canary_reservation.attempt_id:
            blockers.append("AGG08_CANARY_REPORT_RESERVATION_MISMATCH")
        for actual, expected, code in (
            (
                canary_reservation.attempt_id,
                permit.attempt_id,
                "AGG08_RESERVATION_ATTEMPT_MISMATCH",
            ),
            (
                canary_reservation.message_hash,
                evidence.message_hash,
                "AGG08_RESERVATION_MESSAGE_MISMATCH",
            ),
            (
                canary_reservation.candidate_hash,
                evidence.candidate_hash,
                "AGG08_RESERVATION_CANDIDATE_MISMATCH",
            ),
        ):
            _mismatch(blockers, actual, expected, code)
        _mismatch(
            blockers,
            canary_report.policy_hash,
            profile.policy_hash,
            "AGG08_CANARY_POLICY_MISMATCH",
        )
        _mismatch(
            blockers,
            canary_report.evidence_hash,
            profile.qualification_hash,
            "AGG08_CANARY_QUALIFICATION_MISMATCH",
        )

        if permit.expires_at_ms <= now_ms:
            blockers.append("AGG08_REVIEWED_PERMIT_EXPIRED")
        for actual, expected, code in (
            (
                permit.release_hash,
                profile.release_hash,
                "AGG08_PERMIT_RELEASE_MISMATCH",
            ),
            (
                permit.config_hash,
                profile.config_hash,
                "AGG08_PERMIT_CONFIG_MISMATCH",
            ),
            (
                permit.policy_hash,
                profile.policy_hash,
                "AGG08_PERMIT_POLICY_MISMATCH",
            ),
            (
                permit.risk_budget_hash,
                profile.risk_budget_hash,
                "AGG08_PERMIT_RISK_BUDGET_MISMATCH",
            ),
            (
                permit.attempt_id,
                evidence.attempt_id,
                "AGG08_PERMIT_ATTEMPT_MISMATCH",
            ),
            (
                permit.plan_hash,
                evidence.plan_hash,
                "AGG08_PERMIT_PLAN_MISMATCH",
            ),
            (
                permit.message_hash,
                evidence.message_hash,
                "AGG08_PERMIT_MESSAGE_MISMATCH",
            ),
            (
                permit.blockhash,
                evidence.blockhash,
                "AGG08_PERMIT_BLOCKHASH_MISMATCH",
            ),
        ):
            _mismatch(blockers, actual, expected, code)
        if _submission_transport(permit.transport) is not profile.transport:
            blockers.append("AGG08_PERMIT_TRANSPORT_MISMATCH")
        if permit.tip_lamports != evidence.tip_lamports:
            blockers.append("AGG08_PERMIT_TIP_MISMATCH")

        if evidence.profile_generation != profile.generation:
            blockers.append("AGG08_PROFILE_GENERATION_STALE")
        for actual, expected, code in (
            (
                evidence.qualification_hash,
                profile.qualification_hash,
                "AGG08_QUALIFICATION_STALE",
            ),
            (evidence.release_hash, profile.release_hash, "AGG08_RELEASE_STALE"),
            (evidence.config_hash, profile.config_hash, "AGG08_CONFIG_STALE"),
            (evidence.policy_hash, profile.policy_hash, "AGG08_POLICY_STALE"),
            (
                evidence.risk_budget_hash,
                profile.risk_budget_hash,
                "AGG08_RISK_BUDGET_STALE",
            ),
            (
                evidence.cluster_genesis_hash,
                profile.cluster_genesis_hash,
                "AGG08_CLUSTER_STALE",
            ),
            (evidence.wallet_pubkey, profile.wallet_pubkey, "AGG08_WALLET_STALE"),
        ):
            _mismatch(blockers, actual, expected, code)
        if evidence.message_hash != evidence.exact_simulation_hash:
            blockers.append("AGG08_MESSAGE_NOT_EXACT_SIMULATION")
        if evidence.kill_switch_active:
            blockers.append("AGG08_KILL_SWITCH_ACTIVE")
        if evidence.unresolved_attempt_ids:
            blockers.append("AGG08_UNRESOLVED_OUTCOME_PRESENT")
        if not evidence.observed_at_ms <= now_ms < evidence.expires_at_ms:
            blockers.append("AGG08_FRESH_EVIDENCE_EXPIRED")

        if not set(evidence.asset_ids).issubset(profile.asset_ids):
            blockers.append("AGG08_ASSET_SCOPE_MISMATCH")
        if not set(evidence.program_ids).issubset(profile.program_ids):
            blockers.append("AGG08_PROGRAM_SCOPE_MISMATCH")
        if not set(evidence.financing_ids).issubset(profile.financing_ids):
            blockers.append("AGG08_FINANCING_SCOPE_MISMATCH")
        if evidence.route_id not in profile.route_ids:
            blockers.append("AGG08_ROUTE_SCOPE_MISMATCH")
        if evidence.principal_base_units > profile.max_principal_base_units:
            blockers.append("AGG08_PRINCIPAL_CAP")
        if evidence.failure_cost_lamports > profile.failure_budget_lamports:
            blockers.append("AGG08_FAILURE_BUDGET_CAP")
        if evidence.requested_native_debit_lamports > profile.max_native_debit_lamports:
            blockers.append("AGG08_PROFILE_NATIVE_DEBIT_CAP")
        if (
            evidence.requested_native_debit_lamports
            > authorization.maximum_native_debit_lamports
        ):
            blockers.append("AGG08_AUTH_NATIVE_DEBIT_CAP")
        if evidence.tip_lamports > profile.max_tip_lamports:
            blockers.append("AGG08_TIP_CAP")
        if (
            evidence.reserved_for_attempt_lamports
            < evidence.requested_native_debit_lamports
        ):
            blockers.append("AGG08_ATTEMPT_RESERVATION_TOO_SMALL")
        if (
            evidence.other_active_reserved_lamports
            + evidence.reserved_for_attempt_lamports
            > evidence.available_native_lamports
        ):
            blockers.append("AGG08_TOTAL_RESERVATIONS_EXCEED_BALANCE")

        unique = tuple(dict.fromkeys(blockers))
        arm_expiry = canary_report.armed_until_ms or 0
        admission_expiry = min(
            profile.expires_at_ms,
            authorization.expires_at_ms,
            permit.expires_at_ms,
            evidence.expires_at_ms,
            arm_expiry,
        )
        return PreSignAdmission(
            schema_version=AGG08_SCHEMA_VERSION,
            accepted=not unique,
            attempt_id=evidence.attempt_id,
            profile_hash=profile.profile_hash,
            permit_hash=permit.permit_hash,
            message_hash=evidence.message_hash,
            evaluated_at_ms=now_ms,
            expires_at_ms=admission_expiry,
            blockers=unique,
            effect_gate_enabled=self.effect_gate_enabled,
        )


def build_submission_permit_request(
    *,
    admission: PreSignAdmission,
    reviewed_permit: ReviewedPermit,
    signed_payload: SignedPayload,
    exact_simulation_hash: str,
    now_ms: int,
    expires_at_ns: int,
    last_valid_block_height: int,
    min_context_slot: int,
) -> PermitRequest:
    """Bind signed bytes to the existing one-time submission permit contract."""

    _nonnegative_int(now_ms, "now_ms")
    if not admission.accepted:
        raise Agg08Error("AGG08_PRE_SIGN_ADMISSION_REQUIRED")
    if admission.evaluated_at_ms != now_ms:
        raise Agg08Error("AGG08_EFFECT_REVALIDATION_REQUIRED")
    if now_ms >= admission.expires_at_ms:
        raise Agg08Error("AGG08_ADMISSION_EXPIRED")
    if admission.permit_hash != reviewed_permit.permit_hash:
        raise Agg08Error("AGG08_REVIEWED_PERMIT_CHANGED_AFTER_ADMISSION")
    if admission.message_hash != signed_payload.primary_message_hash:
        raise Agg08Error("AGG08_SIGNED_MESSAGE_MISMATCH")
    if exact_simulation_hash != admission.message_hash:
        raise Agg08Error("AGG08_POST_SIGN_SIMULATION_MISMATCH")
    transport = _submission_transport(reviewed_permit.transport)
    if (
        transport is TransportKind.JITO_BUNDLE
        and len(signed_payload.message_hashes) != 1
    ):
        raise Agg08Error("AGG08_MULTI_TX_BUNDLE_REQUIRES_SEPARATE_REVIEW")
    if transport in {TransportKind.JITO_SINGLE, TransportKind.JITO_BUNDLE}:
        tip = signed_payload.tip_evidence
        if tip is None or tip.lamports != reviewed_permit.tip_lamports:
            raise Agg08Error("AGG08_SIGNED_TIP_MISMATCH")
    elif reviewed_permit.tip_lamports != 0 or signed_payload.tip_evidence is not None:
        raise Agg08Error("AGG08_RPC_PAYLOAD_MUST_NOT_CARRY_JITO_TIP")
    if expires_at_ns > reviewed_permit.expires_at_ms * 1_000_000:
        raise Agg08Error("AGG08_SUBMISSION_PERMIT_OUTLIVES_REVIEW")
    if expires_at_ns > admission.expires_at_ms * 1_000_000:
        raise Agg08Error("AGG08_SUBMISSION_PERMIT_OUTLIVES_ADMISSION")
    return permit_request_from_payload(
        attempt_id=reviewed_permit.attempt_id,
        transport=transport,
        exact_simulation_hash=exact_simulation_hash,
        payload=signed_payload,
        expires_at_ns=expires_at_ns,
        last_valid_block_height=last_valid_block_height,
        min_context_slot=min_context_slot,
    )


@dataclass(frozen=True, slots=True)
class FinalizedLandingLabel:
    """Observed-finalized label derived only from Core-V1/MPR-2610 evidence."""

    attempt_id: str
    message_hash: str
    primary_signature: str
    finalized_slot: int
    source_hash: str
    ledger_hash: str
    outcome: str
    economically_successful: bool
    landed_finalized: bool = True

    @property
    def label_hash(self) -> str:
        return _hash_json(
            {
                "attempt_id": self.attempt_id,
                "message_hash": self.message_hash,
                "primary_signature": self.primary_signature,
                "finalized_slot": self.finalized_slot,
                "source_hash": self.source_hash,
                "ledger_hash": self.ledger_hash,
                "outcome": self.outcome,
                "economically_successful": self.economically_successful,
                "landed_finalized": self.landed_finalized,
            }
        )


def finalized_landing_label(commit: CoreV1FinalizedCommit) -> FinalizedLandingLabel:
    """Reject nonterminal/unknown economics before creating a real landing label."""

    if commit.ledger.outcome in {
        FinalizedEconomicOutcome.UNKNOWN_QUARANTINED,
        FinalizedEconomicOutcome.FINALIZED_PENDING_ECONOMICS,
    }:
        raise Agg08Error("AGG08_FINALIZED_TERMINAL_ECONOMICS_REQUIRED")
    lineage = commit.ledger.lineage
    return FinalizedLandingLabel(
        attempt_id=lineage.attempt_id,
        message_hash=lineage.message_hash,
        primary_signature=lineage.primary_signature,
        finalized_slot=lineage.finalized_slot,
        source_hash=commit.source_hash,
        ledger_hash=commit.ledger.ledger_hash,
        outcome=commit.ledger.outcome.value,
        economically_successful=commit.ledger.economically_successful,
    )


@dataclass(frozen=True, slots=True)
class CoverageRow:
    nf: str
    owner: str
    status: CoverageStatus
    note: str


def agg08_static_coverage() -> tuple[CoverageRow, ...]:
    """Map every AGG-08 NF to its canonical owner without claiming live proof."""

    specs = (
        ("NF-194", "agg08 gate", CoverageStatus.INTEGRATED, "exact profile"),
        ("NF-195", "agg08 gate", CoverageStatus.INTEGRATED, "authorization"),
        ("NF-196", "live_canary", CoverageStatus.REUSED, "first-live caps"),
        ("NF-198", "mpr2608/pr202", CoverageStatus.REUSED, "isolated signer"),
        ("NF-199", "agg08 gate", CoverageStatus.INTEGRATED, "pre-sign recheck"),
        (
            "NF-200",
            "DurableCapitalCoordinator/live_canary",
            CoverageStatus.REUSED,
            "execution reservation",
        ),
        ("NF-201", "pr202/permit_bound", CoverageStatus.REUSED, "one-use permit"),
        ("NF-202", "mpr2608", CoverageStatus.REUSED, "exact signing"),
        ("NF-203", "submission durable", CoverageStatus.REUSED, "dispatch intent"),
        ("NF-204", "RpcSender", CoverageStatus.REUSED, "RPC ACK semantics"),
        ("NF-205", "JitoSender", CoverageStatus.REUSED, "Jito transport"),
        ("NF-206", "canonical sender", CoverageStatus.REUSED, "no blind fallback"),
        ("NF-207", "status clients", CoverageStatus.REUSED, "finality states"),
        (
            "NF-208",
            "lifecycle integration",
            CoverageStatus.REUSED,
            "unknown recovery",
        ),
        (
            "NF-209",
            "CoreV1FinalizedSettlementProducer",
            CoverageStatus.REUSED,
            "finalized deltas",
        ),
        ("NF-210", "MPR-2610", CoverageStatus.REUSED, "actual rebates/postings"),
        (
            "NF-211",
            "lifecycle/capital owner",
            CoverageStatus.REUSED,
            "terminal release",
        ),
        ("NF-212", "MPR-2610 lineage", CoverageStatus.REUSED, "execution analysis"),
        ("NF-213", "agg08 label", CoverageStatus.INTEGRATED, "real landing label"),
        ("NF-214", "live_canary", CoverageStatus.REUSED, "emergency stop"),
        (
            "NF-215",
            "qualification generations",
            CoverageStatus.BLOCKED_PREREQUISITE,
            "each expansion needs a new qualified profile",
        ),
    )
    return tuple(CoverageRow(*spec) for spec in specs)


def _submission_transport(value: ReviewedTransportKind) -> TransportKind:
    return {
        ReviewedTransportKind.RPC_SINGLE: TransportKind.RPC,
        ReviewedTransportKind.JITO_SINGLE: TransportKind.JITO_SINGLE,
        ReviewedTransportKind.JITO_BUNDLE: TransportKind.JITO_BUNDLE,
    }[value]


def _mismatch(blockers: list[str], actual: object, expected: object, code: str) -> None:
    if actual != expected:
        blockers.append(code)


def _hash_json(value: object) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise Agg08Error(f"AGG08_INVALID_SHA256:{label}")


def _safe_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise Agg08Error(f"AGG08_INVALID_ID:{label}")


def _nonblank(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise Agg08Error(f"AGG08_BLANK:{label}")


def _nonempty_unique(values: tuple[str, ...], label: str) -> None:
    if not values or len(values) != len(set(values)):
        raise Agg08Error(f"AGG08_INVALID_SET:{label}")
    for value in values:
        _nonblank(value, label)


def _nonnegative_int(value: int, label: str) -> None:
    if type(value) is not int or value < 0:
        raise Agg08Error(f"AGG08_INVALID_NONNEGATIVE_INT:{label}")


def _positive_int(value: int, label: str) -> None:
    if type(value) is not int or value <= 0:
        raise Agg08Error(f"AGG08_INVALID_POSITIVE_INT:{label}")


__all__ = [
    "AGG08_COMPILE_TIME_LIVE_ENABLED",
    "AGG08_REQUIRED_FINANCING",
    "AGG08_SCHEMA_VERSION",
    "Agg08Error",
    "Agg08ExecutionGate",
    "AuthorizationRecord",
    "CanaryReservationEvidence",
    "CoverageRow",
    "CoverageStatus",
    "ExecutionProfile",
    "FinalizedLandingLabel",
    "FreshExecutionEvidence",
    "PreSignAdmission",
    "agg08_static_coverage",
    "build_submission_permit_request",
    "finalized_landing_label",
]
