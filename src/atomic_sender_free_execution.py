"""Sender-free PR-222 atomic flash-loan execution evidence gate.

This module is intentionally offline: it never imports Solana/Jupiter SDKs,
never signs, never submits, never reads private keys and never opens sockets.
It validates the evidence contract required before PR-223 may add an isolated
signer boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "pr222.atomic-sender-free-execution.v1"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_TEXT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}$")
BORROW = "marginfi.borrow"
REPAY = "marginfi.repay"
LEG_A = "jupiter.leg_a"
LEG_B = "jupiter.leg_b"
SENSITIVE_ROLES = (BORROW, LEG_A, LEG_B, REPAY)
ALLOWED_ROLES = frozenset(
    (*SENSITIVE_ROLES, "ata.create", "ata.close", "wsol.wrap", "wsol.unwrap")
)
REQUIRED_FINDINGS = frozenset(
    """
    F-008 F-014 F-018 F-049 F-050 F-059 F-062 F-065 F-066 F-067 F-068 F-069
    F-071 F-072 F-073 F-114 F-115 F-116 F-117 F-118 F-119 F-120 F-121 F-122
    F-123 F-124 F-234 F-235 F-236 F-237 F-238 F-239 F-240 F-241 F-242 F-243
    F-244 F-245 F-246 F-247 F-248 F-312 F-328 F-329 F-330 F-361 F-362 F-363
    F-365 F-366 F-387 F-388 F-389 F-390 F-391 F-392 F-393 F-394 F-395 F-396
    F-397 F-398 F-399 F-403 F-405 F-406
    """.split()
)


class PR222Decision(str, Enum):
    READY_FOR_PR223_SIGNER_REVIEW = "ready_for_pr223_signer_review"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class PR222Violation:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class PR222Report:
    schema_version: str
    decision: PR222Decision
    blockers: tuple[PR222Violation, ...]
    evidence_hash: str
    signer_allowed: bool
    sender_allowed: bool
    live_execution_allowed: bool
    ready_for_pr223_signer_review: bool


def evaluate_atomic_sender_free_evidence(evidence: Mapping[str, Any]) -> PR222Report:
    """Return a fail-closed PR-222 report for one immutable evidence bundle."""

    blockers: list[PR222Violation] = []
    plan = _mapping(evidence.get("plan"))
    message = _mapping(evidence.get("compiled_message"))
    simulation = _mapping(evidence.get("simulation"))
    economics = _mapping(evidence.get("economics"))
    qualification = _mapping(evidence.get("qualification"))
    instructions = tuple(_mapping(item) for item in evidence.get("instructions", ()))

    _forbid_runtime_surfaces(evidence, qualification, blockers)
    _validate_plan(plan, blockers)
    _validate_message(plan, message, blockers)
    _validate_instructions(plan, instructions, blockers)
    _validate_simulation(message, simulation, blockers)
    _validate_economics(plan, instructions, simulation, economics, blockers)
    _validate_qualification(qualification, blockers)
    _validate_findings(evidence.get("findings_covered", ()), blockers)

    unique = tuple(_dedupe(blockers))
    decision = (
        PR222Decision.BLOCKED
        if unique
        else PR222Decision.READY_FOR_PR223_SIGNER_REVIEW
    )
    return PR222Report(
        schema_version=SCHEMA_VERSION,
        decision=decision,
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        signer_allowed=False,
        sender_allowed=False,
        live_execution_allowed=False,
        ready_for_pr223_signer_review=not unique,
    )


def _forbid_runtime_surfaces(
    evidence: Mapping[str, Any],
    qualification: Mapping[str, Any],
    blockers: list[PR222Violation],
) -> None:
    for key in ("live_execution_requested", "signer_requested", "sender_requested"):
        _require(not evidence.get(key), blockers, "PR222_FORBIDDEN_REQUEST", key)
    for key in (
        "sender_namespace_reachable",
        "signer_namespace_reachable",
        "private_key_reachable",
        "network_submission_reachable",
    ):
        _require(not qualification.get(key), blockers, "PR222_FORBIDDEN_SURFACE", key)


def _validate_plan(plan: Mapping[str, Any], blockers: list[PR222Violation]) -> None:
    for key in ("release_id", "plan_id", "wallet_pubkey", "durable_reservation_id"):
        _require(_safe(plan.get(key)), blockers, "PR222_BAD_PLAN_ID", key)
    for key in (
        "cluster_genesis_hash",
        "protocol_registry_hash",
        "provider_generation_hash",
        "build_artifact_hash",
    ):
        _require(_hash(plan.get(key)), blockers, "PR222_BAD_PLAN_HASH", key)
    _require(
        _positive(plan.get("principal_lamports")),
        blockers,
        "PR222_BAD_PLAN_AMOUNT",
        "principal",
    )
    _require(_uint(plan.get("flash_fee_lamports")), blockers, "PR222_BAD_PLAN_AMOUNT", "fee")
    _require(
        _uint(plan.get("minimum_profit_lamports")),
        blockers,
        "PR222_BAD_PLAN_AMOUNT",
        "profit",
    )
    slippage = plan.get("max_slippage_bps")
    _require(
        isinstance(slippage, int) and 0 <= slippage <= 1000,
        blockers,
        "PR222_BAD_SLIPPAGE",
        "max_slippage_bps",
    )


def _validate_message(
    plan: Mapping[str, Any],
    message: Mapping[str, Any],
    blockers: list[PR222Violation],
) -> None:
    _require(message.get("plan_id") == plan.get("plan_id"), blockers, "PR222_MESSAGE_BINDING", "plan_id")
    for key in ("message_hash", "message_bytes_hash", "account_meta_hash", "alt_snapshot_hash"):
        _require(_hash(message.get(key)), blockers, "PR222_BAD_MESSAGE_HASH", key)
    _require(_safe(message.get("recent_blockhash")), blockers, "PR222_BAD_BLOCKHASH", "recent_blockhash")
    current = message.get("current_block_height")
    last_valid = message.get("last_valid_block_height")
    margin = message.get("safety_margin_blocks")
    _require(
        _uint(current) and _uint(last_valid) and _uint(margin),
        blockers,
        "PR222_BAD_BLOCKHEIGHT",
        "height",
    )
    _require(
        current + margin < last_valid,
        blockers,
        "PR222_BLOCKHASH_STALE",
        "last_valid_block_height",
    )
    _require(
        message.get("observed_context_slot", -1) >= message.get("min_context_slot", 0),
        blockers,
        "PR222_CONTEXT_SLOT_STALE",
        "min_context_slot",
    )
    wire_size = message.get("unsigned_transaction_bytes", 0) + 1 + 64 * message.get("required_signature_count", 0)
    _require(
        65 < wire_size <= message.get("max_wire_bytes", 1232),
        blockers,
        "PR222_WIRE_SIZE",
        "wire_size",
    )


def _validate_instructions(
    plan: Mapping[str, Any],
    instructions: tuple[Mapping[str, Any], ...],
    blockers: list[PR222Violation],
) -> None:
    roles = tuple(item.get("role") for item in instructions)
    expected = tuple(item.get("role") for item in sorted(instructions, key=lambda item: item.get("index", -1)))
    _require(roles == expected, blockers, "PR222_INSTRUCTION_INDEX_GAP", "index")
    _require(bool(roles), blockers, "PR222_NO_INSTRUCTIONS", "instructions")
    _require(
        roles[:1] == (BORROW,) and roles[-1:] == (REPAY,),
        blockers,
        "PR222_BAD_FLASH_BRACKET",
        "borrow_repay",
    )
    _require(
        tuple(role for role in roles if role in (LEG_A, LEG_B)) == (LEG_A, LEG_B),
        blockers,
        "PR222_BAD_SWAP_ORDER",
        "jupiter",
    )
    for role in SENSITIVE_ROLES:
        _require(roles.count(role) == 1, blockers, "PR222_DUPLICATE_OR_MISSING_ROLE", role)
    for item in instructions:
        _require(item.get("role") in ALLOWED_ROLES, blockers, "PR222_UNKNOWN_INSTRUCTION", str(item.get("role")))
        for key in ("program_id", "instruction_hash", "account_roles_hash", "decoded_semantics_hash"):
            validator = _safe if key == "program_id" else _hash
            _require(validator(item.get(key)), blockers, "PR222_BAD_INSTRUCTION_EVIDENCE", key)
        for key in (
            "input_lamports",
            "output_lamports",
            "principal_lamports",
            "flash_fee_lamports",
            "repayment_lamports",
        ):
            _require(_uint(item.get(key, 0)), blockers, "PR222_BAD_INSTRUCTION_AMOUNT", key)
    borrow = _find(instructions, BORROW)
    repay = _find(instructions, REPAY)
    expected_repay = plan.get("principal_lamports", 0) + plan.get("flash_fee_lamports", 0)
    _require(
        borrow.get("principal_lamports") == plan.get("principal_lamports"),
        blockers,
        "PR222_BORROW_AMOUNT",
        "principal",
    )
    _require(
        repay.get("repayment_lamports") == expected_repay,
        blockers,
        "PR222_REPAY_AMOUNT",
        "repayment",
    )


def _validate_simulation(
    message: Mapping[str, Any],
    simulation: Mapping[str, Any],
    blockers: list[PR222Violation],
) -> None:
    for key in (
        "message_hash",
        "request_hash",
        "response_hash",
        "pre_accounts_hash",
        "post_accounts_hash",
        "logs_hash",
    ):
        _require(_hash(simulation.get(key)), blockers, "PR222_BAD_SIMULATION_HASH", key)
    _require(
        simulation.get("message_hash") == message.get("message_hash"),
        blockers,
        "PR222_SIMULATION_BINDING",
        "message_hash",
    )
    _require(simulation.get("success") is True, blockers, "PR222_SIMULATION_FAILED", "success")
    _require(simulation.get("error_code") is None, blockers, "PR222_SIMULATION_ERROR_PRESENT", "error_code")
    _require(
        simulation.get("local_signature_verification_passed") is True,
        blockers,
        "PR222_LOCAL_SIGNATURE_CHECK",
        "signature",
    )
    _require(_positive(simulation.get("units_consumed")), blockers, "PR222_BAD_SIMULATION_COUNTER", "units")
    _require(
        _positive(simulation.get("total_transaction_fee_lamports")),
        blockers,
        "PR222_BAD_SIMULATION_COUNTER",
        "fee",
    )


def _validate_economics(
    plan: Mapping[str, Any],
    instructions: tuple[Mapping[str, Any], ...],
    simulation: Mapping[str, Any],
    economics: Mapping[str, Any],
    blockers: list[PR222Violation],
) -> None:
    required_costs = (
        "total_transaction_fee_lamports",
        "failed_landing_fee_lamports",
        "rent_create_lamports",
        "priority_fee_lamports",
        "jito_tip_lamports",
        "token_transfer_fee_lamports",
        "contingency_lamports",
    )
    for key in (*required_costs, "minimum_profit_lamports", "rent_refund_lamports"):
        _require(_uint(economics.get(key)), blockers, "PR222_BAD_ECONOMIC_AMOUNT", key)
    expected_repay = plan.get("principal_lamports", 0) + plan.get("flash_fee_lamports", 0)
    _require(economics.get("repayment_lamports") == expected_repay, blockers, "PR222_ECONOMIC_REPAYMENT", "repayment")
    _require(
        economics.get("total_transaction_fee_lamports") == simulation.get("total_transaction_fee_lamports"),
        blockers,
        "PR222_FEE_NOT_SIMULATION_BOUND",
        "fee",
    )
    _require(
        economics.get("failed_landing_fee_lamports", 0) > 0,
        blockers,
        "PR222_FAILED_LANDING_FEE",
        "failed_landing_fee",
    )
    leg_b = _find(instructions, LEG_B)
    guaranteed_out = economics.get("guaranteed_leg_b_output_lamports")
    _require(
        guaranteed_out == leg_b.get("output_lamports"),
        blockers,
        "PR222_GUARANTEED_OUTPUT",
        "leg_b",
    )
    net = guaranteed_out - economics.get("repayment_lamports", 0) + economics.get("rent_refund_lamports", 0)
    for cost in required_costs:
        net -= economics.get(cost, 0)
    _require(
        economics.get("minimum_profit_lamports") == plan.get("minimum_profit_lamports"),
        blockers,
        "PR222_MIN_PROFIT_BINDING",
        "minimum_profit",
    )
    _require(
        net >= plan.get("minimum_profit_lamports", 0),
        blockers,
        "PR222_CONSERVATIVE_PROFIT",
        "net",
    )


def _validate_qualification(qualification: Mapping[str, Any], blockers: list[PR222Violation]) -> None:
    for key in ("installed_artifact_hash", "composition_root_hash", "durable_shadow_trace_hash", "replay_bundle_hash"):
        _require(_hash(qualification.get(key)), blockers, "PR222_BAD_QUALIFICATION_HASH", key)
    _require(
        qualification.get("ended_ns", 0) > qualification.get("started_ns", 0),
        blockers,
        "PR222_BAD_QUALIFICATION_WINDOW",
        "window",
    )
    for key in ("non_synthetic_cycle_count", "restart_drill_count", "provider_degradation_drill_count"):
        _require(_positive(qualification.get(key)), blockers, "PR222_QUALIFICATION_COUNT", key)
    for key in (
        "deterministic_replay_passed",
        "durable_trace_materialized",
        "compiled_from_installed_artifact",
        "exact_simulation_replayed",
        "economics_reconciled",
    ):
        _require(qualification.get(key) is True, blockers, "PR222_QUALIFICATION_FLAG", key)


def _validate_findings(value: Any, blockers: list[PR222Violation]) -> None:
    findings = tuple(value or ())
    _require(len(findings) == len(set(findings)), blockers, "PR222_DUPLICATE_FINDING", "findings")
    missing = sorted(REQUIRED_FINDINGS.difference(findings))
    _require(not missing, blockers, "PR222_FINDINGS_INCOMPLETE", ",".join(missing))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _find(items: Iterable[Mapping[str, Any]], role: str) -> Mapping[str, Any]:
    return next((item for item in items if item.get("role") == role), {})


def _require(ok: bool, blockers: list[PR222Violation], code: str, detail: str) -> None:
    if not ok:
        blockers.append(PR222Violation(code, detail))


def _dedupe(blockers: Iterable[PR222Violation]) -> Iterable[PR222Violation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker.code, blocker.detail)
        if key not in seen:
            seen.add(key)
            yield blocker


def _hash(value: Any) -> bool:
    return isinstance(value, str) and _HASH_RE.fullmatch(value) is not None


def _safe(value: Any) -> bool:
    return isinstance(value, str) and _SAFE_TEXT_RE.fullmatch(value) is not None


def _uint(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _positive(value: Any) -> bool:
    return _uint(value) and value > 0


def _stable_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()
