"""MPR-CLOSE-05 isolated signer, Jito settlement and bounded canary gate.

This module is an offline, side-effect-free implementation boundary for the
MPR-CLOSE-05 closure PR.  It models the authorization envelope a runtime may
send to an isolated signer, the durable submission outbox state machine, the
Jito settlement rules and the canary latches that must remain default-off.

It deliberately never loads private keys, signs bytes, opens a socket, submits a
transaction, polls Jito/RPC or enables unrestricted live execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Mapping, Sequence

SCHEMA_VERSION = "mpr-close-05.isolated-signer-jito-canary.v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_UPSTREAM_EVIDENCE: tuple[str, ...] = (
    "MPR-CLOSE-01",
    "MPR-CLOSE-02",
    "MPR-CLOSE-03",
    "MPR-CLOSE-04",
)
REQUIRED_CANARY_LATCHES: tuple[str, ...] = (
    "fresh_production_cutover_manifest",
    "fresh_provider_drift_report",
    "no_unknown_outstanding_attempts",
    "exact_message_proof",
    "capital_cap",
    "per_trade_cap",
    "daily_loss_cap",
    "emergency_stop_clear",
    "second_human_approval",
    "auto_stop_after_first_failure",
    "auto_stop_after_budget_exhausted",
)
SUBMISSION_STATES: tuple[str, ...] = (
    "submission_intent_created",
    "signed_by_isolated_signer",
    "submitted_to_transport",
    "landed",
    "confirmed",
    "finalized",
    "rejected",
    "expired",
)
TERMINAL_STATES = frozenset({"finalized", "rejected", "expired"})


class MPRClose05State(str, Enum):
    READY_FOR_BOUNDED_CANARY_REVIEW = "ready_for_bounded_canary_review"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class MPRClose05Violation:
    code: str
    message: str


@dataclass(frozen=True)
class SignerAuthorizationEnvelope:
    """What runtime may hand to the isolated signer.

    The runtime is allowed to pass only a stable authorization envelope and exact
    message bytes/hash.  It must not pass private key bytes or ask the signer to
    mutate the message after local simulation and policy approval.
    """

    message_hash: str
    message_bytes_hash: str
    policy_identity_hash: str
    config_generation_hash: str
    reservation_hash: str
    opportunity_id: str
    nonce: str
    issued_at_ns: int
    expires_at_ns: int
    audit_event_hash: str
    runtime_private_key_access: bool = False
    signer_mutates_message: bool = False


@dataclass(frozen=True)
class SubmissionOutboxEvidence:
    state_sequence: tuple[str, ...]
    intent_hash: str
    signed_payload_hash: str
    transport_payload_hash: str
    ack_recorded_as_terminal: bool
    bundle_id_recorded_as_terminal: bool
    durable_before_transport: bool
    unknown_outstanding_attempts: bool


@dataclass(frozen=True)
class JitoSettlementEvidence:
    local_exact_simulation_hash: str
    simulation_before_send: bool
    skip_preflight_true: bool
    bundle_status_polled: bool
    ack_not_settlement: bool
    bundle_id_not_settlement: bool
    tip_budget_enforced: bool
    minimum_tip_policy_enforced: bool
    unbundling_protection_enforced: bool
    uncled_block_protection_enforced: bool
    tip_inside_strategy_transaction_when_required: bool
    finalized_onchain_reconciliation: bool


@dataclass(frozen=True)
class CanaryLatchEvidence:
    upstream_evidence: Mapping[str, str]
    latch_state: Mapping[str, bool]
    independent_approval_hashes: tuple[str, ...]
    unrestricted_live_available: bool
    live_canary_available_by_default: bool
    canary_requested: bool = False


@dataclass(frozen=True)
class MPRClose05Evidence:
    signer: SignerAuthorizationEnvelope
    outbox: SubmissionOutboxEvidence
    jito: JitoSettlementEvidence
    canary: CanaryLatchEvidence


@dataclass(frozen=True)
class MPRClose05Report:
    schema_version: str
    state: MPRClose05State
    blockers: tuple[MPRClose05Violation, ...]
    evidence_hash: str
    signer_allowed: bool
    sender_allowed: bool
    unrestricted_live_available: bool
    bounded_canary_default_off: bool
    bounded_canary_review_ready: bool


class NonceReplayCache:
    """Tiny deterministic nonce cache for tests and offline verifiers."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def consume(self, nonce: str) -> bool:
        if not nonce or nonce in self._seen:
            return False
        self._seen.add(nonce)
        return True


