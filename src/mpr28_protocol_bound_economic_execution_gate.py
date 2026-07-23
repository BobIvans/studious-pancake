"""Side-effect-free MPR-28 protocol-bound economics evidence gate."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
import hashlib
import json
from typing import Mapping, Sequence

SCHEMA_VERSION = "mpr-28.protocol-bound-economic-execution.v1"
REQUIRED_CHAIN_PROGRAMS = (
    "solana_cluster", "spl_token", "spl_token_2022", "associated_token",
    "marginfi", "kamino", "jupiter",
)
REQUIRED_NEGATIVE_VECTORS = (
    "stale_quote", "expired_blockhash", "duplicate_sensitive_instruction",
    "unknown_side_effecting_instruction", "wrong_ata_pda", "mutable_freeze_authority",
    "mutable_close_authority", "unsupported_token_2022_extension",
    "message_mutated_after_simulation", "caller_supplied_profit", "capital_conflict",
    "wire_size_over_cap",
)
ABSORBED_FINDING_RANGE = tuple(f"V10-F-{i:03d}" for i in range(441, 464))


class MPR28GateState(StrEnum):
    QUALIFIED = "QUALIFIED"
    BLOCKED = "BLOCKED"


class MPR28ViolationLevel(StrEnum):
    BLOCKER = "BLOCKER"


@dataclass(frozen=True, slots=True)
class MPR28Violation:
    code: str
    message: str
    level: MPR28ViolationLevel = MPR28ViolationLevel.BLOCKER


@dataclass(frozen=True, slots=True)
class ChainProgramEvidence:
    name: str
    registry_generation: str
    source_artifact_hash: str
    executable_identity_hash: str
    rooted_account_or_binary_hash: str
    local_literals_removed: bool
    fixtures_generation_bound: bool


@dataclass(frozen=True, slots=True)
class ExactMessageEvidence:
    message_bytes_hash: str
    versioned_message_hash: str
    decoded_instruction_hash: str
    account_meta_hash: str
    alt_contents_hash: str
    payer_pubkey_hash: str
    blockhash_generation_hash: str
    compile_policy_hash: str
    wire_size_bytes: int
    wire_size_cap_bytes: int
    caller_supplied_digest_only: bool
    instructions_decoded_from_bytes: bool
    instruction_cardinality_checked: bool
    program_ids_from_registry_only: bool
    account_metas_from_bytes_only: bool
    alt_roots_verified: bool
    compute_budget_policy_bound: bool
    no_unknown_side_effecting_instructions: bool
    blockhash_current_height_verified: bool


@dataclass(frozen=True, slots=True)
class RawSimulationEvidence:
    simulation_request_hash: str
    message_bytes_hash: str
    raw_account_envelope_hash: str
    raw_logs_hash: str
    loaded_accounts_hash: str
    units_consumed: int
    pre_state_hash: str
    post_state_hash: str
    decoder_version_hash: str
    bounded_raw_state_preserved: bool
    sigverify_policy_explicit: bool
    simulation_success_consistent_with_error: bool
    retryability_typed_not_substring: bool
    raw_accounts_content_addressed: bool


@dataclass(frozen=True, slots=True)
class DecoderAccountingEvidence:
    accounting_hash: str
    message_bytes_hash: str
    simulation_request_hash: str
    protocol_registry_hash: str
    principal_lamports: int
    repayment_lamports: int
    protocol_fee_lamports: int
    tx_fee_lamports: int
    rent_lamports: int
    priority_tip_lamports: int
    transfer_fee_lamports: int
    wsol_lifecycle_lamports: int
    ata_lifecycle_lamports: int
    uncertainty_buffer_lamports: int
    simulated_delta_lamports: int
    conservative_net_pnl_lamports: int
    caller_manual_observations_allowed: bool
    decoder_computes_all_money: bool
    token_account_state_decoded: bool
    money_conservation_proven: bool
    marginfi_health_bound: bool
    kamino_health_bound_or_disabled: bool
    every_output_unit_explained: bool


@dataclass(frozen=True, slots=True)
class CapitalArbitrationEvidence:
    arbitration_generation_hash: str
    candidate_identity_hash: str
    wallet_capital_scope_hash: str
    account_exclusivity_hash: str
    blockhash_window_hash: str
    competing_candidates_evaluated: int
    accepted_candidates: int
    reservations_committed_under_durable_authority: bool
    no_capital_double_acceptance: bool
    route_exclusivity_checked: bool
    stale_generation_rejected: bool


@dataclass(frozen=True, slots=True)
class MPR28Evidence:
    mpr25_artifact_truth_accepted: bool
    mpr26_durable_authority_accepted: bool
    mpr27_rooted_provider_accepted: bool
    findings_covered: tuple[str, ...]
    chain_programs: tuple[ChainProgramEvidence, ...]
    exact_message: ExactMessageEvidence
    raw_simulation: RawSimulationEvidence
    decoder_accounting: DecoderAccountingEvidence
    capital_arbitration: CapitalArbitrationEvidence
    negative_vectors_passed: tuple[str, ...]
    golden_vector_from_installed_wheel: bool
    mutation_after_simulation_rejected: bool
    recorded_paper_only_replay_not_qualification: bool
    runtime_public_profit_constructors_removed: bool
    legacy_lamport_delta_simulator_disabled: bool
    durable_attempt_generation_bound: bool
    signer_or_sender_reachable: bool = False
    live_execution_enabled: bool = False
    private_key_material_accessible: bool = False


@dataclass(frozen=True, slots=True)
class MPR28Report:
    schema_version: str
    state: MPR28GateState
    violations: tuple[MPR28Violation, ...]
    evidence_hash: str
    paper_candidate_allowed: bool
    transaction_signer_allowed: bool
    sender_allowed: bool
    live_execution_allowed: bool
    private_key_material_allowed: bool


def evaluate_mpr28_evidence(evidence: MPR28Evidence) -> MPR28Report:
    violations: list[MPR28Violation] = []
    violations += _deps(evidence) + _safety(evidence) + _coverage(evidence)
    violations += _programs(evidence.chain_programs) + _message(evidence.exact_message)
    violations += _simulation(evidence.raw_simulation, evidence.exact_message)
    violations += _accounting(evidence.decoder_accounting, evidence.exact_message, evidence.raw_simulation)
    violations += _capital(evidence.capital_arbitration) + _cutover(evidence)
    return MPR28Report(
        SCHEMA_VERSION,
        MPR28GateState.BLOCKED if violations else MPR28GateState.QUALIFIED,
        tuple(violations),
        _stable_hash(_jsonable(evidence)),
        not violations,
        False,
        False,
        False,
        False,
    )


def _deps(e: MPR28Evidence) -> list[MPR28Violation]:
    out = []
    if not e.mpr25_artifact_truth_accepted:
        out.append(_v("MPR28_DEPENDS_ON_MPR25", "MPR-25 installed artifact truth is required."))
    if not e.mpr26_durable_authority_accepted:
        out.append(_v("MPR28_DEPENDS_ON_MPR26", "MPR-26 durable authority is required."))
    if not e.mpr27_rooted_provider_accepted:
        out.append(_v("MPR28_DEPENDS_ON_MPR27", "MPR-27 rooted provider evidence is required."))
    return out


def _safety(e: MPR28Evidence) -> list[MPR28Violation]:
    out = []
    if e.signer_or_sender_reachable:
        out.append(_v("MPR28_SIGNER_SENDER_REACHABLE", "MPR-28 must remain sender-free."))
    if e.live_execution_enabled:
        out.append(_v("MPR28_LIVE_ENABLED", "MPR-28 cannot enable live execution."))
    if e.private_key_material_accessible:
        out.append(_v("MPR28_PRIVATE_KEY_ACCESS", "Private key material is forbidden."))
    return out


def _coverage(e: MPR28Evidence) -> list[MPR28Violation]:
    missing = sorted(set(ABSORBED_FINDING_RANGE) - set(e.findings_covered))
    return [_v("MPR28_FINDINGS_INCOMPLETE", f"Missing absorbed findings: {', '.join(missing[:5])}")] if missing else []


def _programs(programs: Sequence[ChainProgramEvidence]) -> list[MPR28Violation]:
    out: list[MPR28Violation] = []
    by_name = {p.name: p for p in programs}
    if len(by_name) != len(programs):
        out.append(_v("MPR28_PROGRAM_REGISTRY_DUPLICATE", "Program registry evidence contains duplicate names."))
    for name in REQUIRED_CHAIN_PROGRAMS:
        if name not in by_name:
            out.append(_v("MPR28_PROGRAM_REGISTRY_MISSING", f"Missing registry evidence for {name}."))
    for p in programs:
        for key in ("registry_generation", "source_artifact_hash", "executable_identity_hash", "rooted_account_or_binary_hash"):
            if not _sha(getattr(p, key)):
                out.append(_v("MPR28_PROGRAM_HASH_INVALID", f"{p.name}.{key} must be sha256."))
        if not p.local_literals_removed:
            out.append(_v("MPR28_LOCAL_PROGRAM_LITERALS", f"{p.name} still allows local program literals."))
        if not p.fixtures_generation_bound:
            out.append(_v("MPR28_UNBOUND_FIXTURE", f"{p.name} fixtures are not generation-bound."))
    return out


def _message(m: ExactMessageEvidence) -> list[MPR28Violation]:
    out: list[MPR28Violation] = []
    for key in ("message_bytes_hash", "versioned_message_hash", "decoded_instruction_hash", "account_meta_hash", "alt_contents_hash", "payer_pubkey_hash", "blockhash_generation_hash", "compile_policy_hash"):
        if not _sha(getattr(m, key)):
            out.append(_v("MPR28_MESSAGE_HASH_INVALID", f"{key} must be sha256."))
    if any(isinstance(x, bool) or not isinstance(x, int) or x <= 0 for x in (m.wire_size_bytes, m.wire_size_cap_bytes)):
        out.append(_v("MPR28_WIRE_SIZE_INVALID", "wire sizes must be positive integers."))
    if m.wire_size_bytes > m.wire_size_cap_bytes:
        out.append(_v("MPR28_WIRE_SIZE_OVER_CAP", "Wire size exceeds configured cap."))
    if m.caller_supplied_digest_only:
        out.append(_v("MPR28_DIGEST_ONLY_MESSAGE", "Digest-only message evidence is forbidden."))
    for flag in ("instructions_decoded_from_bytes", "instruction_cardinality_checked", "program_ids_from_registry_only", "account_metas_from_bytes_only", "alt_roots_verified", "compute_budget_policy_bound", "no_unknown_side_effecting_instructions", "blockhash_current_height_verified"):
        if not getattr(m, flag):
            out.append(_v("MPR28_MESSAGE_PROOF_MISSING", f"{flag} must be proven."))
    return out


def _simulation(s: RawSimulationEvidence, m: ExactMessageEvidence) -> list[MPR28Violation]:
    out: list[MPR28Violation] = []
    for key in ("simulation_request_hash", "message_bytes_hash", "raw_account_envelope_hash", "raw_logs_hash", "loaded_accounts_hash", "pre_state_hash", "post_state_hash", "decoder_version_hash"):
        if not _sha(getattr(s, key)):
            out.append(_v("MPR28_SIM_HASH_INVALID", f"{key} must be sha256."))
    if s.message_bytes_hash != m.message_bytes_hash:
        out.append(_v("MPR28_SIM_MESSAGE_MISMATCH", "Simulation must use exact compiled message bytes."))
    if isinstance(s.units_consumed, bool) or not isinstance(s.units_consumed, int) or s.units_consumed < 0:
        out.append(_v("MPR28_SIM_UNITS_INVALID", "units_consumed must be a non-negative integer."))
    for flag in ("bounded_raw_state_preserved", "sigverify_policy_explicit", "simulation_success_consistent_with_error", "retryability_typed_not_substring", "raw_accounts_content_addressed"):
        if not getattr(s, flag):
            out.append(_v("MPR28_SIM_PROOF_MISSING", f"{flag} must be proven."))
    return out


def _accounting(a: DecoderAccountingEvidence, m: ExactMessageEvidence, s: RawSimulationEvidence) -> list[MPR28Violation]:
    out: list[MPR28Violation] = []
    for key in ("accounting_hash", "message_bytes_hash", "simulation_request_hash", "protocol_registry_hash"):
        if not _sha(getattr(a, key)):
            out.append(_v("MPR28_ACCOUNTING_HASH_INVALID", f"{key} must be sha256."))
    if a.message_bytes_hash != m.message_bytes_hash:
        out.append(_v("MPR28_ACCOUNTING_MESSAGE_MISMATCH", "Accounting must bind to exact message bytes."))
    if a.simulation_request_hash != s.simulation_request_hash:
        out.append(_v("MPR28_ACCOUNTING_SIM_MISMATCH", "Accounting must bind to simulation request."))
    money = ("principal_lamports", "repayment_lamports", "protocol_fee_lamports", "tx_fee_lamports", "rent_lamports", "priority_tip_lamports", "transfer_fee_lamports", "wsol_lifecycle_lamports", "ata_lifecycle_lamports", "uncertainty_buffer_lamports", "simulated_delta_lamports", "conservative_net_pnl_lamports")
    for key in money:
        val = getattr(a, key)
        if isinstance(val, bool) or not isinstance(val, int):
            out.append(_v("MPR28_MONEY_NOT_INTEGER", f"{key} must be integer base units."))
        elif key != "conservative_net_pnl_lamports" and val < 0:
            out.append(_v("MPR28_MONEY_NEGATIVE", f"{key} cannot be negative."))
    expected_net = a.simulated_delta_lamports - a.repayment_lamports - a.tx_fee_lamports - a.rent_lamports - a.priority_tip_lamports - a.transfer_fee_lamports - a.wsol_lifecycle_lamports - a.ata_lifecycle_lamports - a.uncertainty_buffer_lamports
    if a.conservative_net_pnl_lamports != expected_net:
        out.append(_v("MPR28_ACCOUNTING_FORMULA_MISMATCH", "Conservative PnL formula mismatch."))
    if a.repayment_lamports != a.principal_lamports + a.protocol_fee_lamports:
        out.append(_v("MPR28_REPAYMENT_MISMATCH", "Repayment must equal principal plus protocol fee."))
    if a.caller_manual_observations_allowed:
        out.append(_v("MPR28_CALLER_MONEY_ALLOWED", "Caller manual accounting observations are forbidden."))
    for flag in ("decoder_computes_all_money", "token_account_state_decoded", "money_conservation_proven", "marginfi_health_bound", "kamino_health_bound_or_disabled", "every_output_unit_explained"):
        if not getattr(a, flag):
            out.append(_v("MPR28_ACCOUNTING_PROOF_MISSING", f"{flag} must be proven."))
    return out


def _capital(c: CapitalArbitrationEvidence) -> list[MPR28Violation]:
    out: list[MPR28Violation] = []
    for key in ("arbitration_generation_hash", "candidate_identity_hash", "wallet_capital_scope_hash", "account_exclusivity_hash", "blockhash_window_hash"):
        if not _sha(getattr(c, key)):
            out.append(_v("MPR28_CAPITAL_HASH_INVALID", f"{key} must be sha256."))
    if c.accepted_candidates > c.competing_candidates_evaluated:
        out.append(_v("MPR28_CAPITAL_COUNT_ORDERING", "Accepted candidates cannot exceed evaluated candidates."))
    for key in ("competing_candidates_evaluated", "accepted_candidates"):
        val = getattr(c, key)
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            out.append(_v("MPR28_CAPITAL_COUNT_INVALID", f"{key} must be a non-negative integer."))
    for flag in ("reservations_committed_under_durable_authority", "no_capital_double_acceptance", "route_exclusivity_checked", "stale_generation_rejected"):
        if not getattr(c, flag):
            out.append(_v("MPR28_CAPITAL_PROOF_MISSING", f"{flag} must be proven."))
    return out


def _cutover(e: MPR28Evidence) -> list[MPR28Violation]:
    out: list[MPR28Violation] = []
    missing = sorted(set(REQUIRED_NEGATIVE_VECTORS) - set(e.negative_vectors_passed))
    if missing:
        out.append(_v("MPR28_NEGATIVE_VECTORS_INCOMPLETE", f"Missing vectors: {', '.join(missing[:5])}"))
    for flag in ("golden_vector_from_installed_wheel", "mutation_after_simulation_rejected", "recorded_paper_only_replay_not_qualification", "runtime_public_profit_constructors_removed", "legacy_lamport_delta_simulator_disabled", "durable_attempt_generation_bound"):
        if not getattr(e, flag):
            out.append(_v("MPR28_CUTOVER_INCOMPLETE", f"{flag} must be true."))
    return out


def _sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and value == value.lower() and all(c in "0123456789abcdef" for c in value)


def _v(code: str, message: str) -> MPR28Violation:
    return MPR28Violation(code, message)


def _stable_hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _jsonable(value: object) -> object:
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value
