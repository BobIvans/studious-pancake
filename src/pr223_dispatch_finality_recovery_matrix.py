"""PR-223 cryptographic dispatch/finality recovery matrix gate.

This module is deliberately offline and side-effect free.  It does not load
keys, open signer IPC, call RPC/Jito, submit transactions, or enable live
trading.  It defines a fail-closed evidence contract for the next PR-223
follow-up after the first merged PR-223 acceptance gate.

The contract focuses on the dangerous boundary that remains after a simulated
sender-free payload has been accepted by PR-222: authorization must be real,
permit consumption must be exactly-once, transport acknowledgements must not
be confused with settlement, and settlement/accounting evidence must be rooted
in independently materialized finalized observations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re

SCHEMA_VERSION = "pr223.dispatch-finality-recovery-matrix.v1"

REQUIRED_FINDINGS = frozenset(
    {
        "F-025",
        "F-045",
        *{f"F-{idx:03d}" for idx in range(125, 131)},
        *{f"F-{idx:03d}" for idx in range(143, 163)},
        "F-165",
        "F-169",
        "F-170",
        "F-172",
        *{f"F-{idx:03d}" for idx in range(187, 191)},
        *{f"F-{idx:03d}" for idx in range(195, 199)},
        *{f"F-{idx:03d}" for idx in range(249, 256)},
    }
)

REQUIRED_AUTH_BINDINGS = frozenset(
    {
        "config_generation",
        "release_generation",
        "wallet",
        "plan_digest",
        "message_digest",
        "provider",
        "market",
        "reservation",
        "session",
        "nonce",
        "not_before",
        "expiry",
        "transport",
    }
)

REQUIRED_CRASH_POINTS = frozenset(
    {
        "before_permit_consume",
        "after_permit_consume",
        "after_intent_create",
        "after_outbox_create",
        "after_dispatched_record",
        "after_transport_handoff",
        "after_receipt_record",
        "during_reconciliation",
    }
)

REQUIRED_FINALITY_FIELDS = frozenset(
    {
        "signature",
        "slot",
        "err",
        "meta_fee",
        "pre_balances",
        "post_balances",
        "pre_token_balances",
        "post_token_balances",
        "program_logs",
        "loaded_addresses",
        "commitment",
        "transaction_version",
    }
)

REQUIRED_CROSS_PLANE_STORES = frozenset(
    {
        "lifecycle",
        "outbox",
        "signer",
        "transport",
        "settlement",
        "accounting",
        "release_policy",
    }
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class EvidenceRef:
    """A materialized evidence reference."""

    name: str
    sha256: str
    uri: str
    signed: bool = True
    immutable: bool = True
    produced_by_runtime: bool = False

    def problems(self) -> list[str]:
        problems: list[str] = []
        if not self.name:
            problems.append("name missing")
        if not SHA256_RE.fullmatch(self.sha256):
            problems.append(f"{self.name}: sha256 is not a full lowercase SHA-256")
        if self.sha256 in {"0" * 64, "f" * 64}:
            problems.append(f"{self.name}: placeholder sha256")
        if not self.uri or self.uri.startswith("/tmp/") or self.uri.startswith("memory:"):
            problems.append(f"{self.name}: non-durable evidence URI")
        if not self.signed:
            problems.append(f"{self.name}: evidence is unsigned")
        if not self.immutable:
            problems.append(f"{self.name}: evidence is mutable")
        return problems


@dataclass(frozen=True)
class PrerequisiteEvidence:
    pr219_accepted: bool
    pr220_accepted: bool
    pr222_accepted: bool
    prior_pr223_gate_accepted: bool
    pr222_exact_message_sha256: str
    pr223_gate_report_sha256: str

    def problems(self) -> list[str]:
        problems: list[str] = []
        if not self.pr219_accepted:
            problems.append("PR223_PR219_NOT_ACCEPTED")
        if not self.pr220_accepted:
            problems.append("PR223_PR220_NOT_ACCEPTED")
        if not self.pr222_accepted:
            problems.append("PR223_PR222_NOT_ACCEPTED")
        if not self.prior_pr223_gate_accepted:
            problems.append("PR223_INITIAL_GATE_NOT_ACCEPTED")
        for field_name, digest in {
            "pr222_exact_message_sha256": self.pr222_exact_message_sha256,
            "pr223_gate_report_sha256": self.pr223_gate_report_sha256,
        }.items():
            if not SHA256_RE.fullmatch(digest) or digest in {"0" * 64, "f" * 64}:
                problems.append(f"{field_name.upper()}_INVALID")
        return problems


@dataclass(frozen=True)
class TrustAndAuthorizationEvidence:
    root_signed_trust_bundle: bool
    real_ed25519_verification: bool
    canonical_serialization: bool
    schema_domain_separation: bool
    key_rotation_revocation_checked: bool
    not_before_enforced: bool
    expiry_enforced: bool
    future_issued_rejected: bool
    authorization_bindings: frozenset[str]
    authorization_not_caller_boolean: bool
    authorization_not_caller_hash: bool

    def problems(self) -> list[str]:
        problems: list[str] = []
        checks = {
            "ROOT_TRUST_UNSIGNED": self.root_signed_trust_bundle,
            "ED25519_NOT_REAL": self.real_ed25519_verification,
            "CANONICAL_SERIALIZATION_MISSING": self.canonical_serialization,
            "SCHEMA_DOMAIN_SEPARATION_MISSING": self.schema_domain_separation,
            "KEY_ROTATION_REVOCATION_MISSING": self.key_rotation_revocation_checked,
            "NOT_BEFORE_NOT_ENFORCED": self.not_before_enforced,
            "EXPIRY_NOT_ENFORCED": self.expiry_enforced,
            "FUTURE_ISSUED_NOT_REJECTED": self.future_issued_rejected,
            "AUTHORIZATION_CALLER_BOOLEAN_ACCEPTED": self.authorization_not_caller_boolean,
            "AUTHORIZATION_CALLER_HASH_ACCEPTED": self.authorization_not_caller_hash,
        }
        problems.extend(reason for reason, ok in checks.items() if not ok)
        missing = REQUIRED_AUTH_BINDINGS - self.authorization_bindings
        if missing:
            problems.append("AUTHORIZATION_BINDINGS_MISSING:" + ",".join(sorted(missing)))
        extra = self.authorization_bindings - REQUIRED_AUTH_BINDINGS
        if extra:
            problems.append("AUTHORIZATION_UNKNOWN_BINDINGS:" + ",".join(sorted(extra)))
        return problems


@dataclass(frozen=True)
class IsolatedCustodyEvidence:
    runtime_has_no_private_key_access: bool
    signer_separate_package: bool
    signer_separate_process_user_network: bool
    signer_uses_hsm_kms_or_owner_only_key: bool
    signer_decodes_exact_message_bytes: bool
    signer_binds_pr222_message_digest: bool
    signer_produces_signature: bool
    signer_builds_signed_wire: bool
    local_signature_verification_transcript: bool
    runtime_cannot_request_raw_key_export: bool

    def problems(self) -> list[str]:
        checks = {
            "RUNTIME_PRIVATE_KEY_ACCESS": self.runtime_has_no_private_key_access,
            "SIGNER_PACKAGE_NOT_ISOLATED": self.signer_separate_package,
            "SIGNER_PROCESS_USER_NETWORK_NOT_ISOLATED": self.signer_separate_process_user_network,
            "SIGNER_CUSTODY_NOT_PROVEN": self.signer_uses_hsm_kms_or_owner_only_key,
            "SIGNER_DOES_NOT_DECODE_MESSAGE": self.signer_decodes_exact_message_bytes,
            "SIGNER_NOT_BOUND_TO_PR222_MESSAGE": self.signer_binds_pr222_message_digest,
            "SIGNATURE_NOT_SIGNER_PRODUCED": self.signer_produces_signature,
            "SIGNED_WIRE_NOT_SIGNER_BUILT": self.signer_builds_signed_wire,
            "LOCAL_SIGNATURE_VERIFY_MISSING": self.local_signature_verification_transcript,
            "RAW_KEY_EXPORT_REACHABLE": self.runtime_cannot_request_raw_key_export,
        }
        return [reason for reason, ok in checks.items() if not ok]


@dataclass(frozen=True)
class DispatchRecoveryEvidence:
    permit_intent_outbox_single_transaction: bool
    one_permit_one_message_digest: bool
    replay_denied: bool
    stale_config_denied: bool
    stale_shadow_evidence_denied: bool
    dispatched_record_before_transport: bool
    idempotent_provider_key_bound: bool
    unknown_reconciliation_owner: bool
    no_blind_resend: bool
    daily_debit_limits_durable: bool
    crash_points_covered: frozenset[str]
    duplicate_debit_impossible: bool

    def problems(self) -> list[str]:
        checks = {
            "PERMIT_INTENT_OUTBOX_NOT_ATOMIC": self.permit_intent_outbox_single_transaction,
            "PERMIT_NOT_BOUND_TO_ONE_MESSAGE": self.one_permit_one_message_digest,
            "REPLAY_NOT_DENIED": self.replay_denied,
            "STALE_CONFIG_NOT_DENIED": self.stale_config_denied,
            "STALE_SHADOW_EVIDENCE_NOT_DENIED": self.stale_shadow_evidence_denied,
            "DISPATCHED_NOT_RECORDED_BEFORE_TRANSPORT": self.dispatched_record_before_transport,
            "PROVIDER_IDEMPOTENCY_KEY_NOT_BOUND": self.idempotent_provider_key_bound,
            "UNKNOWN_HAS_NO_RECONCILIATION_OWNER": self.unknown_reconciliation_owner,
            "BLIND_RESEND_REACHABLE": self.no_blind_resend,
            "DURABLE_DEBIT_LIMITS_MISSING": self.daily_debit_limits_durable,
            "DUPLICATE_DEBIT_POSSIBLE": self.duplicate_debit_impossible,
        }
        problems = [reason for reason, ok in checks.items() if not ok]
        missing = REQUIRED_CRASH_POINTS - self.crash_points_covered
        if missing:
            problems.append("CRASH_POINTS_MISSING:" + ",".join(sorted(missing)))
        return problems


@dataclass(frozen=True)
class TransportFinalityEvidence:
    transport_payload_digest_bound: bool
    transport_endpoint_min_context_slot_blockhash_bound: bool
    transport_tip_bound: bool
    ack_is_not_landing: bool
    bundle_id_is_not_landing: bool
    rpc_signature_is_not_finality: bool
    finalized_get_transaction_required: bool
    finality_fields: frozenset[str]
    failed_landed_fee_and_balance_deltas_recorded: bool
    settlement_transport_matches_intent: bool
    fork_reorg_uncle_rebroadcast_matrix: bool

    def problems(self) -> list[str]:
        checks = {
            "TRANSPORT_PAYLOAD_DIGEST_NOT_BOUND": self.transport_payload_digest_bound,
            "TRANSPORT_CONTEXT_BLOCKHASH_NOT_BOUND": self.transport_endpoint_min_context_slot_blockhash_bound,
            "TRANSPORT_TIP_NOT_BOUND": self.transport_tip_bound,
            "ACK_COUNTS_AS_LANDING": self.ack_is_not_landing,
            "BUNDLE_ID_COUNTS_AS_LANDING": self.bundle_id_is_not_landing,
            "RPC_SIGNATURE_COUNTS_AS_FINALITY": self.rpc_signature_is_not_finality,
            "FINALIZED_GET_TRANSACTION_NOT_REQUIRED": self.finalized_get_transaction_required,
            "FAILED_LANDED_COSTS_MISSING": self.failed_landed_fee_and_balance_deltas_recorded,
            "SETTLEMENT_TRANSPORT_MISMATCH_ALLOWED": self.settlement_transport_matches_intent,
            "FORK_REORG_MATRIX_MISSING": self.fork_reorg_uncle_rebroadcast_matrix,
        }
        problems = [reason for reason, ok in checks.items() if not ok]
        missing = REQUIRED_FINALITY_FIELDS - self.finality_fields
        if missing:
            problems.append("FINALITY_FIELDS_MISSING:" + ",".join(sorted(missing)))
        return problems


@dataclass(frozen=True)
class ArchiveReconciliationGovernanceEvidence:
    archive_receipt_rehashes_published_bytes: bool
    archive_receipt_remote_worm: bool
    archive_receipt_immutable_no_upsert: bool
    cross_plane_stores: frozenset[str]
    corrections_append_only: bool
    reconciliation_reads_authoritative_stores: bool
    dual_approval_distinct: bool
    approval_fresh_trusted_time: bool
    aggregate_budget_checked: bool
    rollback_proof_present: bool
    tiny_canary_requires_final_settlement: bool
    canary_disabled_by_default: bool

    def problems(self) -> list[str]:
        checks = {
            "ARCHIVE_BYTES_NOT_REHASHED": self.archive_receipt_rehashes_published_bytes,
            "ARCHIVE_RECEIPT_NOT_WORM": self.archive_receipt_remote_worm,
            "ARCHIVE_UPSERT_ALLOWED": self.archive_receipt_immutable_no_upsert,
            "CORRECTIONS_NOT_APPEND_ONLY": self.corrections_append_only,
            "RECONCILIATION_NOT_AUTHORITATIVE": self.reconciliation_reads_authoritative_stores,
            "DUAL_APPROVAL_NOT_DISTINCT": self.dual_approval_distinct,
            "APPROVAL_TIME_NOT_TRUSTED": self.approval_fresh_trusted_time,
            "AGGREGATE_BUDGET_NOT_CHECKED": self.aggregate_budget_checked,
            "ROLLBACK_PROOF_MISSING": self.rollback_proof_present,
            "TINY_CANARY_WITHOUT_FINAL_SETTLEMENT": self.tiny_canary_requires_final_settlement,
            "CANARY_ENABLED_BY_DEFAULT": self.canary_disabled_by_default,
        }
        problems = [reason for reason, ok in checks.items() if not ok]
        missing = REQUIRED_CROSS_PLANE_STORES - self.cross_plane_stores
        if missing:
            problems.append("CROSS_PLANE_STORES_MISSING:" + ",".join(sorted(missing)))
        return problems


@dataclass(frozen=True)
class CapabilityPosture:
    signer_allowed: bool = False
    sender_allowed: bool = False
    live_execution_allowed: bool = False
    private_key_material_allowed: bool = False
    automatic_canary_allowed: bool = False
    unrestricted_live_allowed: bool = False


@dataclass(frozen=True)
class PR223DispatchFinalityEvidence:
    schema_version: str
    finding_coverage: frozenset[str]
    evidence_refs: tuple[EvidenceRef, ...]
    prerequisites: PrerequisiteEvidence
    trust_authorization: TrustAndAuthorizationEvidence
    custody: IsolatedCustodyEvidence
    dispatch: DispatchRecoveryEvidence
    transport_finality: TransportFinalityEvidence
    archive_reconciliation_governance: ArchiveReconciliationGovernanceEvidence
    capabilities: CapabilityPosture = field(default_factory=CapabilityPosture)


@dataclass(frozen=True)
class PR223DispatchFinalityReport:
    schema_version: str
    accepted: bool
    reasons: tuple[str, ...]
    dispatch_finality_review_allowed: bool
    signer_allowed: bool
    sender_allowed: bool
    live_execution_allowed: bool
    private_key_material_allowed: bool
    automatic_canary_allowed: bool
    unrestricted_live_allowed: bool

    def assert_accepted(self) -> None:
        if not self.accepted:
            raise ValueError("; ".join(self.reasons))

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "accepted": self.accepted,
                "reasons": list(self.reasons),
                "dispatch_finality_review_allowed": self.dispatch_finality_review_allowed,
                "signer_allowed": self.signer_allowed,
                "sender_allowed": self.sender_allowed,
                "live_execution_allowed": self.live_execution_allowed,
                "private_key_material_allowed": self.private_key_material_allowed,
                "automatic_canary_allowed": self.automatic_canary_allowed,
                "unrestricted_live_allowed": self.unrestricted_live_allowed,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def _coverage_problems(coverage: frozenset[str]) -> list[str]:
    problems: list[str] = []
    missing = REQUIRED_FINDINGS - coverage
    if missing:
        problems.append("FINDINGS_MISSING:" + ",".join(sorted(missing)))
    extra = coverage - REQUIRED_FINDINGS
    if extra:
        problems.append("UNKNOWN_FINDINGS:" + ",".join(sorted(extra)))
    if len(coverage) != len(set(coverage)):
        problems.append("FINDINGS_DUPLICATED")
    return problems


def evaluate_pr223_dispatch_finality(
    evidence: PR223DispatchFinalityEvidence,
) -> PR223DispatchFinalityReport:
    """Evaluate the PR-223 dispatch/finality recovery matrix evidence."""

    reasons: list[str] = []
    if evidence.schema_version != SCHEMA_VERSION:
        reasons.append("SCHEMA_VERSION_MISMATCH")

    reasons.extend(_coverage_problems(evidence.finding_coverage))

    if not evidence.evidence_refs:
        reasons.append("MATERIALIZED_EVIDENCE_MISSING")
    for ref in evidence.evidence_refs:
        reasons.extend(f"EVIDENCE_REF_INVALID:{problem}" for problem in ref.problems())
        if ref.produced_by_runtime:
            reasons.append(f"EVIDENCE_SELF_ATTESTED:{ref.name}")

    reasons.extend(evidence.prerequisites.problems())
    reasons.extend(evidence.trust_authorization.problems())
    reasons.extend(evidence.custody.problems())
    reasons.extend(evidence.dispatch.problems())
    reasons.extend(evidence.transport_finality.problems())
    reasons.extend(evidence.archive_reconciliation_governance.problems())

    capabilities = evidence.capabilities
    forbidden_capabilities = {
        "SIGNER_ALLOWED": capabilities.signer_allowed,
        "SENDER_ALLOWED": capabilities.sender_allowed,
        "LIVE_EXECUTION_ALLOWED": capabilities.live_execution_allowed,
        "PRIVATE_KEY_MATERIAL_ALLOWED": capabilities.private_key_material_allowed,
        "AUTOMATIC_CANARY_ALLOWED": capabilities.automatic_canary_allowed,
        "UNRESTRICTED_LIVE_ALLOWED": capabilities.unrestricted_live_allowed,
    }
    reasons.extend(reason for reason, enabled in forbidden_capabilities.items() if enabled)

    accepted = not reasons
    return PR223DispatchFinalityReport(
        schema_version=SCHEMA_VERSION,
        accepted=accepted,
        reasons=tuple(reasons),
        dispatch_finality_review_allowed=accepted,
        signer_allowed=False,
        sender_allowed=False,
        live_execution_allowed=False,
        private_key_material_allowed=False,
        automatic_canary_allowed=False,
        unrestricted_live_allowed=False,
    )
