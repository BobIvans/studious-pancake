"""PR-209 exact atomic message semantics and economics gate.

Side-effect free acceptance boundary for Pass 6 PR-209. It never connects to
RPC, never signs, never submits and never enables live trading.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "pr209.exact-atomic-message-semantics-gate.v1"

REQUIRED_SEQUENCE: tuple[str, ...] = (
    "marginfi.borrow",
    "jupiter.leg_a",
    "jupiter.leg_b",
    "marginfi.repay",
)

HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


class PR209GateState(str, Enum):
    READY_FOR_SENDER_FREE_ATOMIC_PROOF = "ready_for_sender_free_atomic_proof"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class AtomicInstruction:
    role: str
    program_id: str
    instruction_hash: str
    side_effecting: bool = True


@dataclass(frozen=True)
class DecodedSemanticEffect:
    role: str
    instruction_hash: str
    effect_hash: str
    principal_lamports: int = 0
    flash_fee_lamports: int = 0
    repayment_lamports: int = 0
    input_lamports: int = 0
    output_lamports: int = 0
    rent_lamports: int = 0
    tip_lamports: int = 0
    transfer_fee_lamports: int = 0


@dataclass(frozen=True)
class BlockhashFreshness:
    current_block_height: int
    last_valid_block_height: int
    safety_margin_blocks: int
    min_context_slot: int
    observed_context_slot: int


@dataclass(frozen=True)
class SimulationBinding:
    success: bool
    error_code: str | None
    sig_verify_enabled: bool
    exact_message_hash: str
    exact_signed_payload_hash: str
    raw_account_state_hash: str
    account_delta_hash: str
    logs_hash: str
    units_consumed: int
    total_transaction_fee_lamports: int


@dataclass(frozen=True)
class TimelineEvidence:
    provider_snapshot_unix_ns: int
    quote_unix_ns: int
    blockhash_unix_ns: int
    compile_unix_ns: int
    simulation_unix_ns: int
    max_total_age_ns: int


@dataclass(frozen=True)
class IntegerEconomics:
    principal_lamports: int
    flash_fee_lamports: int
    repayment_lamports: int
    expected_output_lamports: int
    total_transaction_fee_lamports: int
    rent_lamports: int
    tip_lamports: int
    transfer_fee_lamports: int
    contingency_lamports: int
    minimum_profit_lamports: int


@dataclass(frozen=True)
class FeeAccounting:
    projected_total_transaction_fee_lamports: int
    failed_landing_fee_lamports: int | None = None


@dataclass(frozen=True)
class PR209AtomicEvidence:
    release_artifact_hash: str
    rooted_provider_generation_hash: str
    protocol_registry_hash: str
    instructions: tuple[AtomicInstruction, ...]
    semantic_effects: tuple[DecodedSemanticEffect, ...]
    blockhash: BlockhashFreshness
    simulation: SimulationBinding
    timeline: TimelineEvidence
    economics: IntegerEconomics
    fee_accounting: FeeAccounting
    live_execution_requested: bool = False
    signer_requested: bool = False
    sender_requested: bool = False


@dataclass(frozen=True)
class PR209Violation:
    code: str
    message: str


@dataclass(frozen=True)
class PR209AtomicReport:
    schema_version: str
    state: PR209GateState
    blockers: tuple[PR209Violation, ...]
    evidence_hash: str
    live_execution_allowed: bool
    signer_allowed: bool
    sender_allowed: bool
    required_sequence: tuple[str, ...]


def evaluate_pr209_atomic_evidence(evidence: PR209AtomicEvidence) -> PR209AtomicReport:
    blockers: list[PR209Violation] = []
    _validate_release_hashes(evidence, blockers)
    _validate_no_live_boundary(evidence, blockers)
    _validate_blockhash(evidence.blockhash, blockers)
    _validate_instruction_sequence(evidence.instructions, blockers)
    effect_by_hash = _validate_semantic_effects(evidence.instructions, evidence.semantic_effects, blockers)
    _validate_simulation(evidence.simulation, blockers)
    _validate_timeline(evidence.timeline, blockers)
    _validate_economics(evidence.economics, evidence.semantic_effects, blockers)
    _validate_fee_accounting(evidence, blockers)

    for instruction in evidence.instructions:
        if instruction.instruction_hash not in effect_by_hash:
            _add(blockers, "PR209_EFFECT_MISSING_FOR_INSTRUCTION", f"instruction {instruction.role} has no decoded effect")

    unique = tuple(_dedupe(blockers))
    state = PR209GateState.BLOCKED if unique else PR209GateState.READY_FOR_SENDER_FREE_ATOMIC_PROOF
    return PR209AtomicReport(
        schema_version=SCHEMA_VERSION,
        state=state,
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        live_execution_allowed=False,
        signer_allowed=False,
        sender_allowed=False,
        required_sequence=REQUIRED_SEQUENCE,
    )


def _validate_release_hashes(evidence: PR209AtomicEvidence, blockers: list[PR209Violation]) -> None:
    for field_name, value in (
        ("release_artifact_hash", evidence.release_artifact_hash),
        ("rooted_provider_generation_hash", evidence.rooted_provider_generation_hash),
        ("protocol_registry_hash", evidence.protocol_registry_hash),
    ):
        if not _is_strict_sha256(value):
            _add(blockers, "PR209_BAD_HASH", f"{field_name} is not a strict content hash")


def _validate_no_live_boundary(evidence: PR209AtomicEvidence, blockers: list[PR209Violation]) -> None:
    if evidence.live_execution_requested:
        _add(blockers, "PR209_LIVE_REQUESTED", "PR-209 gate cannot enable live execution")
    if evidence.signer_requested:
        _add(blockers, "PR209_SIGNER_REQUESTED", "PR-209 gate cannot enable signing")
    if evidence.sender_requested:
        _add(blockers, "PR209_SENDER_REQUESTED", "PR-209 gate cannot enable sender submission")


def _validate_blockhash(blockhash: BlockhashFreshness, blockers: list[PR209Violation]) -> None:
    for name, value in asdict(blockhash).items():
        if not _is_nonnegative_int(value):
            _add(blockers, "PR209_BAD_BLOCKHASH_FIELD", f"{name} must be a non-negative integer")
    if blockhash.observed_context_slot < blockhash.min_context_slot:
        _add(blockers, "PR209_CONTEXT_BEFORE_MIN_CONTEXT_SLOT", "observed context slot is below requested minContextSlot")
    if blockhash.current_block_height + blockhash.safety_margin_blocks >= blockhash.last_valid_block_height:
        _add(blockers, "PR209_BLOCKHASH_EXPIRED_OR_TOO_CLOSE", "current block height plus safety margin reaches lastValidBlockHeight")


def _validate_instruction_sequence(instructions: Sequence[AtomicInstruction], blockers: list[PR209Violation]) -> None:
    roles = tuple(instruction.role for instruction in instructions)
    if roles != REQUIRED_SEQUENCE:
        _add(blockers, "PR209_INSTRUCTION_SEQUENCE_NOT_EXACT", f"roles must be exactly {REQUIRED_SEQUENCE!r}, got {roles!r}")
    seen_roles: set[str] = set()
    for instruction in instructions:
        if instruction.role in seen_roles:
            _add(blockers, "PR209_DUPLICATE_INSTRUCTION_ROLE", f"duplicate instruction role {instruction.role}")
        seen_roles.add(instruction.role)
        if instruction.role not in REQUIRED_SEQUENCE:
            _add(blockers, "PR209_UNKNOWN_INSTRUCTION_ROLE", f"unknown instruction role {instruction.role}")
        if not instruction.program_id:
            _add(blockers, "PR209_MISSING_PROGRAM_ID", f"{instruction.role} missing program id")
        if not _is_strict_sha256(instruction.instruction_hash):
            _add(blockers, "PR209_BAD_INSTRUCTION_HASH", f"{instruction.role} instruction hash is not strict sha256")


def _validate_semantic_effects(
    instructions: Sequence[AtomicInstruction],
    effects: Sequence[DecodedSemanticEffect],
    blockers: list[PR209Violation],
) -> Mapping[str, DecodedSemanticEffect]:
    effects_by_instruction_hash: dict[str, DecodedSemanticEffect] = {}
    instruction_hashes = {instruction.instruction_hash for instruction in instructions}
    if len(effects) != len(instructions):
        _add(blockers, "PR209_EFFECT_COUNT_MISMATCH", "decoded semantic effects must be one-to-one with top-level instructions")
    for effect in effects:
        if not _is_strict_sha256(effect.instruction_hash):
            _add(blockers, "PR209_BAD_EFFECT_INSTRUCTION_HASH", "effect instruction hash is invalid")
            continue
        if not _is_strict_sha256(effect.effect_hash):
            _add(blockers, "PR209_BAD_EFFECT_HASH", "effect hash is invalid")
        if effect.instruction_hash in effects_by_instruction_hash:
            _add(blockers, "PR209_DUPLICATE_EFFECT_FOR_INSTRUCTION", f"duplicate semantic effect for instruction hash {effect.instruction_hash}")
        effects_by_instruction_hash[effect.instruction_hash] = effect
        if effect.instruction_hash not in instruction_hashes:
            _add(blockers, "PR209_EFFECT_FOR_UNKNOWN_INSTRUCTION", f"semantic effect {effect.role} does not map to a compiled instruction")
        for field_name, value in _numeric_effect_fields(effect).items():
            if not _is_nonnegative_int(value):
                _add(blockers, "PR209_BAD_EFFECT_AMOUNT", f"{field_name} must be non-negative integer")
    role_by_hash = {instruction.instruction_hash: instruction.role for instruction in instructions}
    for instruction_hash, effect in effects_by_instruction_hash.items():
        expected_role = role_by_hash.get(instruction_hash)
        if expected_role is not None and effect.role != expected_role:
            _add(blockers, "PR209_EFFECT_ROLE_MISMATCH", f"effect role {effect.role} does not match instruction role {expected_role}")
    return effects_by_instruction_hash


def _validate_simulation(simulation: SimulationBinding, blockers: list[PR209Violation]) -> None:
    for field_name, value in (
        ("exact_message_hash", simulation.exact_message_hash),
        ("exact_signed_payload_hash", simulation.exact_signed_payload_hash),
        ("raw_account_state_hash", simulation.raw_account_state_hash),
        ("account_delta_hash", simulation.account_delta_hash),
        ("logs_hash", simulation.logs_hash),
    ):
        if not _is_strict_sha256(value):
            _add(blockers, "PR209_BAD_SIMULATION_HASH", f"{field_name} is not strict sha256")
    if simulation.success != (simulation.error_code is None):
        _add(blockers, "PR209_SIMULATION_SUCCESS_ERROR_CONFLICT", "simulation success must be true iff error_code is None")
    if not simulation.sig_verify_enabled:
        _add(blockers, "PR209_SIMULATION_SIGVERIFY_REQUIRED", "simulation proof must explicitly bind sigVerify=true or local signature verification")
    if not _is_nonnegative_int(simulation.units_consumed):
        _add(blockers, "PR209_BAD_COMPUTE_UNITS", "units_consumed must be non-negative integer")
    if not _is_nonnegative_int(simulation.total_transaction_fee_lamports):
        _add(blockers, "PR209_BAD_SIMULATION_FEE", "simulation total fee must be non-negative integer")


def _validate_timeline(timeline: TimelineEvidence, blockers: list[PR209Violation]) -> None:
    ordered = (
        ("provider_snapshot_unix_ns", timeline.provider_snapshot_unix_ns),
        ("quote_unix_ns", timeline.quote_unix_ns),
        ("blockhash_unix_ns", timeline.blockhash_unix_ns),
        ("compile_unix_ns", timeline.compile_unix_ns),
        ("simulation_unix_ns", timeline.simulation_unix_ns),
    )
    for name, value in ordered + (("max_total_age_ns", timeline.max_total_age_ns),):
        if not _is_nonnegative_int(value):
            _add(blockers, "PR209_BAD_TIMELINE_FIELD", f"{name} must be non-negative integer")
    values = tuple(value for _, value in ordered)
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        _add(blockers, "PR209_TIMELINE_NOT_CAUSAL", "timeline must be strictly ordered provider<=quote<=blockhash<=compile<=simulation")
    total_age = timeline.simulation_unix_ns - timeline.provider_snapshot_unix_ns
    if total_age > timeline.max_total_age_ns:
        _add(blockers, "PR209_TIMELINE_TOO_OLD", "provider/blockhash/compile/simulation evidence exceeds bounded age")


def _validate_economics(economics: IntegerEconomics, effects: Sequence[DecodedSemanticEffect], blockers: list[PR209Violation]) -> None:
    for field_name, value in asdict(economics).items():
        if not _is_nonnegative_int(value):
            _add(blockers, "PR209_BAD_ECONOMIC_AMOUNT", f"{field_name} must be non-negative integer")
    if economics.repayment_lamports != economics.principal_lamports + economics.flash_fee_lamports:
        _add(blockers, "PR209_REPAYMENT_FORMULA_MISMATCH", "repayment must equal principal + flash fee using protocol integer rules")
    borrow = _single_role_effect(effects, "marginfi.borrow")
    repay = _single_role_effect(effects, "marginfi.repay")
    if borrow and borrow.principal_lamports != economics.principal_lamports:
        _add(blockers, "PR209_PRINCIPAL_EFFECT_MISMATCH", "decoded borrow principal does not match economics principal")
    if repay:
        if repay.repayment_lamports != economics.repayment_lamports:
            _add(blockers, "PR209_REPAYMENT_EFFECT_MISMATCH", "decoded repayment effect does not match economics repayment")
        if repay.flash_fee_lamports != economics.flash_fee_lamports:
            _add(blockers, "PR209_FLASH_FEE_EFFECT_MISMATCH", "decoded flash fee effect does not match economics flash fee")
    required_output = (
        economics.repayment_lamports
        + economics.total_transaction_fee_lamports
        + economics.rent_lamports
        + economics.tip_lamports
        + economics.transfer_fee_lamports
        + economics.contingency_lamports
        + economics.minimum_profit_lamports
    )
    if economics.expected_output_lamports < required_output:
        _add(blockers, "PR209_CONSERVATIVE_OUTPUT_INSUFFICIENT", "expected output must cover repayment, total fee, rent, tip, transfer fees, contingency and minimum profit")


def _validate_fee_accounting(evidence: PR209AtomicEvidence, blockers: list[PR209Violation]) -> None:
    fees = evidence.fee_accounting
    if not _is_nonnegative_int(fees.projected_total_transaction_fee_lamports):
        _add(blockers, "PR209_BAD_PROJECTED_FEE", "projected total transaction fee must be non-negative integer")
    if fees.projected_total_transaction_fee_lamports != evidence.simulation.total_transaction_fee_lamports:
        _add(blockers, "PR209_PROJECTED_FEE_NOT_SIMULATION_FEE", "projected fee must equal exact simulation/message total transaction fee")
    if fees.projected_total_transaction_fee_lamports != evidence.economics.total_transaction_fee_lamports:
        _add(blockers, "PR209_ECONOMICS_FEE_NOT_TOTAL_TRANSACTION_FEE", "economics fee must be the total transaction fee, not split caller fields")
    if fees.failed_landing_fee_lamports is not None:
        if not _is_nonnegative_int(fees.failed_landing_fee_lamports):
            _add(blockers, "PR209_BAD_FAILED_LANDING_FEE", "failed landing fee must be non-negative integer")
        if fees.failed_landing_fee_lamports == 0:
            _add(blockers, "PR209_FAILED_LANDING_FEE_MUST_BE_AUTHORITATIVE", "a landed failed transaction cannot be reconciled with caller-supplied zero fee")


def _single_role_effect(effects: Sequence[DecodedSemanticEffect], role: str) -> DecodedSemanticEffect | None:
    matches = [effect for effect in effects if effect.role == role]
    return matches[0] if len(matches) == 1 else None


def _numeric_effect_fields(effect: DecodedSemanticEffect) -> Mapping[str, int]:
    return {
        "principal_lamports": effect.principal_lamports,
        "flash_fee_lamports": effect.flash_fee_lamports,
        "repayment_lamports": effect.repayment_lamports,
        "input_lamports": effect.input_lamports,
        "output_lamports": effect.output_lamports,
        "rent_lamports": effect.rent_lamports,
        "tip_lamports": effect.tip_lamports,
        "transfer_fee_lamports": effect.transfer_fee_lamports,
    }


def _is_strict_sha256(value: str) -> bool:
    if not isinstance(value, str) or not HEX_64_RE.match(value):
        return False
    return value not in {"0" * 64, "f" * 64}


def _is_nonnegative_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def _stable_hash(value: object) -> str:
    payload = json.dumps(_to_jsonable(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _to_jsonable(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _to_jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, float) and not math.isfinite(value):
        return "<non-finite>"
    return value


def _add(blockers: list[PR209Violation], code: str, message: str) -> None:
    blockers.append(PR209Violation(code=code, message=message))


def _dedupe(blockers: Iterable[PR209Violation]) -> Iterable[PR209Violation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        identity = (blocker.code, blocker.message)
        if identity not in seen:
            seen.add(identity)
            yield blocker