def evaluate_mpr_close_05_evidence(evidence: MPRClose05Evidence) -> MPRClose05Report:
    blockers: list[MPRClose05Violation] = []
    _validate_signer_authorization(evidence.signer, blockers)
    _validate_submission_outbox(evidence.outbox, blockers)
    _validate_jito_semantics(evidence.jito, blockers)
    _validate_canary_latches(evidence.canary, blockers)
    unique = tuple(_dedupe(blockers))
    canary_review_ready = not unique and evidence.canary.canary_requested
    return MPRClose05Report(
        schema_version=SCHEMA_VERSION,
        state=(
            MPRClose05State.BLOCKED
            if unique
            else MPRClose05State.READY_FOR_BOUNDED_CANARY_REVIEW
        ),
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        signer_allowed=False,
        sender_allowed=False,
        unrestricted_live_available=False,
        bounded_canary_default_off=not evidence.canary.live_canary_available_by_default,
        bounded_canary_review_ready=canary_review_ready,
    )


def authorize_exact_message(
    envelope: SignerAuthorizationEnvelope,
    *,
    message_bytes: bytes,
    replay_cache: NonceReplayCache,
    now_ns: int,
) -> str:
    """Return an authorization hash only for an exact, fresh, non-replayed message.

    This helper is intentionally not a signer.  It proves the pre-signing
    boundary: audit event first, exact bytes/hash only, expiry and nonce replay
    enforced, and no runtime key material.
    """

    blockers: list[MPRClose05Violation] = []
    _validate_signer_authorization(envelope, blockers)
    if hashlib.sha256(message_bytes).hexdigest() != envelope.message_bytes_hash:
        _add(blockers, "SIGNER_MESSAGE_BYTES_CHANGED", "message bytes do not match approved hash")
    if now_ns < envelope.issued_at_ns or now_ns >= envelope.expires_at_ns:
        _add(blockers, "SIGNER_AUTHORIZATION_EXPIRED", "authorization is not currently valid")
    if not replay_cache.consume(envelope.nonce):
        _add(blockers, "SIGNER_NONCE_REPLAY", "nonce was already consumed or is empty")
    if blockers:
        raise ValueError("; ".join(f"{item.code}: {item.message}" for item in blockers))
    return _stable_hash(envelope)


def _validate_signer_authorization(
    signer: SignerAuthorizationEnvelope,
    blockers: list[MPRClose05Violation],
) -> None:
    for field_name in (
        "message_hash",
        "message_bytes_hash",
        "policy_identity_hash",
        "config_generation_hash",
        "reservation_hash",
        "audit_event_hash",
    ):
        if not _is_hash(getattr(signer, field_name)):
            _add(blockers, "SIGNER_BAD_HASH", f"{field_name} must be sha256")
    if not signer.opportunity_id.strip():
        _add(blockers, "SIGNER_OPPORTUNITY_ID_MISSING", "opportunity_id is required")
    if not signer.nonce.strip():
        _add(blockers, "SIGNER_NONCE_MISSING", "nonce is required")
    if signer.issued_at_ns < 0 or signer.expires_at_ns <= signer.issued_at_ns:
        _add(blockers, "SIGNER_BAD_EXPIRY", "authorization must have a positive validity window")
    if signer.runtime_private_key_access:
        _add(blockers, "SIGNER_RUNTIME_KEY_ACCESS", "runtime must never access private-key bytes")
    if signer.signer_mutates_message:
        _add(blockers, "SIGNER_MESSAGE_MUTATION", "signer may sign only exact approved message bytes/hash")


def _validate_submission_outbox(
    outbox: SubmissionOutboxEvidence,
    blockers: list[MPRClose05Violation],
) -> None:
    if outbox.state_sequence[:3] != SUBMISSION_STATES[:3]:
        _add(
            blockers,
            "OUTBOX_STATE_PREFIX_INVALID",
            "submission intent must be durable before signing and transport",
        )
    unknown = [state for state in outbox.state_sequence if state not in SUBMISSION_STATES]
    if unknown:
        _add(blockers, "OUTBOX_UNKNOWN_STATE", "unknown states: " + ", ".join(unknown))
    terminals = [state for state in outbox.state_sequence if state in TERMINAL_STATES]
    if len(terminals) > 1:
        _add(blockers, "OUTBOX_MULTIPLE_TERMINALS", "only one terminal state is allowed")
    if outbox.ack_recorded_as_terminal:
        _add(blockers, "OUTBOX_ACK_TERMINAL", "transport ACK must not be terminal")
    if outbox.bundle_id_recorded_as_terminal:
        _add(blockers, "OUTBOX_BUNDLE_ID_TERMINAL", "bundle ID must not be terminal")
    if not outbox.durable_before_transport:
        _add(blockers, "OUTBOX_NOT_DURABLE", "intent must be written before transport")
    if outbox.unknown_outstanding_attempts:
        _add(blockers, "OUTBOX_UNKNOWN_ATTEMPTS", "unknown outstanding attempts block canary")
    for field_name in ("intent_hash", "signed_payload_hash", "transport_payload_hash"):
        if not _is_hash(getattr(outbox, field_name)):
            _add(blockers, "OUTBOX_BAD_HASH", f"{field_name} must be sha256")


