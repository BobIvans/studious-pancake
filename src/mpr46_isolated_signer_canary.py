"""MPR-46 isolated signer and permit-bound one-transaction canary gate.

This module is deliberately sender-free and signer-free. It models the policy
that must be satisfied before a future physically isolated signer may receive a
single immutable canary permit. It never loads keys, builds transactions, opens
network sockets, submits transactions, or returns signature material.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

SCHEMA_VERSION = "mpr-46.isolated-signer-permit-canary.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=-]{0,127}$")


class MPR46State(str, Enum):
    """Stable MPR-46 gate states."""

    BLOCKED = "BLOCKED"
    CANARY_PAUSED = "CANARY_PAUSED"
    CANARY_ELIGIBLE = "CANARY_ELIGIBLE"
    ONE_TX_PERMIT_ELIGIBLE = "ONE_TX_PERMIT_ELIGIBLE"


@dataclass(frozen=True, slots=True)
class MPR46Violation:
    """One deterministic fail-closed policy blocker."""

    code: str
    message: str
    surface: str


@dataclass(frozen=True, slots=True)
class MPR46Report:
    """Deterministic MPR-46 policy report."""

    schema_version: str
    state: MPR46State
    accepted: bool
    permit_eligible: bool
    one_tx_canary_authorized: bool
    live_enabled: bool
    unrestricted_live_available: bool
    signature_material_returned: bool
    canary_latch_remaining: int
    evidence_digest: str
    blockers: tuple[MPR46Violation, ...]
    required_actions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "accepted": self.accepted,
            "permit_eligible": self.permit_eligible,
            "one_tx_canary_authorized": self.one_tx_canary_authorized,
            "live_enabled": self.live_enabled,
            "unrestricted_live_available": self.unrestricted_live_available,
            "signature_material_returned": self.signature_material_returned,
            "canary_latch_remaining": self.canary_latch_remaining,
            "evidence_digest": self.evidence_digest,
            "blockers": [
                {"code": row.code, "message": row.message, "surface": row.surface}
                for row in self.blockers
            ],
            "required_actions": list(self.required_actions),
        }


_REQUIRED_TRUE: tuple[tuple[str, str], ...] = (
    ("paper_qualified_evidence_complete", "PAPER_QUALIFIED evidence is complete"),
    ("provider_protocol_binaries_attested", "provider/protocol contracts are attested"),
    ("exact_transaction_settlement_authority_operational", "exact transaction and settlement authority is operational"),
    ("deployment_supply_chain_controls_passed", "deployment and supply-chain controls pass"),
    ("backup_restore_runbooks_approved", "backup/restore and incident runbooks are approved"),
    ("human_release_authority_signed", "human release authority signed canary eligibility"),
    ("signer_separate_artifact", "signer is a separate signed artifact"),
    ("signer_no_arbitrary_egress", "signer has no arbitrary egress"),
    ("signer_no_provider_rpc_access", "signer cannot access provider/RPC APIs"),
    ("authenticated_ipc", "IPC authenticates peer identity and replay window"),
    ("external_key_backend", "keys live in an external key backend"),
    ("durable_single_use_permit_store", "permit store is durable and single-use"),
    ("signer_independent_policy_checks", "signer independently checks policy"),
    ("signed_receipts", "approve/deny/consume events produce signed receipts"),
    ("signer_side_kill_switch", "signer-side kill switch is independent"),
    ("monotonic_anti_rollback_state", "signer rejects stale generations"),
    ("permit_binds_final_simulation", "permit binds the final simulated message"),
    ("permit_binds_reservation", "permit binds the durable reservation"),
    ("sender_submits_only_signed_bytes", "sender can submit only signed bytes"),
    ("finalized_reconciliation_required", "finalized reconciliation is required"),
    ("abnormality_auto_pauses_canary", "abnormality automatically pauses canary"),
)

_REQUIRED_FALSE: tuple[tuple[str, str], ...] = (
    ("unrestricted_live_available", "unrestricted live capability must not exist"),
    ("live_by_env_flag", "environment variables alone must not enable live"),
    ("jito_authoritative_for_settlement", "Jito must not be settlement authority"),
    ("signer_can_build_transactions", "signer must not build transactions"),
    ("signer_can_submit_transactions", "signer must not submit transactions"),
    ("sender_can_mutate_message", "sender must not mutate signed message"),
    ("signature_material_returned", "gate must never return signature material"),
)

_BUDGET_CEILINGS: tuple[str, ...] = (
    "max_borrow_atomic",
    "max_total_fee_atomic",
    "max_jito_tip_atomic",
)

_GENERATIONS: tuple[str, ...] = (
    "release_generation",
    "runtime_generation",
    "config_generation",
    "permit_store_generation",
)


def _is_int(value: Any, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _is_safe_id(value: Any) -> bool:
    return isinstance(value, str) and _SAFE_ID_RE.fullmatch(value) is not None


def _digest_json(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _message_digest(request: Mapping[str, Any]) -> str | None:
    raw_hex = request.get("serialized_message_hex")
    if not isinstance(raw_hex, str):
        return None
    try:
        raw = bytes.fromhex(raw_hex)
    except ValueError:
        return None
    if not raw:
        return None
    return hashlib.sha256(raw).hexdigest()


def _block(code: str, message: str, surface: str) -> MPR46Violation:
    return MPR46Violation(code=code, message=message, surface=surface)


def _validate_evidence(evidence: Mapping[str, Any]) -> list[MPR46Violation]:
    blockers: list[MPR46Violation] = []

    if evidence.get("schema_version") != SCHEMA_VERSION:
        blockers.append(_block("SCHEMA_VERSION_MISMATCH", f"expected {SCHEMA_VERSION}", "schema_version"))

    for key, message in _REQUIRED_TRUE:
        if evidence.get(key) is not True:
            blockers.append(_block(f"REQUIRED_{key.upper()}", message, key))

    for key, message in _REQUIRED_FALSE:
        if evidence.get(key) is True:
            blockers.append(_block(f"DANGEROUS_{key.upper()}", message, key))

    if evidence.get("canary_state") not in {"CANARY_PAUSED", "CANARY_ELIGIBLE"}:
        blockers.append(_block("INVALID_CANARY_STATE", "canary state must be paused or eligible", "canary_state"))

    if evidence.get("max_transaction_count") != 1:
        blockers.append(_block("CANARY_LATCH_NOT_SINGLE_TX", "canary must allow exactly one transaction", "max_transaction_count"))
    if evidence.get("max_submission_count") != 1:
        blockers.append(_block("SUBMISSION_LATCH_NOT_SINGLE_SEND", "canary must allow exactly one submission", "max_submission_count"))

    for key in _BUDGET_CEILINGS:
        if not _is_int(evidence.get(key), minimum=0):
            blockers.append(_block(f"INVALID_{key.upper()}", "budget ceilings must be nonnegative integers", key))

    for key in _GENERATIONS:
        if not _is_int(evidence.get(key), minimum=1):
            blockers.append(_block(f"INVALID_{key.upper()}", "generations must be positive integers", key))

    if _is_int(evidence.get("permit_store_generation"), minimum=1) and _is_int(evidence.get("release_generation"), minimum=1):
        if evidence["permit_store_generation"] < evidence["release_generation"]:
            blockers.append(_block("PERMIT_STORE_ROLLBACK", "permit store generation cannot lag release generation", "permit_store_generation"))

    if not _is_safe_id(evidence.get("operator_approval_ref")):
        blockers.append(_block("INVALID_OPERATOR_APPROVAL_REF", "operator approval ref must be present and bounded", "operator_approval_ref"))

    sim_digest = evidence.get("final_simulation_message_sha256")
    reservation_digest = evidence.get("reservation_message_sha256")
    if not _is_sha256(sim_digest):
        blockers.append(_block("INVALID_FINAL_SIMULATION_DIGEST", "final simulation digest must be sha256", "final_simulation_message_sha256"))
    if not _is_sha256(reservation_digest):
        blockers.append(_block("INVALID_RESERVATION_DIGEST", "reservation digest must be sha256", "reservation_message_sha256"))
    if _is_sha256(sim_digest) and _is_sha256(reservation_digest) and sim_digest != reservation_digest:
        blockers.append(_block("SIMULATION_RESERVATION_DRIFT", "simulation and reservation must bind same message", "reservation_message_sha256"))

    return blockers


def _validate_request(evidence: Mapping[str, Any], request: Mapping[str, Any]) -> list[MPR46Violation]:
    blockers: list[MPR46Violation] = []

    if evidence.get("canary_state") != "CANARY_ELIGIBLE":
        blockers.append(_block("CANARY_NOT_ELIGIBLE", "request denied unless canary is eligible", "canary_state"))
    if not _is_safe_id(request.get("permit_id")):
        blockers.append(_block("INVALID_PERMIT_ID", "permit id must be bounded", "request.permit_id"))
    if request.get("permit_consumed") is True:
        blockers.append(_block("PERMIT_ALREADY_CONSUMED", "single-use permit already consumed", "request.permit_consumed"))

    decoded_digest = _message_digest(request)
    if decoded_digest is None:
        blockers.append(_block("INVALID_SERIALIZED_MESSAGE", "serialized message must be nonempty hex", "request.serialized_message_hex"))

    request_digest = request.get("message_digest_sha256")
    if not _is_sha256(request_digest):
        blockers.append(_block("INVALID_REQUEST_DIGEST", "request digest must be sha256", "request.message_digest_sha256"))
    elif decoded_digest is not None and request_digest != decoded_digest:
        blockers.append(_block("SERIALIZED_MESSAGE_DIGEST_MISMATCH", "digest must equal serialized bytes", "request.message_digest_sha256"))

    for key in ("final_simulation_message_sha256", "reservation_message_sha256"):
        if request.get(key) != evidence.get(key):
            blockers.append(_block(f"REQUEST_{key.upper()}_MISMATCH", "request digest must match evidence", f"request.{key}"))
    if decoded_digest is not None and decoded_digest != evidence.get("final_simulation_message_sha256"):
        blockers.append(_block("REQUEST_NOT_FINAL_SIMULATED_MESSAGE", "request must be exact final simulated message", "request.serialized_message_hex"))

    for key in ("release_generation", "runtime_generation", "config_generation"):
        if request.get(key) != evidence.get(key):
            blockers.append(_block(f"REQUEST_{key.upper()}_MISMATCH", "request generation must match evidence", f"request.{key}"))

    if request.get("operator_approval_ref") != evidence.get("operator_approval_ref"):
        blockers.append(_block("REQUEST_OPERATOR_APPROVAL_MISMATCH", "operator approval must match", "request.operator_approval_ref"))

    for request_key, ceiling_key in (
        ("borrow_atomic", "max_borrow_atomic"),
        ("total_fee_atomic", "max_total_fee_atomic"),
        ("jito_tip_atomic", "max_jito_tip_atomic"),
    ):
        value = request.get(request_key)
        if not _is_int(value, minimum=0):
            blockers.append(_block(f"INVALID_REQUEST_{request_key.upper()}", "request budget must be integer", f"request.{request_key}"))
        elif _is_int(evidence.get(ceiling_key), minimum=0) and value > evidence[ceiling_key]:
            blockers.append(_block(f"REQUEST_{request_key.upper()}_EXCEEDS_CEILING", "request exceeds hard budget", f"request.{request_key}"))

    if request.get("transaction_count") != 1:
        blockers.append(_block("REQUEST_TRANSACTION_COUNT_NOT_ONE", "request must authorize one transaction", "request.transaction_count"))
    if request.get("submission_count") != 1:
        blockers.append(_block("REQUEST_SUBMISSION_COUNT_NOT_ONE", "request must authorize one submission", "request.submission_count"))

    return blockers


def evaluate_mpr46_policy(evidence: Mapping[str, Any], *, request: Mapping[str, Any] | None = None) -> MPR46Report:
    """Evaluate MPR-46 evidence and an optional future sign request.

    A true ``permit_eligible`` result means only that the offline policy layer
    would allow handing the exact bytes to a separate signer implementation. It
    does not sign and does not enable general live execution.
    """

    blockers = _validate_evidence(evidence)
    if request is not None:
        blockers.extend(_validate_request(evidence, request))

    accepted = not blockers
    permit_eligible = accepted and request is not None
    one_tx_authorized = permit_eligible and evidence.get("canary_state") == "CANARY_ELIGIBLE"

    if blockers:
        state = MPR46State.BLOCKED
    elif permit_eligible:
        state = MPR46State.ONE_TX_PERMIT_ELIGIBLE
    elif evidence.get("canary_state") == "CANARY_ELIGIBLE":
        state = MPR46State.CANARY_ELIGIBLE
    else:
        state = MPR46State.CANARY_PAUSED

    return MPR46Report(
        schema_version=SCHEMA_VERSION,
        state=state,
        accepted=accepted,
        permit_eligible=permit_eligible,
        one_tx_canary_authorized=one_tx_authorized,
        live_enabled=False,
        unrestricted_live_available=evidence.get("unrestricted_live_available") is True,
        signature_material_returned=False,
        canary_latch_remaining=1 if one_tx_authorized else 0,
        evidence_digest=_digest_json(evidence),
        blockers=tuple(blockers),
        required_actions=tuple(sorted({row.message for row in blockers})),
    )


def load_json_policy(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("MPR-46 policy must be a JSON object")
    return payload


def default_policy_path(root: str | Path = ".") -> Path:
    return Path(root) / "src" / "resources" / "mpr46_permit_canary_policy.json"


def evaluate_default_policy(root: str | Path = ".") -> MPR46Report:
    return evaluate_mpr46_policy(load_json_policy(default_policy_path(root)))
