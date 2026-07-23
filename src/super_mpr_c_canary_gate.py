"""SUPER-MPR-C isolated signer and permit-bound canary gate.

Offline acceptance contract only: it does not load keys, sign transactions, call
RPC/Jito/providers, submit transactions or enable live trading.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Iterable

SUPER_MPR_C_SCHEMA_VERSION = "super-mpr-c.one-transaction-canary.v1"
SUPER_MPR_C_READY = "super_mpr_c_canary_gate_ready"
SUPER_MPR_C_BLOCKED = "blocked_super_mpr_c_canary_gate"
SUPER_MPR_C_DEPENDENCY_GATED = "blocked_super_mpr_c_dependencies_incomplete"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class SuperMprCError(ValueError):
    """Invalid canary evidence."""


class CanaryGateState(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    BLOCKED_DEPENDENCY_GATED = "BLOCKED_DEPENDENCY_GATED"


class TransportKind(StrEnum):
    RPC = "rpc"
    JITO = "jito"


class JitoBundleStatus(StrEnum):
    NONE = "none"
    ACKED = "acked"
    LANDED = "landed"
    UNCLED = "uncled"
    REBROADCAST = "rebroadcast"


class KillCondition(StrEnum):
    PROVIDER_DRIFT = "provider_drift"
    RPC_DISAGREEMENT = "rpc_disagreement"
    SETTLEMENT_TIMEOUT = "settlement_timeout"
    UNEXPECTED_BALANCE_DELTA = "unexpected_balance_delta"
    DUPLICATE_SUBMISSION = "duplicate_submission"
    PERMIT_REPLAY = "permit_replay"
    FEE_TIP_BUDGET_EXCEEDED = "fee_tip_budget_exceeded"
    PROGRAM_ACCOUNT_DIGEST_MISMATCH = "program_account_digest_mismatch"
    MANUAL_KILL = "manual_kill"


def digest_payload(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _sha(value: str | None, name: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise SuperMprCError(f"{name} must be sha256")
    return value


def _text(value: str | None, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SuperMprCError(f"{name} is required")
    return value


def _utc(value: str, name: str) -> str:
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        raise SuperMprCError(f"{name} must be UTC ISO timestamp")
    return value


def _nonneg(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SuperMprCError(f"{name} must be non-negative int")
    return value


def _unique(values: Iterable[str], name: str) -> tuple[str, ...]:
    items = tuple(_text(item, name) for item in values)
    if not items or len(items) != len(set(items)):
        raise SuperMprCError(f"{name} must be a non-empty unique sequence")
    return items


@dataclass(frozen=True, slots=True)
class SuperMprDependencyEvidence:
    super_mpr_a_complete: bool
    super_mpr_b_complete: bool
    super_mpr_a_artifact_digest: str | None = None
    super_mpr_b_artifact_digest: str | None = None

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.super_mpr_a_complete:
            blockers.append("super_mpr_a_incomplete")
        elif self.super_mpr_a_artifact_digest is None:
            blockers.append("super_mpr_a_artifact_missing")
        else:
            _sha(self.super_mpr_a_artifact_digest, "super_mpr_a_artifact_digest")
        if not self.super_mpr_b_complete:
            blockers.append("super_mpr_b_incomplete")
        elif self.super_mpr_b_artifact_digest is None:
            blockers.append("super_mpr_b_artifact_missing")
        else:
            _sha(self.super_mpr_b_artifact_digest, "super_mpr_b_artifact_digest")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class SignerIsolationEvidence:
    signer_service_id: str
    separate_process_boundary: bool
    separate_entrypoint: str
    separate_config_digest: str
    separate_capability_manifest_digest: str
    separate_artifact_digest: str
    runtime_to_signer_channel_authenticated: bool
    namespace_isolation_evidence_digest: str
    key_backend_policy_digest: str
    provider_discovery_inside_signer: bool = False
    route_building_inside_signer: bool = False
    strategy_logic_inside_signer: bool = False
    arbitrary_message_signing: bool = False
    signer_private_key_exposed_to_runtime: bool = False

    def __post_init__(self) -> None:
        _text(self.signer_service_id, "signer_service_id")
        _text(self.separate_entrypoint, "separate_entrypoint")
        for field in (
            "separate_config_digest",
            "separate_capability_manifest_digest",
            "separate_artifact_digest",
            "namespace_isolation_evidence_digest",
            "key_backend_policy_digest",
        ):
            _sha(getattr(self, field), field)

    def blockers(self) -> tuple[str, ...]:
        flags = {
            "signer_not_separate_process": not self.separate_process_boundary,
            "signer_channel_not_authenticated": (
                not self.runtime_to_signer_channel_authenticated
            ),
            "signer_contains_provider_discovery": self.provider_discovery_inside_signer,
            "signer_contains_route_building": self.route_building_inside_signer,
            "signer_contains_strategy_logic": self.strategy_logic_inside_signer,
            "signer_allows_arbitrary_message_signing": self.arbitrary_message_signing,
            "runtime_can_see_signer_private_key": (
                self.signer_private_key_exposed_to_runtime
            ),
        }
        return tuple(reason for reason, blocked in flags.items() if blocked)


@dataclass(frozen=True, slots=True)
class HumanApprovalArtifact:
    approval_id: str
    operator: str
    timestamp: str
    expires_at: str
    runtime_artifact_digest: str
    config_digest: str
    capability_manifest_digest: str
    max_spend_lamports: int
    max_tip_lamports: int
    max_loss_lamports: int
    allowed_route_digest: str
    allowed_program_ids: tuple[str, ...]
    one_transaction_limit: int = 1

    def __post_init__(self) -> None:
        _text(self.approval_id, "approval_id")
        _text(self.operator, "operator")
        _utc(self.timestamp, "timestamp")
        _utc(self.expires_at, "expires_at")
        for field in (
            "runtime_artifact_digest",
            "config_digest",
            "capability_manifest_digest",
            "allowed_route_digest",
        ):
            _sha(getattr(self, field), field)
        _nonneg(self.max_spend_lamports, "max_spend_lamports")
        _nonneg(self.max_tip_lamports, "max_tip_lamports")
        _nonneg(self.max_loss_lamports, "max_loss_lamports")
        if self.one_transaction_limit != 1:
            raise SuperMprCError("approval must be one-transaction only")
        object.__setattr__(
            self,
            "allowed_program_ids",
            _unique(self.allowed_program_ids, "allowed_program_ids"),
        )

    @property
    def approval_digest(self) -> str:
        return digest_payload(asdict(self))


@dataclass(frozen=True, slots=True)
class CanaryPermit:
    permit_id: str
    nonce: str
    expires_at: str
    final_message_digest: str
    simulation_digest: str
    route_digest: str
    economic_digest: str
    account_metas_digest: str
    allowed_program_ids: tuple[str, ...]
    max_fee_lamports: int
    max_tip_lamports: int
    max_loss_lamports: int
    max_spend_lamports: int
    approval_artifact_digest: str
    runtime_artifact_digest: str
    config_digest: str
    capability_manifest_digest: str
    one_transaction_limit: int = 1

    def __post_init__(self) -> None:
        _text(self.permit_id, "permit_id")
        _text(self.nonce, "nonce")
        _utc(self.expires_at, "expires_at")
        for field in (
            "final_message_digest",
            "simulation_digest",
            "route_digest",
            "economic_digest",
            "account_metas_digest",
            "approval_artifact_digest",
            "runtime_artifact_digest",
            "config_digest",
            "capability_manifest_digest",
        ):
            _sha(getattr(self, field), field)
        for field in (
            "max_fee_lamports",
            "max_tip_lamports",
            "max_loss_lamports",
            "max_spend_lamports",
        ):
            _nonneg(getattr(self, field), field)
        if self.one_transaction_limit != 1:
            raise SuperMprCError("permit must be one-transaction only")
        object.__setattr__(
            self,
            "allowed_program_ids",
            _unique(self.allowed_program_ids, "allowed_program_ids"),
        )

    @property
    def permit_digest(self) -> str:
        return digest_payload(asdict(self))

    def blockers_with_approval(
        self,
        approval: HumanApprovalArtifact,
        *,
        now: str,
    ) -> tuple[str, ...]:
        blockers: list[str] = []
        checks = {
            "permit_approval_digest_mismatch": (
                self.approval_artifact_digest == approval.approval_digest
            ),
            "permit_runtime_artifact_mismatch": (
                self.runtime_artifact_digest == approval.runtime_artifact_digest
            ),
            "permit_config_digest_mismatch": (
                self.config_digest == approval.config_digest
            ),
            "permit_route_not_approved": (
                self.route_digest == approval.allowed_route_digest
            ),
            "permit_capability_manifest_digest_mismatch": (
                self.capability_manifest_digest == approval.capability_manifest_digest
            ),
        }
        blockers.extend(reason for reason, ok in checks.items() if not ok)
        if set(self.allowed_program_ids) - set(approval.allowed_program_ids):
            blockers.append("permit_programs_not_approved")
        if self.max_spend_lamports > approval.max_spend_lamports:
            blockers.append("permit_spend_exceeds_approval")
        if self.max_tip_lamports > approval.max_tip_lamports:
            blockers.append("permit_tip_exceeds_approval")
        if self.max_loss_lamports > approval.max_loss_lamports:
            blockers.append("permit_loss_exceeds_approval")
        if approval.expires_at <= now:
            blockers.append("approval_expired")
        if self.expires_at <= now:
            blockers.append("permit_expired")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class PermitLedgerSnapshot:
    consumed_permit_ids: tuple[str, ...] = ()
    consumed_permit_digests: tuple[str, ...] = ()

    def contains(self, permit: CanaryPermit) -> bool:
        return permit.permit_id in self.consumed_permit_ids or (
            permit.permit_digest in self.consumed_permit_digests
        )

    def consume(self, permit: CanaryPermit) -> "PermitLedgerSnapshot":
        if self.contains(permit):
            raise SuperMprCError("permit already consumed")
        return PermitLedgerSnapshot(
            (*self.consumed_permit_ids, permit.permit_id),
            (*self.consumed_permit_digests, permit.permit_digest),
        )


@dataclass(frozen=True, slots=True)
class SameMessageSigningRequest:
    request_id: str
    permit: CanaryPermit
    final_message_digest: str
    simulation_digest: str
    route_digest: str
    economic_digest: str
    account_metas_digest: str
    requested_program_ids: tuple[str, ...]
    signing_request_digest: str
    requested_fee_lamports: int
    requested_tip_lamports: int
    requested_loss_lamports: int
    requested_spend_lamports: int
    blockhash: str
    blockhash_expires_at: str

    def blockers(self, *, now: str) -> tuple[str, ...]:
        blockers: list[str] = []
        expected = {
            "signing_message_digest_mismatch": (
                self.final_message_digest == self.permit.final_message_digest
            ),
            "signing_simulation_digest_mismatch": (
                self.simulation_digest == self.permit.simulation_digest
            ),
            "signing_route_digest_mismatch": (
                self.route_digest == self.permit.route_digest
            ),
            "signing_economic_digest_mismatch": (
                self.economic_digest == self.permit.economic_digest
            ),
            "signing_account_metas_digest_mismatch": (
                self.account_metas_digest == self.permit.account_metas_digest
            ),
        }
        blockers.extend(reason for reason, ok in expected.items() if not ok)
        if set(self.requested_program_ids) - set(self.permit.allowed_program_ids):
            blockers.append("signing_program_not_permitted")
        if self.requested_fee_lamports > self.permit.max_fee_lamports:
            blockers.append("signing_fee_exceeds_permit")
        if self.requested_tip_lamports > self.permit.max_tip_lamports:
            blockers.append("signing_tip_exceeds_permit")
        if self.requested_loss_lamports > self.permit.max_loss_lamports:
            blockers.append("signing_loss_exceeds_permit")
        if self.requested_spend_lamports > self.permit.max_spend_lamports:
            blockers.append("signing_spend_exceeds_permit")
        if self.blockhash_expires_at <= now:
            blockers.append("signing_blockhash_expired")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class KillSwitchState:
    active_conditions: tuple[KillCondition, ...] = ()
    manual_kill_present: bool = False

    def blockers(self) -> tuple[str, ...]:
        conditions = list(self.active_conditions)
        if self.manual_kill_present and KillCondition.MANUAL_KILL not in conditions:
            conditions.append(KillCondition.MANUAL_KILL)
        return tuple(f"kill_switch:{condition.value}" for condition in conditions)


@dataclass(frozen=True, slots=True)
class DuplicateSubmissionSnapshot:
    submitted_transaction_digests: tuple[str, ...] = ()
    consumed_permit_ids: tuple[str, ...] = ()
    submitted_opportunity_ids: tuple[str, ...] = ()
    submitted_blockhashes: tuple[str, ...] = ()
    rpc_and_jito_dual_submission_allowed: bool = False

    def blockers_for(
        self,
        *,
        signed_transaction_digest: str,
        permit_id: str,
        opportunity_id: str,
        blockhash: str,
        already_submitted_via_rpc: bool = False,
        already_submitted_via_jito: bool = False,
    ) -> tuple[str, ...]:
        blockers: list[str] = []
        if signed_transaction_digest in self.submitted_transaction_digests:
            blockers.append("duplicate_signed_transaction")
        if permit_id in self.consumed_permit_ids:
            blockers.append("duplicate_permit_submission")
        if opportunity_id in self.submitted_opportunity_ids:
            blockers.append("duplicate_opportunity_submission")
        if blockhash in self.submitted_blockhashes:
            blockers.append("duplicate_blockhash_submission")
        if (
            already_submitted_via_rpc
            and already_submitted_via_jito
            and not self.rpc_and_jito_dual_submission_allowed
        ):
            blockers.append("rpc_jito_dual_submission_without_policy")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class JitoTransportEvidence:
    enabled_by_canary_policy: bool
    transport_kind: TransportKind
    bundle_status: JitoBundleStatus = JitoBundleStatus.NONE
    tip_inside_same_message_policy: bool = False
    uncle_or_rebroadcast_detected: bool = False

    @property
    def settlement_authority(self) -> bool:
        return False

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if (
            self.transport_kind is TransportKind.JITO
            and not self.enabled_by_canary_policy
        ):
            blockers.append("jito_not_enabled_by_canary_policy")
        if (
            self.transport_kind is TransportKind.JITO
            and not self.tip_inside_same_message_policy
        ):
            blockers.append("jito_tip_not_inside_same_message_policy")
        if self.bundle_status in (JitoBundleStatus.UNCLED, JitoBundleStatus.REBROADCAST):
            blockers.append(f"jito_{self.bundle_status.value}_fail_closed")
        if self.uncle_or_rebroadcast_detected:
            blockers.append("jito_uncle_or_rebroadcast_detected")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class FinalizedSettlementProof:
    finalized_transaction_found: bool
    finalized_commitment: str
    signature: str
    final_message_digest: str
    signed_transaction_digest: str
    token_balance_deltas_digest: str
    native_balance_deltas_digest: str
    actual_fee_lamports: int
    rent_delta_lamports: int
    ata_changes_digest: str
    wsol_lifecycle_digest: str
    flashloan_repayment_digest: str
    realized_net_pnl_lamports: int
    provider_ack_used_as_settlement: bool = False
    rpc_send_response_used_as_settlement: bool = False
    jito_bundle_id_used_as_settlement: bool = False
    signature_only_used_as_settlement: bool = False

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.finalized_commitment != "finalized":
            blockers.append("settlement_not_finalized")
        if not self.finalized_transaction_found:
            blockers.append("settlement_finalized_transaction_missing")
        if self.provider_ack_used_as_settlement:
            blockers.append("provider_ack_cannot_settle")
        if self.rpc_send_response_used_as_settlement:
            blockers.append("rpc_send_response_cannot_settle")
        if self.jito_bundle_id_used_as_settlement:
            blockers.append("jito_bundle_id_cannot_settle")
        if self.signature_only_used_as_settlement:
            blockers.append("signature_only_cannot_settle")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class CanaryRequestEvidence:
    dependencies: SuperMprDependencyEvidence
    signer: SignerIsolationEvidence
    approval: HumanApprovalArtifact | None
    permit: CanaryPermit
    permit_ledger: PermitLedgerSnapshot
    signing_request: SameMessageSigningRequest
    kill_switch: KillSwitchState
    duplicate_guard: DuplicateSubmissionSnapshot
    jito: JitoTransportEvidence
    signed_transaction_digest: str | None = None
    opportunity_id: str | None = None


@dataclass(frozen=True, slots=True)
class CanaryGateAssessment:
    state: CanaryGateState
    reason_code: str
    blockers: tuple[str, ...]
    live_ready: bool
    canary_available: bool
    signer_refuses: bool
    unrestricted_live_possible: bool
    settlement_required: bool
    schema_version: str = SUPER_MPR_C_SCHEMA_VERSION


def evaluate_canary_gate(
    evidence: CanaryRequestEvidence,
    *,
    now: str,
) -> CanaryGateAssessment:
    _utc(now, "now")
    blockers: list[str] = []
    dependency_blockers = list(evidence.dependencies.blockers())
    blockers.extend(dependency_blockers)
    blockers.extend(evidence.signer.blockers())
    if evidence.approval is None:
        blockers.append("missing_human_approval_artifact")
    else:
        blockers.extend(
            evidence.permit.blockers_with_approval(evidence.approval, now=now)
        )
    if evidence.permit_ledger.contains(evidence.permit):
        blockers.append("permit_already_consumed")
    blockers.extend(evidence.signing_request.blockers(now=now))
    blockers.extend(evidence.kill_switch.blockers())
    blockers.extend(evidence.jito.blockers())
    if evidence.signed_transaction_digest and evidence.opportunity_id:
        blockers.extend(
            evidence.duplicate_guard.blockers_for(
                signed_transaction_digest=evidence.signed_transaction_digest,
                permit_id=evidence.permit.permit_id,
                opportunity_id=evidence.opportunity_id,
                blockhash=evidence.signing_request.blockhash,
            )
        )
    unique = tuple(dict.fromkeys(blockers))
    if dependency_blockers:
        state = CanaryGateState.BLOCKED_DEPENDENCY_GATED
        reason = SUPER_MPR_C_DEPENDENCY_GATED
    elif unique:
        state = CanaryGateState.BLOCKED
        reason = SUPER_MPR_C_BLOCKED
    else:
        state = CanaryGateState.READY
        reason = SUPER_MPR_C_READY
    return CanaryGateAssessment(
        state=state,
        reason_code=reason,
        blockers=unique,
        live_ready=False,
        canary_available=state is CanaryGateState.READY,
        signer_refuses=state is not CanaryGateState.READY,
        unrestricted_live_possible=False,
        settlement_required=True,
    )


def consume_permit_before_signing(
    ledger: PermitLedgerSnapshot,
    assessment: CanaryGateAssessment,
    permit: CanaryPermit,
) -> PermitLedgerSnapshot:
    if assessment.state is not CanaryGateState.READY:
        raise SuperMprCError("cannot consume blocked permit")
    return ledger.consume(permit)


def evaluate_finalized_settlement(
    proof: FinalizedSettlementProof,
    *,
    expected_final_message_digest: str,
    expected_signed_transaction_digest: str,
    jito: JitoTransportEvidence,
) -> CanaryGateAssessment:
    blockers = list(proof.blockers())
    if proof.final_message_digest != expected_final_message_digest:
        blockers.append("settlement_message_digest_mismatch")
    if proof.signed_transaction_digest != expected_signed_transaction_digest:
        blockers.append("settlement_signed_transaction_digest_mismatch")
    if jito.settlement_authority:
        blockers.append("jito_transport_cannot_be_settlement_authority")
    blockers.extend(jito.blockers())
    unique = tuple(dict.fromkeys(blockers))
    return CanaryGateAssessment(
        state=CanaryGateState.BLOCKED if unique else CanaryGateState.READY,
        reason_code=SUPER_MPR_C_BLOCKED if unique else SUPER_MPR_C_READY,
        blockers=unique,
        live_ready=False,
        canary_available=False,
        signer_refuses=True,
        unrestricted_live_possible=False,
        settlement_required=True,
    )
