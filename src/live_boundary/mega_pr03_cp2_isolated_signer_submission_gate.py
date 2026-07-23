"""MEGA-PR-03 CP2 isolated signer and bounded submission gate.

Side-effect-free evidence validator only. It does not load keys, open IPC,
sign, submit, call RPC/Jito, or enable live execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "mega-pr03.cp2.isolated-signer-bounded-submission-gate.v1"
REQUIRED_COVERAGE: tuple[str, ...] = (
    "runtime.live-entrypoint",
    "execution.finalized-settlement-binding",
    "external.jito-low-latency",
    "submission.jito-unbundling-protection",
    "evidence.finalized-economic-proof",
    "security.signer-isolation",
    "security.secret-incident-drill",
    "canary.permit-budget-latches",
    "canary.second-human-approval",
    "IMPL-23",
    "IMPL-24",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class MegaPR03CP2State(str, Enum):
    READY_FOR_CP3_FINALIZED_SETTLEMENT_REVIEW = "ready_for_cp3_finalized_settlement_review"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class SignerIsolationEvidence:
    isolated_process_identity_hash: str
    signer_image_digest: str
    ipc_policy_hash: str
    key_authority_kind: str
    key_authority_generation_hash: str
    signed_message_policy_hash: str
    message_decoder_hash: str
    replay_store_hash: str
    durable_authorization_outbox_hash: str
    runtime_container_has_key_access: bool
    private_key_material_exportable: bool
    private_key_in_environment: bool
    caller_supplies_signer_metadata: bool
    signer_decodes_message_bytes: bool
    owner_only_key_source: bool = False


@dataclass(frozen=True)
class ExactMessageAuthorizationEvidence:
    exact_simulated_message_hash: str
    signer_decoded_message_hash: str
    simulation_evidence_hash: str
    semantic_policy_hash: str
    signer_policy_generation_hash: str
    cluster_genesis_hash: str
    alt_snapshot_hash: str
    current_block_height_at_authorization: int
    last_valid_block_height: int
    blockheight_safety_margin: int
    trusted_now_unix_ns: int
    signer_expires_at_unix_ns: int
    maximum_permit_ttl_ns: int


@dataclass(frozen=True)
class BoundedSubmissionEvidence:
    selected_transport: str
    bundle_or_signature_identity_hash: str
    wire_message_digest: str
    durable_intent_store_hash: str
    rate_limit_policy_hash: str
    retry_budget_hash: str
    max_rpc_send_attempts: int
    max_jito_bundle_attempts: int
    max_unknown_outcome_hold_ns: int
    durable_intent_created_before_network: bool
    staged_write_evidence_required: bool
    no_blind_resend: bool
    ack_is_not_landing: bool
    confirmed_is_not_finality: bool
    jito_unbundling_safeguards_required: bool
    transaction_local_assertions_required: bool


@dataclass(frozen=True)
class CanaryBoundaryEvidence:
    release_bound_paper_evidence_hash: str
    mega_pr02_paper_qualified: bool
    two_distinct_approvers_required: bool
    second_human_approval_required: bool
    one_in_flight_intent_limit: bool
    absolute_loss_budget_lamports: int
    absolute_trade_count_limit: int
    provider_drift_latch_required: bool
    reconciliation_latch_required: bool
    evidence_latch_required: bool
    bounded_canary_review_requested: bool = True
    live_execution_requested: bool = False
    unrestricted_live_requested: bool = False
    automatic_scale_up_requested: bool = False


@dataclass(frozen=True)
class MegaPR03CP2Evidence:
    coverage_items: tuple[str, ...]
    signer_isolation: SignerIsolationEvidence
    exact_message_authorization: ExactMessageAuthorizationEvidence
    bounded_submission: BoundedSubmissionEvidence
    canary_boundary: CanaryBoundaryEvidence


@dataclass(frozen=True)
class MegaPR03CP2Violation:
    code: str
    message: str


@dataclass(frozen=True)
class MegaPR03CP2Report:
    schema_version: str
    state: MegaPR03CP2State
    blockers: tuple[MegaPR03CP2Violation, ...]
    evidence_hash: str
    cp3_finalized_settlement_review_allowed: bool
    bounded_canary_review_allowed: bool
    live_execution_allowed: bool
    unrestricted_live_allowed: bool
    automatic_scale_up_allowed: bool
    required_coverage: tuple[str, ...]


def evaluate_mega_pr03_cp2_evidence(evidence: MegaPR03CP2Evidence) -> MegaPR03CP2Report:
    blockers: list[MegaPR03CP2Violation] = []
    _coverage(evidence.coverage_items, blockers)
    _signer(evidence.signer_isolation, blockers)
    _message(evidence.exact_message_authorization, blockers)
    _submission(evidence.bounded_submission, blockers)
    _canary(evidence.canary_boundary, blockers)

    unique = tuple(_dedupe(blockers))
    ready = not unique
    return MegaPR03CP2Report(
        schema_version=SCHEMA_VERSION,
        state=(
            MegaPR03CP2State.READY_FOR_CP3_FINALIZED_SETTLEMENT_REVIEW
            if ready
            else MegaPR03CP2State.BLOCKED
        ),
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        cp3_finalized_settlement_review_allowed=ready,
        bounded_canary_review_allowed=ready and evidence.canary_boundary.bounded_canary_review_requested,
        live_execution_allowed=False,
        unrestricted_live_allowed=False,
        automatic_scale_up_allowed=False,
        required_coverage=REQUIRED_COVERAGE,
    )


def _coverage(items: Sequence[str], out: list[MegaPR03CP2Violation]) -> None:
    missing = [item for item in REQUIRED_COVERAGE if item not in items]
    if missing:
        _add(out, "MEGA_PR03_CP2_MISSING_COVERAGE", f"missing coverage items: {missing}")
    if len(set(items)) != len(tuple(items)):
        _add(out, "MEGA_PR03_CP2_DUPLICATE_COVERAGE", "coverage items must be unique")


def _signer(s: SignerIsolationEvidence, out: list[MegaPR03CP2Violation]) -> None:
    _hash_fields(
        out,
        "MEGA_PR03_CP2_BAD_SIGNER_HASH",
        isolated_process_identity_hash=s.isolated_process_identity_hash,
        ipc_policy_hash=s.ipc_policy_hash,
        key_authority_generation_hash=s.key_authority_generation_hash,
        signed_message_policy_hash=s.signed_message_policy_hash,
        message_decoder_hash=s.message_decoder_hash,
        replay_store_hash=s.replay_store_hash,
        durable_authorization_outbox_hash=s.durable_authorization_outbox_hash,
    )
    if not _digest(s.signer_image_digest):
        _add(out, "MEGA_PR03_CP2_BAD_SIGNER_IMAGE_DIGEST", "signer image must be digest pinned")
    if s.key_authority_kind not in {"hsm", "kms", "owner_only_file"}:
        _add(out, "MEGA_PR03_CP2_BAD_KEY_AUTHORITY", "key authority must be hsm/kms/owner_only_file")
    if s.key_authority_kind == "owner_only_file" and not s.owner_only_key_source:
        _add(out, "MEGA_PR03_CP2_OWNER_ONLY_KEY_REQUIRED", "owner-only key source proof required")
    if s.runtime_container_has_key_access:
        _add(out, "MEGA_PR03_CP2_RUNTIME_KEY_ACCESS", "runtime container must not access key material")
    if s.private_key_material_exportable:
        _add(out, "MEGA_PR03_CP2_EXPORTABLE_KEY", "private key must not be exportable")
    if s.private_key_in_environment:
        _add(out, "MEGA_PR03_CP2_KEY_IN_ENVIRONMENT", "private key must not be in generic environment")
    if s.caller_supplies_signer_metadata:
        _add(out, "MEGA_PR03_CP2_CALLER_METADATA_TRUSTED", "signer cannot trust caller metadata")
    if not s.signer_decodes_message_bytes:
        _add(out, "MEGA_PR03_CP2_SIGNER_MUST_DECODE_BYTES", "signer must derive identity from message bytes")


def _message(m: ExactMessageAuthorizationEvidence, out: list[MegaPR03CP2Violation]) -> None:
    _hash_fields(
        out,
        "MEGA_PR03_CP2_BAD_MESSAGE_HASH",
        exact_simulated_message_hash=m.exact_simulated_message_hash,
        signer_decoded_message_hash=m.signer_decoded_message_hash,
        simulation_evidence_hash=m.simulation_evidence_hash,
        semantic_policy_hash=m.semantic_policy_hash,
        signer_policy_generation_hash=m.signer_policy_generation_hash,
        cluster_genesis_hash=m.cluster_genesis_hash,
        alt_snapshot_hash=m.alt_snapshot_hash,
    )
    if m.exact_simulated_message_hash != m.signer_decoded_message_hash:
        _add(out, "MEGA_PR03_CP2_MESSAGE_HASH_MISMATCH", "signer-decoded message must equal simulated message")
    for name in (
        "current_block_height_at_authorization",
        "last_valid_block_height",
        "blockheight_safety_margin",
        "trusted_now_unix_ns",
        "signer_expires_at_unix_ns",
        "maximum_permit_ttl_ns",
    ):
        if not _nonnegative_int(getattr(m, name)):
            _add(out, "MEGA_PR03_CP2_BAD_MESSAGE_NUMBER", f"{name} must be non-negative integer")
    if m.current_block_height_at_authorization + m.blockheight_safety_margin >= m.last_valid_block_height:
        _add(out, "MEGA_PR03_CP2_BLOCKHEIGHT_EXPIRED", "blockheight must be inside last valid height with margin")
    ttl = m.signer_expires_at_unix_ns - m.trusted_now_unix_ns
    if ttl <= 0:
        _add(out, "MEGA_PR03_CP2_PERMIT_EXPIRED", "signer permit must not be expired")
    if ttl > m.maximum_permit_ttl_ns:
        _add(out, "MEGA_PR03_CP2_PERMIT_TTL_TOO_LONG", "signer permit TTL must be bounded")


def _submission(s: BoundedSubmissionEvidence, out: list[MegaPR03CP2Violation]) -> None:
    _hash_fields(
        out,
        "MEGA_PR03_CP2_BAD_SUBMISSION_HASH",
        bundle_or_signature_identity_hash=s.bundle_or_signature_identity_hash,
        wire_message_digest=s.wire_message_digest,
        durable_intent_store_hash=s.durable_intent_store_hash,
        rate_limit_policy_hash=s.rate_limit_policy_hash,
        retry_budget_hash=s.retry_budget_hash,
    )
    if s.selected_transport not in {"solana_rpc", "jito_bundle"}:
        _add(out, "MEGA_PR03_CP2_BAD_TRANSPORT", "one admitted transport must be selected")
    attempts = s.max_rpc_send_attempts + s.max_jito_bundle_attempts
    if attempts <= 0 or attempts > 3:
        _add(out, "MEGA_PR03_CP2_UNBOUNDED_SEND_ATTEMPTS", "send attempts must be tightly bounded")
    if s.selected_transport == "solana_rpc" and s.max_rpc_send_attempts <= 0:
        _add(out, "MEGA_PR03_CP2_TRANSPORT_ATTEMPT_MISMATCH", "RPC transport requires RPC attempts")
    if s.selected_transport == "jito_bundle" and s.max_jito_bundle_attempts <= 0:
        _add(out, "MEGA_PR03_CP2_TRANSPORT_ATTEMPT_MISMATCH", "Jito transport requires bundle attempts")
    if not _positive_int(s.max_unknown_outcome_hold_ns):
        _add(out, "MEGA_PR03_CP2_UNKNOWN_OUTCOME_BUDGET_REQUIRED", "unknown outcome hold budget required")
    required_flags = {
        "MEGA_PR03_CP2_INTENT_AFTER_NETWORK": (s.durable_intent_created_before_network, "durable intent before network required"),
        "MEGA_PR03_CP2_NO_STAGED_WRITE_EVIDENCE": (s.staged_write_evidence_required, "staged write evidence required"),
        "MEGA_PR03_CP2_BLIND_RESEND_ALLOWED": (s.no_blind_resend, "blind resend must be forbidden"),
        "MEGA_PR03_CP2_ACK_AS_LANDING": (s.ack_is_not_landing, "ACK/bundle id is not landing truth"),
        "MEGA_PR03_CP2_CONFIRMED_AS_FINALITY": (s.confirmed_is_not_finality, "confirmed is not finality"),
        "MEGA_PR03_CP2_MISSING_JITO_SAFEGUARDS": (s.jito_unbundling_safeguards_required, "Jito safeguards required"),
        "MEGA_PR03_CP2_MISSING_TX_LOCAL_ASSERTIONS": (s.transaction_local_assertions_required, "transaction-local assertions required"),
    }
    for code, (ok, msg) in required_flags.items():
        if not ok:
            _add(out, code, msg)


def _canary(c: CanaryBoundaryEvidence, out: list[MegaPR03CP2Violation]) -> None:
    if not _sha(c.release_bound_paper_evidence_hash):
        _add(out, "MEGA_PR03_CP2_BAD_RELEASE_EVIDENCE_HASH", "release-bound paper evidence hash required")
    if not c.mega_pr02_paper_qualified:
        _add(out, "MEGA_PR03_CP2_MEGA_PR02_REQUIRED", "MEGA-PR-03 depends on accepted MEGA-PR-02")
    if not (c.two_distinct_approvers_required and c.second_human_approval_required):
        _add(out, "MEGA_PR03_CP2_TWO_PERSON_REVIEW_REQUIRED", "two distinct verified approvers required")
    if not c.one_in_flight_intent_limit:
        _add(out, "MEGA_PR03_CP2_ONE_IN_FLIGHT_REQUIRED", "one in-flight intent limit required")
    if not _positive_int(c.absolute_loss_budget_lamports):
        _add(out, "MEGA_PR03_CP2_BAD_LOSS_BUDGET", "absolute loss budget must be positive")
    if not _positive_int(c.absolute_trade_count_limit):
        _add(out, "MEGA_PR03_CP2_BAD_TRADE_LIMIT", "absolute trade limit must be positive")
    for name in ("provider_drift_latch_required", "reconciliation_latch_required", "evidence_latch_required"):
        if not getattr(c, name):
            _add(out, "MEGA_PR03_CP2_MISSING_CANARY_LATCH", f"{name} must be required")
    if c.live_execution_requested:
        _add(out, "MEGA_PR03_CP2_LIVE_EXECUTION_REQUESTED", "CP2 cannot enable live execution")
    if c.unrestricted_live_requested:
        _add(out, "MEGA_PR03_CP2_UNRESTRICTED_LIVE_REQUESTED", "unrestricted live remains forbidden")
    if c.automatic_scale_up_requested:
        _add(out, "MEGA_PR03_CP2_AUTOMATIC_SCALE_UP_REQUESTED", "automatic scale-up remains forbidden")


def blockers_by_code(report: MegaPR03CP2Report) -> Mapping[str, tuple[MegaPR03CP2Violation, ...]]:
    grouped: dict[str, list[MegaPR03CP2Violation]] = {}
    for blocker in report.blockers:
        grouped.setdefault(blocker.code, []).append(blocker)
    return {code: tuple(items) for code, items in grouped.items()}


def _hash_fields(out: list[MegaPR03CP2Violation], code: str, **values: str) -> None:
    for name, value in values.items():
        if not _sha(value):
            _add(out, code, f"{name} must be strict sha256")


def _sha(value: object) -> bool:
    return isinstance(value, str) and bool(HEX64.match(value)) and value not in {"0" * 64, "f" * 64}


def _digest(value: object) -> bool:
    return isinstance(value, str) and bool(DIGEST.match(value)) and value != f"sha256:{'0' * 64}"


def _nonnegative_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def _positive_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(_json(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _json(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {k: _json(v) for k, v in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_json(v) for v in value]
    return value


def _add(out: list[MegaPR03CP2Violation], code: str, message: str) -> None:
    out.append(MegaPR03CP2Violation(code, message))


def _dedupe(blockers: Iterable[MegaPR03CP2Violation]) -> Iterable[MegaPR03CP2Violation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key not in seen:
            seen.add(key)
            yield blocker