def _validate_jito_semantics(
    jito: JitoSettlementEvidence,
    blockers: list[MPRClose05Violation],
) -> None:
    if not _is_hash(jito.local_exact_simulation_hash):
        _add(blockers, "JITO_BAD_SIMULATION_HASH", "local exact simulation hash is required")
    required = (
        "simulation_before_send",
        "skip_preflight_true",
        "bundle_status_polled",
        "ack_not_settlement",
        "bundle_id_not_settlement",
        "tip_budget_enforced",
        "minimum_tip_policy_enforced",
        "unbundling_protection_enforced",
        "uncled_block_protection_enforced",
        "tip_inside_strategy_transaction_when_required",
        "finalized_onchain_reconciliation",
    )
    for field_name in required:
        if getattr(jito, field_name) is not True:
            _add(blockers, "JITO_SEMANTICS_INCOMPLETE", f"{field_name} is required")


def _validate_canary_latches(
    canary: CanaryLatchEvidence,
    blockers: list[MPRClose05Violation],
) -> None:
    for name in REQUIRED_UPSTREAM_EVIDENCE:
        digest = canary.upstream_evidence.get(name)
        if not digest or not _is_hash(digest):
            _add(blockers, "CANARY_UPSTREAM_EVIDENCE_MISSING", f"{name} evidence digest is required")
    for name in REQUIRED_CANARY_LATCHES:
        if canary.latch_state.get(name) is not True:
            _add(blockers, "CANARY_LATCH_OPEN", f"{name} latch must be closed/true")
    if len(set(canary.independent_approval_hashes)) < 2:
        _add(blockers, "CANARY_SECOND_APPROVAL_MISSING", "two distinct human approval hashes are required")
    for digest in canary.independent_approval_hashes:
        if not _is_hash(digest):
            _add(blockers, "CANARY_BAD_APPROVAL_HASH", "approval hashes must be sha256")
    if canary.unrestricted_live_available:
        _add(blockers, "CANARY_UNRESTRICTED_LIVE_FORBIDDEN", "unrestricted live remains unavailable")
    if canary.live_canary_available_by_default:
        _add(blockers, "CANARY_DEFAULT_ON_FORBIDDEN", "bounded canary must be default-off")


def sample_ready_evidence(*, canary_requested: bool = True) -> MPRClose05Evidence:
    """Deterministic verifier fixture with all latches closed but default live off."""

    h = lambda char: char * 64
    return MPRClose05Evidence(
        signer=SignerAuthorizationEnvelope(
            message_hash=h("a"),
            message_bytes_hash=h("b"),
            policy_identity_hash=h("c"),
            config_generation_hash=h("d"),
            reservation_hash=h("e"),
            opportunity_id="opp-mpr-close-05-fixture",
            nonce="nonce-mpr-close-05-fixture",
            issued_at_ns=100,
            expires_at_ns=1_000,
            audit_event_hash=h("f"),
        ),
        outbox=SubmissionOutboxEvidence(
            state_sequence=(
                "submission_intent_created",
                "signed_by_isolated_signer",
                "submitted_to_transport",
                "finalized",
            ),
            intent_hash=h("1"),
            signed_payload_hash=h("2"),
            transport_payload_hash=h("3"),
            ack_recorded_as_terminal=False,
            bundle_id_recorded_as_terminal=False,
            durable_before_transport=True,
            unknown_outstanding_attempts=False,
        ),
        jito=JitoSettlementEvidence(
            local_exact_simulation_hash=h("4"),
            simulation_before_send=True,
            skip_preflight_true=True,
            bundle_status_polled=True,
            ack_not_settlement=True,
            bundle_id_not_settlement=True,
            tip_budget_enforced=True,
            minimum_tip_policy_enforced=True,
            unbundling_protection_enforced=True,
            uncled_block_protection_enforced=True,
            tip_inside_strategy_transaction_when_required=True,
            finalized_onchain_reconciliation=True,
        ),
        canary=CanaryLatchEvidence(
            upstream_evidence={name: h(str(index + 5)) for index, name in enumerate(REQUIRED_UPSTREAM_EVIDENCE)},
            latch_state={name: True for name in REQUIRED_CANARY_LATCHES},
            independent_approval_hashes=(h("9"), h("8")),
            unrestricted_live_available=False,
            live_canary_available_by_default=False,
            canary_requested=canary_requested,
        ),
    )


def report_to_json(report: MPRClose05Report) -> str:
    return json.dumps(asdict(report), sort_keys=True, indent=2)


def _add(blockers: list[MPRClose05Violation], code: str, message: str) -> None:
    blockers.append(MPRClose05Violation(code=code, message=message))


def _dedupe(blockers: Iterable[MPRClose05Violation]) -> Iterable[MPRClose05Violation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key not in seen:
            seen.add(key)
            yield blocker


def _is_hash(value: str) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def _stable_hash(value: object) -> str:
    payload = asdict(value) if hasattr(value, "__dataclass_fields__") else value
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
