"""MEGA-PR-03 V3 isolated-signer cryptographic evidence gate.

Offline validator only: it does not load keys, sign, verify bytes, submit
transactions, call RPC/Jito, or enable live execution. It prevents treating a
caller-supplied signed-wire digest as proof that the isolated signer produced
and locally verified a signature.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Mapping, Sequence

SCHEMA_VERSION = "mega-pr03.v3.signer-cryptographic-evidence-gate.v1"
REQUIRED_COVERAGE: tuple[str, ...] = (
    "IMPL-39",
    "signer.exact-message-bytes-reviewed",
    "signer.key-loaded-inside-boundary",
    "signer.signature-produced-by-signer",
    "signer.local-signature-verification",
    "signer.pubkey-message-signature-binding",
    "signer.signed-wire-built-by-signer",
    "signer.cryptographic-evidence-before-dispatch",
    "signer.one-time-dispatch-fencing",
    "signer.no-caller-supplied-signed-wire-digest",
)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class MegaPR03V3State(str, Enum):
    """Stable result states for V3 signer evidence."""

    READY_FOR_FINALIZED_RECONCILIATION_REVIEW = "ready_for_finalized_reconciliation_review"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class SignerMessageReviewEvidence:
    """Signer-side parsing and review of exact message bytes."""

    reviewed_message_bytes_sha256: str
    caller_intent_message_sha256: str
    decoded_programs_sha256: str
    decoded_accounts_sha256: str
    decoded_amounts_fees_sha256: str
    semantic_bounds_sha256: str
    simulation_evidence_sha256: str
    signer_reparsed_exact_message_bytes: bool
    programs_accounts_amounts_fees_reviewed: bool
    simulation_message_identity_matched: bool
    message_mutation_after_review_impossible: bool


@dataclass(frozen=True)
class SignerSignatureEvidence:
    """Proof that signing happened inside the isolated signer boundary."""

    isolated_signer_process_sha256: str
    signer_binary_sha256: str
    key_authority_generation_sha256: str
    public_key_sha256: str
    signature_sha256: str
    signed_wire_sha256: str
    verification_transcript_sha256: str
    key_loaded_inside_signer_boundary: bool
    private_key_exportable: bool
    private_key_visible_to_runtime: bool
    signature_produced_by_isolated_signer: bool
    signed_wire_built_by_isolated_signer: bool
    signature_verified_against_public_key_and_message: bool
    caller_supplied_signed_wire_sha256_present: bool
    caller_supplied_signature_sha256_present: bool


@dataclass(frozen=True)
class DispatchCryptographicEvidence:
    """Durable one-time dispatch fencing for signer-produced bytes."""

    evidence_record_sha256: str
    authorization_intent_sha256: str
    dispatch_token_sha256: str
    dispatch_receipt_sha256: str
    evidence_persisted_before_dispatch: bool
    dispatch_token_consumed_once: bool
    replay_or_duplicate_dispatch_rejected: bool
    durable_audit_receipt_written: bool
    crash_recovery_does_not_replay_signature: bool


@dataclass(frozen=True)
class MegaPR03V3SignerEvidence:
    """Complete V3 IMPL-39 evidence envelope."""

    coverage_items: tuple[str, ...]
    mega_pr02_paper_qualified: bool
    mega_pr02_evidence_sha256: str
    two_person_approval_sha256: str
    message_review: SignerMessageReviewEvidence
    signature: SignerSignatureEvidence
    dispatch: DispatchCryptographicEvidence
    live_execution_requested: bool = False
    sender_requested: bool = False
    unrestricted_live_requested: bool = False
    automatic_scale_up_requested: bool = False


@dataclass(frozen=True)
class MegaPR03V3Violation:
    code: str
    message: str


@dataclass(frozen=True)
class MegaPR03V3Report:
    schema_version: str
    state: MegaPR03V3State
    blockers: tuple[MegaPR03V3Violation, ...]
    evidence_hash: str
    finalized_reconciliation_review_allowed: bool
    bounded_canary_review_allowed: bool
    live_execution_allowed: bool
    sender_allowed: bool
    unrestricted_live_allowed: bool
    automatic_scale_up_allowed: bool
    required_coverage: tuple[str, ...]


def evaluate_mega_pr03_v3_signer_evidence(evidence: MegaPR03V3SignerEvidence) -> MegaPR03V3Report:
    """Evaluate V3 signer evidence without performing any live action."""

    blockers: list[MegaPR03V3Violation] = []
    _coverage(evidence.coverage_items, blockers)
    _dependency_and_live_boundary(evidence, blockers)
    _message_review(evidence.message_review, blockers)
    _signature(evidence.signature, blockers)
    _dispatch(evidence.dispatch, blockers)

    unique = tuple(_dedupe(blockers))
    ready = not unique
    return MegaPR03V3Report(
        schema_version=SCHEMA_VERSION,
        state=(
            MegaPR03V3State.READY_FOR_FINALIZED_RECONCILIATION_REVIEW
            if ready
            else MegaPR03V3State.BLOCKED
        ),
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        finalized_reconciliation_review_allowed=ready,
        bounded_canary_review_allowed=ready,
        live_execution_allowed=False,
        sender_allowed=False,
        unrestricted_live_allowed=False,
        automatic_scale_up_allowed=False,
        required_coverage=REQUIRED_COVERAGE,
    )


def blockers_by_code(report: MegaPR03V3Report) -> Mapping[str, tuple[MegaPR03V3Violation, ...]]:
    grouped: dict[str, list[MegaPR03V3Violation]] = {}
    for blocker in report.blockers:
        grouped.setdefault(blocker.code, []).append(blocker)
    return {code: tuple(items) for code, items in grouped.items()}


def _coverage(items: Sequence[str], out: list[MegaPR03V3Violation]) -> None:
    missing = [item for item in REQUIRED_COVERAGE if item not in items]
    if missing:
        _add(out, "MEGA_PR03_V3_MISSING_COVERAGE", f"missing coverage items: {missing}")
    if len(set(items)) != len(tuple(items)):
        _add(out, "MEGA_PR03_V3_DUPLICATE_COVERAGE", "coverage items must be unique")


def _dependency_and_live_boundary(e: MegaPR03V3SignerEvidence, out: list[MegaPR03V3Violation]) -> None:
    _hash_fields(out, "MEGA_PR03_V3_BAD_DEPENDENCY_HASH", e.mega_pr02_evidence_sha256, e.two_person_approval_sha256)
    if not e.mega_pr02_paper_qualified:
        _add(out, "MEGA_PR03_V3_MEGA_PR02_NOT_QUALIFIED", "MEGA-PR-03 depends on accepted MEGA-PR-02 evidence")
    for code, requested in (
        ("MEGA_PR03_V3_LIVE_EXECUTION_REQUESTED", e.live_execution_requested),
        ("MEGA_PR03_V3_SENDER_REQUESTED", e.sender_requested),
        ("MEGA_PR03_V3_UNRESTRICTED_LIVE_REQUESTED", e.unrestricted_live_requested),
        ("MEGA_PR03_V3_AUTOMATIC_SCALE_UP_REQUESTED", e.automatic_scale_up_requested),
    ):
        if requested:
            _add(out, code, "this evidence gate cannot enable live/sender/unrestricted capability")


def _message_review(m: SignerMessageReviewEvidence, out: list[MegaPR03V3Violation]) -> None:
    _hash_fields(
        out,
        "MEGA_PR03_V3_BAD_MESSAGE_HASH",
        m.reviewed_message_bytes_sha256,
        m.caller_intent_message_sha256,
        m.decoded_programs_sha256,
        m.decoded_accounts_sha256,
        m.decoded_amounts_fees_sha256,
        m.semantic_bounds_sha256,
        m.simulation_evidence_sha256,
    )
    if m.reviewed_message_bytes_sha256 != m.caller_intent_message_sha256:
        _add(out, "MEGA_PR03_V3_MESSAGE_IDENTITY_MISMATCH", "signer-reviewed bytes must match authorized intent")
    for code, ok in (
        ("MEGA_PR03_V3_SIGNER_DID_NOT_REPARSE_MESSAGE", m.signer_reparsed_exact_message_bytes),
        ("MEGA_PR03_V3_MESSAGE_SEMANTICS_NOT_REVIEWED", m.programs_accounts_amounts_fees_reviewed),
        ("MEGA_PR03_V3_SIMULATION_IDENTITY_NOT_BOUND", m.simulation_message_identity_matched),
        ("MEGA_PR03_V3_MESSAGE_MUTABLE_AFTER_REVIEW", m.message_mutation_after_review_impossible),
    ):
        if not ok:
            _add(out, code, code.lower())


def _signature(s: SignerSignatureEvidence, out: list[MegaPR03V3Violation]) -> None:
    _hash_fields(
        out,
        "MEGA_PR03_V3_BAD_SIGNATURE_HASH",
        s.isolated_signer_process_sha256,
        s.signer_binary_sha256,
        s.key_authority_generation_sha256,
        s.public_key_sha256,
        s.signature_sha256,
        s.signed_wire_sha256,
        s.verification_transcript_sha256,
    )
    for code, bad in (
        ("MEGA_PR03_V3_EXPORTABLE_PRIVATE_KEY", s.private_key_exportable),
        ("MEGA_PR03_V3_RUNTIME_PRIVATE_KEY_ACCESS", s.private_key_visible_to_runtime),
        ("MEGA_PR03_V3_CALLER_SUPPLIED_SIGNED_WIRE_DIGEST", s.caller_supplied_signed_wire_sha256_present),
        ("MEGA_PR03_V3_CALLER_SUPPLIED_SIGNATURE_DIGEST", s.caller_supplied_signature_sha256_present),
    ):
        if bad:
            _add(out, code, code.lower())
    for code, ok in (
        ("MEGA_PR03_V3_KEY_NOT_LOADED_INSIDE_BOUNDARY", s.key_loaded_inside_signer_boundary),
        ("MEGA_PR03_V3_SIGNATURE_NOT_SIGNER_PRODUCED", s.signature_produced_by_isolated_signer),
        ("MEGA_PR03_V3_SIGNED_WIRE_NOT_SIGNER_BUILT", s.signed_wire_built_by_isolated_signer),
        ("MEGA_PR03_V3_SIGNATURE_NOT_LOCALLY_VERIFIED", s.signature_verified_against_public_key_and_message),
    ):
        if not ok:
            _add(out, code, code.lower())


def _dispatch(d: DispatchCryptographicEvidence, out: list[MegaPR03V3Violation]) -> None:
    _hash_fields(
        out,
        "MEGA_PR03_V3_BAD_DISPATCH_HASH",
        d.evidence_record_sha256,
        d.authorization_intent_sha256,
        d.dispatch_token_sha256,
        d.dispatch_receipt_sha256,
    )
    for code, ok in (
        ("MEGA_PR03_V3_EVIDENCE_AFTER_DISPATCH", d.evidence_persisted_before_dispatch),
        ("MEGA_PR03_V3_DISPATCH_TOKEN_NOT_CONSUMED_ONCE", d.dispatch_token_consumed_once),
        ("MEGA_PR03_V3_REPLAY_OR_DUPLICATE_DISPATCH_ALLOWED", d.replay_or_duplicate_dispatch_rejected),
        ("MEGA_PR03_V3_AUDIT_RECEIPT_MISSING", d.durable_audit_receipt_written),
        ("MEGA_PR03_V3_CRASH_REPLAYS_SIGNATURE", d.crash_recovery_does_not_replay_signature),
    ):
        if not ok:
            _add(out, code, code.lower())


def _hash_fields(out: list[MegaPR03V3Violation], code: str, *values: str) -> None:
    for value in values:
        if not _sha(value):
            _add(out, code, "sha256 evidence must be strict and non-placeholder")


def _sha(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA_RE.fullmatch(value)) and value not in {"0" * 64, "f" * 64}


def _stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(_json(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _json(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _json(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_json(item) for item in value]
    return value


def _add(out: list[MegaPR03V3Violation], code: str, message: str) -> None:
    out.append(MegaPR03V3Violation(code, message))


def _dedupe(blockers: Iterable[MegaPR03V3Violation]) -> Iterable[MegaPR03V3Violation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key not in seen:
            seen.add(key)
            yield blocker
