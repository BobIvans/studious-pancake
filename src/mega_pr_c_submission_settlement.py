"""MEGA-PR C permit-bound submission and finalized settlement contract.

This module is intentionally side-effect free. It does not sign, submit, poll,
resend, open sockets, import key material, or enable live trading.  It models the
hard preconditions required before a later integration PR may wire an already
proven sender-free paper message into an isolated signer and finalized settlement
vertical.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable

MEGA_PR_C_SCHEMA = "mega-pr-c.submission-finalized-settlement.v1"
MAX_SOLANA_WIRE_BYTES = 1232


class SubmissionSettlementError(ValueError):
    """Raised when MEGA-PR C evidence is malformed or contradictory."""


class SubmissionSettlementState(StrEnum):
    BLOCKED = "blocked"
    READY_FOR_MANUAL_INTEGRATION_REVIEW = "ready-for-manual-integration-review"


@dataclass(frozen=True, slots=True)
class UpstreamReadinessEvidence:
    """Evidence that A/B/D prerequisites exist before active submission wiring."""

    canonical_paper_vertical_merged: bool
    provider_protocol_conformance_merged: bool
    real_sender_free_soak_completed: bool
    release_candidate_pinned: bool
    live_default_disabled: bool
    paper_message_identity_stable: bool
    evidence_bundle_hash: str

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.canonical_paper_vertical_merged:
            blockers.append("MEGA_PR_A_CANONICAL_PAPER_VERTICAL_REQUIRED")
        if not self.provider_protocol_conformance_merged:
            blockers.append("MEGA_PR_B_PROVIDER_CONFORMANCE_REQUIRED")
        if not self.real_sender_free_soak_completed:
            blockers.append("REAL_SENDER_FREE_SOAK_REQUIRED")
        if not self.release_candidate_pinned:
            blockers.append("PINNED_RELEASE_CANDIDATE_REQUIRED")
        if not self.live_default_disabled:
            blockers.append("LIVE_DEFAULT_MUST_REMAIN_DISABLED")
        if not self.paper_message_identity_stable:
            blockers.append("STABLE_PAPER_MESSAGE_IDENTITY_REQUIRED")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class IsolatedSignerBoundary:
    """Proof that the runtime cannot directly sign or reach key material."""

    signer_service_identity: str
    expected_signer_pubkey: str
    network_runtime_private_key_absent: bool
    runtime_cannot_import_keypair: bool
    signer_general_internet_blocked: bool
    signer_uses_authenticated_ipc_only: bool
    signer_parses_unsigned_message: bool
    signer_verifies_payer_and_signers: bool
    signer_verifies_programs_and_writable_accounts: bool
    signer_verifies_alt_resolution: bool
    signer_verifies_instruction_semantics: bool
    key_material_hash_absent_from_evidence: bool = True

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.signer_service_identity.strip():
            blockers.append("SIGNER_SERVICE_IDENTITY_REQUIRED")
        if not self.expected_signer_pubkey.strip():
            blockers.append("EXPECTED_SIGNER_PUBKEY_REQUIRED")
        checks = {
            "NETWORK_RUNTIME_PRIVATE_KEY_MUST_BE_ABSENT": self.network_runtime_private_key_absent,
            "NETWORK_RUNTIME_KEYPAIR_IMPORT_MUST_BE_IMPOSSIBLE": self.runtime_cannot_import_keypair,
            "SIGNER_GENERAL_INTERNET_MUST_BE_BLOCKED": self.signer_general_internet_blocked,
            "SIGNER_IPC_MUST_BE_AUTHENTICATED_ONLY": self.signer_uses_authenticated_ipc_only,
            "SIGNER_MUST_PARSE_UNSIGNED_MESSAGE": self.signer_parses_unsigned_message,
            "SIGNER_MUST_VERIFY_PAYER_AND_SIGNERS": self.signer_verifies_payer_and_signers,
            "SIGNER_MUST_VERIFY_PROGRAMS_AND_WRITABLE_ACCOUNTS": self.signer_verifies_programs_and_writable_accounts,
            "SIGNER_MUST_VERIFY_ALT_RESOLUTION": self.signer_verifies_alt_resolution,
            "SIGNER_MUST_VERIFY_INSTRUCTION_SEMANTICS": self.signer_verifies_instruction_semantics,
            "KEY_MATERIAL_MUST_NOT_APPEAR_IN_EVIDENCE": self.key_material_hash_absent_from_evidence,
        }
        blockers.extend(name for name, ok in checks.items() if not ok)
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class ProvenMessageBundle:
    """The one final serialized message identity proven by paper/soak."""

    logical_opportunity_id: str
    attempt_id: str
    attempt_generation: int
    final_request_hash: str
    policy_hash: str
    plan_hash: str
    final_simulation_hash: str
    cpi_graph_hash: str
    final_fee_hash: str
    blockhash_evidence_hash: str
    alt_evidence_hash: str
    serialized_message_hash: str
    unsigned_wire_hash: str
    payer: str
    signer_set_hash: str
    writable_accounts_hash: str
    wire_size_bytes: int
    same_message_jito_tip_lamports: int = 0
    standalone_tip_transaction_allowed: bool = False

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        for field, value in (
            ("final_request_hash", self.final_request_hash),
            ("policy_hash", self.policy_hash),
            ("plan_hash", self.plan_hash),
            ("final_simulation_hash", self.final_simulation_hash),
            ("cpi_graph_hash", self.cpi_graph_hash),
            ("final_fee_hash", self.final_fee_hash),
            ("blockhash_evidence_hash", self.blockhash_evidence_hash),
            ("alt_evidence_hash", self.alt_evidence_hash),
            ("serialized_message_hash", self.serialized_message_hash),
            ("unsigned_wire_hash", self.unsigned_wire_hash),
            ("signer_set_hash", self.signer_set_hash),
            ("writable_accounts_hash", self.writable_accounts_hash),
        ):
            if not _is_digest(value):
                blockers.append(f"INVALID_{field.upper()}")
        for field, value in (
            ("logical_opportunity_id", self.logical_opportunity_id),
            ("attempt_id", self.attempt_id),
            ("payer", self.payer),
        ):
            if not value.strip():
                blockers.append(f"{field.upper()}_REQUIRED")
        if self.attempt_generation < 1:
            blockers.append("ATTEMPT_GENERATION_MUST_BE_POSITIVE")
        if self.wire_size_bytes <= 0 or self.wire_size_bytes > MAX_SOLANA_WIRE_BYTES:
            blockers.append("WIRE_SIZE_OUTSIDE_SOLANA_LIMIT")
        if self.same_message_jito_tip_lamports < 0:
            blockers.append("JITO_TIP_MUST_BE_NON_NEGATIVE")
        if self.standalone_tip_transaction_allowed:
            blockers.append("STANDALONE_TIP_TRANSACTION_FORBIDDEN")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class OneTimeAuthorization:
    """Durable isolated-signer authorization bound to one exact message."""

    authorization_id: str
    signer_service_identity: str
    expected_signer_pubkey: str
    request_hash: str
    policy_hash: str
    message_hash: str
    unsigned_wire_hash: str
    nonce: str
    issued_at_ns: int
    expires_at_ns: int
    verification_chain_hash: str
    durable_consumed_state: bool
    consumed: bool = False
    revoked: bool = False

    def blockers(self, *, bundle: ProvenMessageBundle, signer: IsolatedSignerBoundary) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.authorization_id.strip():
            blockers.append("AUTHORIZATION_ID_REQUIRED")
        if not self.nonce.strip():
            blockers.append("AUTHORIZATION_NONCE_REQUIRED")
        if self.signer_service_identity != signer.signer_service_identity:
            blockers.append("AUTHORIZATION_SIGNER_IDENTITY_MISMATCH")
        if self.expected_signer_pubkey != signer.expected_signer_pubkey:
            blockers.append("AUTHORIZATION_SIGNER_PUBKEY_MISMATCH")
        if self.request_hash != bundle.final_request_hash:
            blockers.append("AUTHORIZATION_REQUEST_HASH_MISMATCH")
        if self.policy_hash != bundle.policy_hash:
            blockers.append("AUTHORIZATION_POLICY_HASH_MISMATCH")
        if self.message_hash != bundle.serialized_message_hash:
            blockers.append("AUTHORIZATION_MESSAGE_HASH_MISMATCH")
        if self.unsigned_wire_hash != bundle.unsigned_wire_hash:
            blockers.append("AUTHORIZATION_WIRE_HASH_MISMATCH")
        if not _is_digest(self.verification_chain_hash):
            blockers.append("AUTHORIZATION_VERIFICATION_CHAIN_HASH_INVALID")
        if self.issued_at_ns <= 0 or self.expires_at_ns <= self.issued_at_ns:
            blockers.append("AUTHORIZATION_EXPIRY_INVALID")
        if not self.durable_consumed_state:
            blockers.append("AUTHORIZATION_CONSUMPTION_MUST_BE_DURABLE")
        if self.consumed:
            blockers.append("AUTHORIZATION_ALREADY_CONSUMED")
        if self.revoked:
            blockers.append("AUTHORIZATION_REVOKED")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class DurableSubmissionIntent:
    """Submission intent that must be recorded before any external I/O."""

    intent_id: str
    authorization_id: str
    attempt_id: str
    attempt_generation: int
    message_hash: str
    idempotency_key: str
    lease_owner: str
    fencing_token: str
    recorded_before_external_io: bool
    authorization_consumed_atomically: bool
    outbound_io_started: bool
    duplicate_send_possible: bool = False
    blind_resend_after_timeout_allowed: bool = False

    def blockers(self, *, bundle: ProvenMessageBundle, authorization: OneTimeAuthorization) -> tuple[str, ...]:
        blockers: list[str] = []
        for field, value in (
            ("intent_id", self.intent_id),
            ("lease_owner", self.lease_owner),
            ("fencing_token", self.fencing_token),
        ):
            if not value.strip():
                blockers.append(f"{field.upper()}_REQUIRED")
        if self.authorization_id != authorization.authorization_id:
            blockers.append("SUBMISSION_AUTHORIZATION_ID_MISMATCH")
        if self.attempt_id != bundle.attempt_id:
            blockers.append("SUBMISSION_ATTEMPT_ID_MISMATCH")
        if self.attempt_generation != bundle.attempt_generation:
            blockers.append("SUBMISSION_ATTEMPT_GENERATION_MISMATCH")
        if self.message_hash != bundle.serialized_message_hash:
            blockers.append("SUBMISSION_MESSAGE_HASH_MISMATCH")
        expected_key = derive_idempotency_key(
            authorization_id=authorization.authorization_id,
            message_hash=bundle.serialized_message_hash,
            attempt_id=bundle.attempt_id,
            attempt_generation=bundle.attempt_generation,
        )
        if self.idempotency_key != expected_key:
            blockers.append("SUBMISSION_IDEMPOTENCY_KEY_MISMATCH")
        if not self.recorded_before_external_io:
            blockers.append("SUBMISSION_INTENT_MUST_PRECEDE_EXTERNAL_IO")
        if not self.authorization_consumed_atomically:
            blockers.append("AUTHORIZATION_MUST_BE_CONSUMED_ATOMICALLY_WITH_INTENT")
        if not self.outbound_io_started:
            blockers.append("SUBMISSION_IO_NOT_STARTED_FOR_REVIEW_EVIDENCE")
        if self.duplicate_send_possible:
            blockers.append("DUPLICATE_SEND_MUST_BE_IMPOSSIBLE")
        if self.blind_resend_after_timeout_allowed:
            blockers.append("BLIND_RESEND_AFTER_TIMEOUT_FORBIDDEN")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class JitoRpcSubmissionPolicy:
    """First-live transport constraints. Transport never equals settlement."""

    one_strategy_transaction_only: bool
    same_message_tip_only: bool
    no_multiregion_shotgun: bool
    bundle_ack_is_not_settlement: bool
    direct_rpc_fallback_requires_explicit_policy: bool
    bundle_only_requires_reviewed_policy: bool
    max_transactions_per_hour: int
    max_transactions_per_day: int
    max_tip_lamports: int
    max_fee_lamports: int

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        checks = {
            "FIRST_LIVE_REQUIRES_ONE_STRATEGY_TRANSACTION": self.one_strategy_transaction_only,
            "JITO_TIP_MUST_BE_IN_SAME_MESSAGE_ONLY": self.same_message_tip_only,
            "MULTIREGION_SHOTGUN_SUBMISSION_FORBIDDEN": self.no_multiregion_shotgun,
            "BUNDLE_ACK_MUST_NOT_BE_SETTLEMENT": self.bundle_ack_is_not_settlement,
            "DIRECT_RPC_FALLBACK_REQUIRES_EXPLICIT_POLICY": self.direct_rpc_fallback_requires_explicit_policy,
            "BUNDLE_ONLY_REQUIRES_REVIEWED_POLICY": self.bundle_only_requires_reviewed_policy,
        }
        blockers.extend(name for name, ok in checks.items() if not ok)
        for field, value in (
            ("max_transactions_per_hour", self.max_transactions_per_hour),
            ("max_transactions_per_day", self.max_transactions_per_day),
            ("max_tip_lamports", self.max_tip_lamports),
            ("max_fee_lamports", self.max_fee_lamports),
        ):
            if value < 0:
                blockers.append(f"{field.upper()}_MUST_BE_NON_NEGATIVE")
        if self.max_transactions_per_hour == 0 or self.max_transactions_per_day == 0:
            blockers.append("FIRST_CANARY_TRANSACTION_LIMITS_REQUIRED")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class TransportObservation:
    """Receipt/transport observations that are explicitly non-economic."""

    json_rpc_ack_received: bool
    bundle_status_observed: bool
    signature_observed: bool
    timed_out_or_unknown: bool
    treated_as_economic_success: bool = False

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.treated_as_economic_success:
            blockers.append("TRANSPORT_OBSERVATION_CANNOT_BE_ECONOMIC_SUCCESS")
        if self.timed_out_or_unknown:
            blockers.append("UNKNOWN_TRANSPORT_OUTCOME_REQUIRES_DURABLE_RECONCILIATION")
        if not self.signature_observed:
            blockers.append("SUBMITTED_SIGNATURE_REQUIRED_FOR_SETTLEMENT_POLLING")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class FinalizedSettlementEvidence:
    """Actual finalized transaction evidence needed before PnL can be booked."""

    signature: str
    expected_signature: str
    message_hash: str
    expected_message_hash: str
    finalized_get_transaction: bool
    transaction_version_supported: bool
    signature_matches_message: bool
    loaded_addresses_reconciled: bool
    native_balances_reconciled: bool
    token_balances_reconciled: bool
    inner_instructions_reconciled: bool
    logs_reconciled: bool
    return_data_reconciled: bool
    compute_units_reconciled: bool
    marginfi_repayment_proven: bool
    fees_tips_rent_cleanup_reconciled: bool
    unresolved_or_conflicting_status: bool
    pnl_booked_from_finalized_actuals_only: bool
    actual_net_lamports: int | None
    evidence_hash: str

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.signature.strip() or self.signature != self.expected_signature:
            blockers.append("FINALIZED_SIGNATURE_MISMATCH")
        if self.message_hash != self.expected_message_hash:
            blockers.append("FINALIZED_MESSAGE_HASH_MISMATCH")
        checks = {
            "FINALIZED_GET_TRANSACTION_REQUIRED": self.finalized_get_transaction,
            "SUPPORTED_TRANSACTION_VERSION_REQUIRED": self.transaction_version_supported,
            "SIGNATURE_MUST_MATCH_EXACT_MESSAGE": self.signature_matches_message,
            "LOADED_ADDRESSES_MUST_BE_RECONCILED": self.loaded_addresses_reconciled,
            "NATIVE_BALANCES_MUST_BE_RECONCILED": self.native_balances_reconciled,
            "TOKEN_BALANCES_MUST_BE_RECONCILED": self.token_balances_reconciled,
            "INNER_INSTRUCTIONS_MUST_BE_RECONCILED": self.inner_instructions_reconciled,
            "LOGS_MUST_BE_RECONCILED": self.logs_reconciled,
            "RETURN_DATA_MUST_BE_RECONCILED": self.return_data_reconciled,
            "COMPUTE_UNITS_MUST_BE_RECONCILED": self.compute_units_reconciled,
            "MARGINFI_REPAYMENT_MUST_BE_PROVEN": self.marginfi_repayment_proven,
            "FEES_TIPS_RENT_CLEANUP_MUST_BE_RECONCILED": self.fees_tips_rent_cleanup_reconciled,
            "PNL_CAN_ONLY_BE_BOOKED_FROM_FINALIZED_ACTUALS": self.pnl_booked_from_finalized_actuals_only,
        }
        blockers.extend(name for name, ok in checks.items() if not ok)
        if self.unresolved_or_conflicting_status:
            blockers.append("CONFLICTING_STATUS_REQUIRES_MANUAL_REVIEW")
        if self.actual_net_lamports is None:
            blockers.append("ACTUAL_NET_LAMPORTS_REQUIRED")
        if not _is_digest(self.evidence_hash):
            blockers.append("FINALIZED_SETTLEMENT_EVIDENCE_HASH_INVALID")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class SubmissionSettlementPackage:
    upstream: UpstreamReadinessEvidence
    signer: IsolatedSignerBoundary
    message: ProvenMessageBundle
    authorization: OneTimeAuthorization
    submission_intent: DurableSubmissionIntent
    transport_policy: JitoRpcSubmissionPolicy
    transport_observation: TransportObservation
    finalized_settlement: FinalizedSettlementEvidence
    schema_version: str = MEGA_PR_C_SCHEMA
    live_requested: bool = False


@dataclass(frozen=True, slots=True)
class SubmissionSettlementReadiness:
    schema_version: str
    state: SubmissionSettlementState
    runtime_live_enabled: bool
    supported_command_can_submit: bool
    signer_reachable_from_network_runtime: bool
    economically_successful: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "runtime_live_enabled": self.runtime_live_enabled,
            "supported_command_can_submit": self.supported_command_can_submit,
            "signer_reachable_from_network_runtime": self.signer_reachable_from_network_runtime,
            "economically_successful": self.economically_successful,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


def evaluate_submission_settlement_package(
    package: SubmissionSettlementPackage,
) -> SubmissionSettlementReadiness:
    """Evaluate whether MEGA-PR C evidence is ready for manual integration review.

    This is a pre-submit contract. It deliberately never returns an active submit
    capability; later runtime wiring must consume these invariants behind release,
    operator and canary gates.
    """

    if package.schema_version != MEGA_PR_C_SCHEMA:
        raise SubmissionSettlementError("unsupported MEGA-PR C schema")

    blockers: list[str] = []
    warnings: list[str] = []
    blockers.extend(package.upstream.blockers())
    _append_digest_blocker(blockers, package.upstream.evidence_bundle_hash, "UPSTREAM_EVIDENCE_BUNDLE_HASH_INVALID")
    blockers.extend(package.signer.blockers())
    blockers.extend(package.message.blockers())
    blockers.extend(package.authorization.blockers(bundle=package.message, signer=package.signer))
    blockers.extend(package.submission_intent.blockers(bundle=package.message, authorization=package.authorization))
    blockers.extend(package.transport_policy.blockers())
    blockers.extend(package.transport_observation.blockers())
    blockers.extend(package.finalized_settlement.blockers())

    if package.live_requested:
        blockers.append("LIVE_REQUEST_OUT_OF_SCOPE_FOR_MEGA_PR_C_START")
    if package.transport_observation.json_rpc_ack_received:
        warnings.append("json-rpc ack is transport-only, not settlement")
    if package.transport_observation.bundle_status_observed:
        warnings.append("bundle status is transport-only, not settlement")

    state = (
        SubmissionSettlementState.READY_FOR_MANUAL_INTEGRATION_REVIEW
        if not blockers
        else SubmissionSettlementState.BLOCKED
    )
    return SubmissionSettlementReadiness(
        schema_version=MEGA_PR_C_SCHEMA,
        state=state,
        runtime_live_enabled=False,
        supported_command_can_submit=False,
        signer_reachable_from_network_runtime=False,
        economically_successful=(state == SubmissionSettlementState.READY_FOR_MANUAL_INTEGRATION_REVIEW),
        blockers=_dedupe(blockers),
        warnings=_dedupe(warnings),
    )


def derive_idempotency_key(
    *, authorization_id: str, message_hash: str, attempt_id: str, attempt_generation: int
) -> str:
    return (
        "mega-pr-c:"
        f"{authorization_id}:{attempt_id}:{attempt_generation}:{message_hash}"
    )


def _append_digest_blocker(blockers: list[str], value: str, blocker: str) -> None:
    if not _is_digest(value):
        blockers.append(blocker)


def _is_digest(value: str) -> bool:
    text = value.strip().lower()
    if text.startswith("sha256:"):
        text = text.removeprefix("sha256:")
    if text in {"", "todo", "placeholder", "unknown", "0" * 64}:
        return False
    if len(text) != 64:
        return False
    return all(char in "0123456789abcdef" for char in text)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


__all__ = [
    "MAX_SOLANA_WIRE_BYTES",
    "MEGA_PR_C_SCHEMA",
    "DurableSubmissionIntent",
    "FinalizedSettlementEvidence",
    "IsolatedSignerBoundary",
    "JitoRpcSubmissionPolicy",
    "OneTimeAuthorization",
    "ProvenMessageBundle",
    "SubmissionSettlementError",
    "SubmissionSettlementPackage",
    "SubmissionSettlementReadiness",
    "SubmissionSettlementState",
    "TransportObservation",
    "UpstreamReadinessEvidence",
    "derive_idempotency_key",
    "evaluate_submission_settlement_package",
]
