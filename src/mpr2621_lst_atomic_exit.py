"""MPR-2621 sender-free LST NAV / atomic-exit arbitrage authority.

This module is deliberately side-effect free. It does not load wallets, call RPC,
construct/send transactions, or enable live trading. It qualifies one exact LST
capability and one immutable candidate from already-governed evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from hashlib import sha256
import json
from typing import Iterable, Mapping

SCHEMA_VERSION = "mpr-2621.lst-atomic-exit.v1"
SOL_MINT = "So11111111111111111111111111111111111111112"


class Mechanism(str, Enum):
    DEX_SWAP_LST_TO_SOL = "DEX_SWAP_LST_TO_SOL"
    SANCTUM_ROUTER_LST_TO_SOL = "SANCTUM_ROUTER_LST_TO_SOL"
    STAKEDEX_WITHDRAW_SOL = "STAKEDEX_WITHDRAW_SOL"
    PROTOCOL_LIQUID_UNSTAKE = "PROTOCOL_LIQUID_UNSTAKE"
    PROTOCOL_DEPOSIT_SOL_FOR_LST = "PROTOCOL_DEPOSIT_SOL_FOR_LST"
    STAKE_ACCOUNT_WITHDRAW = "STAKE_ACCOUNT_WITHDRAW"
    STAKE_ACCOUNT_DEACTIVATION = "STAKE_ACCOUNT_DEACTIVATION"
    LST_TO_LST_POOL_SWAP = "LST_TO_LST_POOL_SWAP"


IMMEDIATE_SOL_EXIT_MECHANISMS = frozenset(
    {
        Mechanism.DEX_SWAP_LST_TO_SOL,
        Mechanism.SANCTUM_ROUTER_LST_TO_SOL,
        Mechanism.STAKEDEX_WITHDRAW_SOL,
        Mechanism.PROTOCOL_LIQUID_UNSTAKE,
    }
)


class Decision(str, Enum):
    QUALIFIED_SENDER_FREE = "QUALIFIED_SENDER_FREE"
    NO_TRADE = "NO_TRADE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class LstCapability:
    capability_id: str
    mint: str
    token_program: str
    decimals: int
    staking_protocol: str
    pool_program: str
    pool_generation: str
    mechanism: Mechanism
    cluster: str
    genesis_hash: str
    evidence_hash: str
    status: str
    token2022_extensions: tuple[str, ...] = ()
    transfer_fee_modeled: bool = False
    route_program_ids: tuple[str, ...] = ()
    route_account_hash: str = ""
    source_pins: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NavState:
    epoch: int
    rooted_slot: int
    update_generation: str
    numerator_lamports: int
    denominator_atomic_lst: int
    liquid_sol_capacity_lamports: int
    state_hash: str
    fresh: bool
    complete: bool

    def rate(self) -> Fraction:
        _require_positive_int(self.numerator_lamports, "NAV_NUMERATOR")
        _require_positive_int(self.denominator_atomic_lst, "NAV_DENOMINATOR")
        return Fraction(self.numerator_lamports, self.denominator_atomic_lst)


@dataclass(frozen=True, slots=True)
class AcquisitionProof:
    provider: str
    input_sol_lamports: int
    guaranteed_lst_out_atomic: int
    route_program_ids: tuple[str, ...]
    route_account_hash: str
    request_id: str
    deadline_ms: int


@dataclass(frozen=True, slots=True)
class ExitProof:
    provider: str
    mechanism: Mechanism
    lst_in_atomic: int
    guaranteed_active_sol_out_lamports: int
    same_transaction: bool
    route_program_ids: tuple[str, ...]
    route_account_hash: str
    immediate_liquidity_lamports: int


@dataclass(frozen=True, slots=True)
class CostProof:
    lender_fee_lamports: int
    acquisition_fee_lamports: int
    exit_fee_lamports: int
    network_fee_lamports: int
    priority_fee_lamports: int
    tip_lamports: int
    rent_ata_wsol_lamports: int
    failure_reserve_lamports: int

    def total(self) -> int:
        values = (
            self.lender_fee_lamports,
            self.acquisition_fee_lamports,
            self.exit_fee_lamports,
            self.network_fee_lamports,
            self.priority_fee_lamports,
            self.tip_lamports,
            self.rent_ata_wsol_lamports,
            self.failure_reserve_lamports,
        )
        for value in values:
            _require_nonnegative_int(value, "COST")
        return sum(values)


@dataclass(frozen=True, slots=True)
class CandidateLimits:
    lender_capacity_lamports: int
    acquisition_capacity_lamports: int
    exit_capacity_lamports: int
    strategy_cap_lamports: int
    wallet_cost_reserve_lamports: int
    max_message_accounts: int
    message_accounts: int


@dataclass(frozen=True, slots=True)
class ShadowEvidence:
    capability_id: str
    mint: str
    real_observation: bool
    synthetic: bool
    eligible_duration_seconds: int
    epoch_transitions_observed: int
    source_generation: str


@dataclass(frozen=True, slots=True)
class LstAtomicExitCandidate:
    schema_version: str
    candidate_id: str
    capability: LstCapability
    nav: NavState
    acquisition: AcquisitionProof
    exit: ExitProof
    costs: CostProof
    limits: CandidateLimits
    flash_repayment_lamports: int
    minimum_surplus_lamports: int
    expected_profit_lamports: int | None = None
    premium_direction_requested: bool = False
    retry_generation: int = 1
    effect_issued_or_unknown: bool = False
    final_message_hash: str = ""
    final_simulation_hash: str = ""
    simulation_success: bool = False
    decoded_acquired_lst_atomic: int | None = None
    decoded_consumed_lst_atomic: int | None = None
    decoded_returned_sol_lamports: int | None = None
    decoded_flash_repaid_lamports: int | None = None
    residual_assets: Mapping[str, int] | None = None


@dataclass(frozen=True, slots=True)
class QualificationResult:
    decision: Decision
    blockers: tuple[str, ...]
    capability_id: str
    candidate_id: str
    nav_lamports_per_lst_atomic_num: int
    nav_lamports_per_lst_atomic_den: int
    guaranteed_surplus_lamports: int | None
    sender_allowed: bool = False
    signer_allowed: bool = False
    live_enabled: bool = False
    canary_eligible: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "decision": self.decision.value,
            "blockers": list(self.blockers),
            "capability_id": self.capability_id,
            "candidate_id": self.candidate_id,
            "nav_rate": [
                self.nav_lamports_per_lst_atomic_num,
                self.nav_lamports_per_lst_atomic_den,
            ],
            "guaranteed_surplus_lamports": self.guaranteed_surplus_lamports,
            "sender_allowed": self.sender_allowed,
            "signer_allowed": self.signer_allowed,
            "live_enabled": self.live_enabled,
            "canary_eligible": self.canary_eligible,
        }


def _require_nonnegative_int(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(code)
    return value


def _require_positive_int(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(code)
    return value


def _is_hash(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _add(blockers: list[str], code: str) -> None:
    if code not in blockers:
        blockers.append(code)


def _same_route_authority(cap: LstCapability, programs: Iterable[str], account_hash: str) -> bool:
    return tuple(programs) == tuple(cap.route_program_ids) and account_hash == cap.route_account_hash


def qualify_candidate(candidate: LstAtomicExitCandidate) -> QualificationResult:
    blockers: list[str] = []
    cap = candidate.capability

    if candidate.schema_version != SCHEMA_VERSION:
        _add(blockers, "SCHEMA_VERSION_MISMATCH")
    if cap.status != "reviewed_executable":
        _add(blockers, "LST_CAPABILITY_NOT_REVIEWED_EXECUTABLE")
    if not cap.capability_id or not cap.mint or cap.mint == SOL_MINT:
        _add(blockers, "INVALID_LST_CAPABILITY_IDENTITY")
    if not cap.token_program or not cap.staking_protocol or not cap.pool_program:
        _add(blockers, "INCOMPLETE_LST_PROTOCOL_BINDING")
    if isinstance(cap.decimals, bool) or not isinstance(cap.decimals, int) or not 0 <= cap.decimals <= 18:
        _add(blockers, "INVALID_LST_DECIMALS")
    if not _is_hash(cap.evidence_hash) or not _is_hash(cap.route_account_hash):
        _add(blockers, "CAPABILITY_EVIDENCE_HASH_INVALID")
    if cap.token2022_extensions and not cap.transfer_fee_modeled:
        _add(blockers, "TOKEN2022_EXTENSION_UNMODELED")
    if cap.mechanism not in IMMEDIATE_SOL_EXIT_MECHANISMS:
        _add(blockers, "MECHANISM_NOT_IMMEDIATE_ACTIVE_SOL_EXIT")

    if not candidate.nav.fresh:
        _add(blockers, "NAV_STATE_STALE")
    if not candidate.nav.complete:
        _add(blockers, "NAV_STATE_INCOMPLETE")
    if candidate.nav.epoch < 0 or candidate.nav.rooted_slot < 0 or not candidate.nav.update_generation:
        _add(blockers, "NAV_EPOCH_ROOT_BINDING_INVALID")
    try:
        rate = candidate.nav.rate()
        _require_nonnegative_int(candidate.nav.liquid_sol_capacity_lamports, "NAV_LIQUIDITY")
    except ValueError as exc:
        _add(blockers, str(exc))
        rate = Fraction(0, 1)

    acq = candidate.acquisition
    exit_proof = candidate.exit
    for value, code in (
        (acq.input_sol_lamports, "ACQUISITION_INPUT_INVALID"),
        (acq.guaranteed_lst_out_atomic, "ACQUISITION_OUTPUT_INVALID"),
        (exit_proof.lst_in_atomic, "EXIT_INPUT_INVALID"),
        (exit_proof.guaranteed_active_sol_out_lamports, "EXIT_OUTPUT_INVALID"),
        (exit_proof.immediate_liquidity_lamports, "EXIT_LIQUIDITY_INVALID"),
        (candidate.flash_repayment_lamports, "FLASH_REPAYMENT_INVALID"),
        (candidate.minimum_surplus_lamports, "MINIMUM_SURPLUS_INVALID"),
    ):
        try:
            _require_nonnegative_int(value, code)
        except ValueError:
            _add(blockers, code)

    if not acq.request_id or acq.deadline_ms <= 0:
        _add(blockers, "PROVIDER_REQUEST_ID_OR_DEADLINE_INVALID")
    if exit_proof.mechanism != cap.mechanism:
        _add(blockers, "EXIT_MECHANISM_CAPABILITY_MISMATCH")
    if not exit_proof.same_transaction:
        _add(blockers, "EXIT_NOT_SAME_TRANSACTION")
    if exit_proof.mechanism not in IMMEDIATE_SOL_EXIT_MECHANISMS:
        _add(blockers, "EXIT_NOT_ACTIVE_SOL_IMMEDIATE")
    if exit_proof.lst_in_atomic > acq.guaranteed_lst_out_atomic:
        _add(blockers, "EXIT_CONSUMES_UNGUARANTEED_LST")
    if exit_proof.immediate_liquidity_lamports < exit_proof.guaranteed_active_sol_out_lamports:
        _add(blockers, "EXIT_LIQUIDITY_INSUFFICIENT")
    if candidate.nav.liquid_sol_capacity_lamports < exit_proof.guaranteed_active_sol_out_lamports:
        _add(blockers, "NAV_EXIT_CAPACITY_INSUFFICIENT")
    if not _same_route_authority(cap, exit_proof.route_program_ids, exit_proof.route_account_hash):
        _add(blockers, "EXIT_ROUTE_AUTHORITY_MISMATCH")

    limits = candidate.limits
    try:
        bounds = tuple(
            _require_nonnegative_int(v, "CANDIDATE_LIMIT_INVALID")
            for v in (
                limits.lender_capacity_lamports,
                limits.acquisition_capacity_lamports,
                limits.exit_capacity_lamports,
                limits.strategy_cap_lamports,
            )
        )
        max_borrow = min(bounds)
        if acq.input_sol_lamports > max_borrow:
            _add(blockers, "BORROW_EXCEEDS_HARD_CAPACITY")
        _require_nonnegative_int(limits.wallet_cost_reserve_lamports, "WALLET_COST_RESERVE_INVALID")
        if limits.message_accounts <= 0 or limits.max_message_accounts <= 0 or limits.message_accounts > limits.max_message_accounts:
            _add(blockers, "MESSAGE_ACCOUNT_LIMIT_EXCEEDED")
    except ValueError as exc:
        _add(blockers, str(exc))

    if candidate.premium_direction_requested:
        _add(blockers, "PREMIUM_MINT_DIRECTION_DISABLED")
    if candidate.retry_generation <= 0:
        _add(blockers, "RETRY_GENERATION_INVALID")
    if candidate.effect_issued_or_unknown and candidate.retry_generation > 1:
        _add(blockers, "POST_EFFECT_RETRY_FORBIDDEN")

    if not candidate.final_message_hash or not _is_hash(candidate.final_message_hash):
        _add(blockers, "FINAL_MESSAGE_HASH_MISSING")
    if not candidate.final_simulation_hash or not _is_hash(candidate.final_simulation_hash):
        _add(blockers, "FINAL_SIMULATION_HASH_MISSING")
    if not candidate.simulation_success:
        _add(blockers, "FINAL_SIMULATION_NOT_SUCCESSFUL")

    decoded_values = (
        candidate.decoded_acquired_lst_atomic,
        candidate.decoded_consumed_lst_atomic,
        candidate.decoded_returned_sol_lamports,
        candidate.decoded_flash_repaid_lamports,
    )
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in decoded_values):
        _add(blockers, "SIMULATION_ACCOUNT_DELTAS_INCOMPLETE")
    else:
        if candidate.decoded_acquired_lst_atomic < acq.guaranteed_lst_out_atomic:
            _add(blockers, "SIMULATED_LST_ACQUISITION_BELOW_GUARANTEE")
        if candidate.decoded_consumed_lst_atomic != exit_proof.lst_in_atomic:
            _add(blockers, "SIMULATED_EXIT_INPUT_MISMATCH")
        if candidate.decoded_returned_sol_lamports < exit_proof.guaranteed_active_sol_out_lamports:
            _add(blockers, "SIMULATED_SOL_EXIT_BELOW_GUARANTEE")
        if candidate.decoded_flash_repaid_lamports != candidate.flash_repayment_lamports:
            _add(blockers, "SIMULATED_FLASH_REPAYMENT_MISMATCH")

    residuals = candidate.residual_assets or {}
    for mint, amount in residuals.items():
        if not mint or isinstance(amount, bool) or not isinstance(amount, int):
            _add(blockers, "RESIDUAL_ASSET_ACCOUNTING_INVALID")

    try:
        total_cost = candidate.costs.total()
    except ValueError as exc:
        _add(blockers, str(exc))
        total_cost = 0

    guaranteed_surplus: int | None = None
    if not blockers:
        guaranteed_surplus = (
            exit_proof.guaranteed_active_sol_out_lamports
            - candidate.flash_repayment_lamports
            - total_cost
        )
        if guaranteed_surplus < candidate.minimum_surplus_lamports:
            _add(blockers, "CONSERVATIVE_SURPLUS_BELOW_THRESHOLD")

    decision = Decision.QUALIFIED_SENDER_FREE
    if blockers:
        decision = Decision.NO_TRADE if all(
            code in {
                "CONSERVATIVE_SURPLUS_BELOW_THRESHOLD",
                "EXIT_LIQUIDITY_INSUFFICIENT",
                "NAV_EXIT_CAPACITY_INSUFFICIENT",
            }
            for code in blockers
        ) else Decision.BLOCKED

    return QualificationResult(
        decision=decision,
        blockers=tuple(blockers),
        capability_id=cap.capability_id,
        candidate_id=candidate.candidate_id,
        nav_lamports_per_lst_atomic_num=rate.numerator,
        nav_lamports_per_lst_atomic_den=rate.denominator,
        guaranteed_surplus_lamports=guaranteed_surplus,
    )


def qualify_shadow(capability: LstCapability, shadow: ShadowEvidence) -> tuple[bool, tuple[str, ...]]:
    blockers: list[str] = []
    if shadow.capability_id != capability.capability_id or shadow.mint != capability.mint:
        _add(blockers, "SHADOW_CAPABILITY_IDENTITY_MISMATCH")
    if not shadow.real_observation or shadow.synthetic:
        _add(blockers, "SHADOW_NOT_REAL_DATA")
    if isinstance(shadow.eligible_duration_seconds, bool) or shadow.eligible_duration_seconds <= 0:
        _add(blockers, "SHADOW_DURATION_INVALID")
    if shadow.epoch_transitions_observed < 1:
        _add(blockers, "EPOCH_TRANSITION_NOT_OBSERVED")
    if shadow.source_generation != capability.pool_generation:
        _add(blockers, "SHADOW_GENERATION_MISMATCH")
    return (not blockers, tuple(blockers))


def capability_digest(capability: LstCapability) -> str:
    payload = {
        "capability_id": capability.capability_id,
        "mint": capability.mint,
        "token_program": capability.token_program,
        "decimals": capability.decimals,
        "staking_protocol": capability.staking_protocol,
        "pool_program": capability.pool_program,
        "pool_generation": capability.pool_generation,
        "mechanism": capability.mechanism.value,
        "cluster": capability.cluster,
        "genesis_hash": capability.genesis_hash,
        "evidence_hash": capability.evidence_hash,
        "status": capability.status,
        "token2022_extensions": list(capability.token2022_extensions),
        "transfer_fee_modeled": capability.transfer_fee_modeled,
        "route_program_ids": list(capability.route_program_ids),
        "route_account_hash": capability.route_account_hash,
        "source_pins": list(capability.source_pins),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
