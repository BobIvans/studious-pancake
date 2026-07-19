"""PR-020 shadow-only liquidation domain model.

This module intentionally models only verified binary snapshot evidence.  It does
not scan chain state, decode lending bytes, sign, submit, or claim live execution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib, json
from typing import Mapping


class LendingProtocol(str, Enum):
    KAMINO_LEND = "kamino_lend"
    MARGINFI_V2 = "marginfi_v2"


class LiquidationStatus(str, Enum):
    INDEXED = "indexed"
    POTENTIALLY_LIQUIDATABLE = "potentially_liquidatable"
    PRE_SIMULATION_REJECTED = "pre_simulation_rejected"
    SIMULATED_NOT_LIQUIDATABLE = "simulated_not_liquidatable"
    SIMULATED_REPAYMENT_FAILED = "simulated_repayment_failed"
    SIMULATED_UNPROFITABLE = "simulated_unprofitable"
    SIMULATED_LIQUIDATION_RECONCILED = "simulated_liquidation_reconciled"


class LiquidationReason(str, Enum):
    LIQUIDATION_PROTOCOL_UNSUPPORTED = "liquidation_protocol_unsupported"
    LIQUIDATION_DEPLOYMENT_MISMATCH = "liquidation_deployment_mismatch"
    LIQUIDATION_IDL_VERSION_MISMATCH = "liquidation_idl_version_mismatch"
    LIQUIDATION_ACCOUNT_LAYOUT_INVALID = "liquidation_account_layout_invalid"
    TARGET_SNAPSHOT_INCOMPLETE = "target_snapshot_incomplete"
    TARGET_STATE_STALE = "target_state_stale"
    LIQUIDATION_SLOT_INCONSISTENT = "liquidation_slot_inconsistent"
    ORACLE_STALE = "oracle_stale"
    ORACLE_CONFIDENCE_INVALID = "oracle_confidence_invalid"
    HEALTH_MODEL_MISMATCH = "health_model_mismatch"
    TARGET_NOT_LIQUIDATABLE = "target_not_liquidatable"
    DEBT_OR_COLLATERAL_NOT_ELIGIBLE = "debt_or_collateral_not_eligible"
    CLOSE_FACTOR_UNKNOWN = "close_factor_unknown"
    LIQUIDATION_BONUS_UNKNOWN = "liquidation_bonus_unknown"
    LIQUIDATION_LIMIT_EXCEEDED = "liquidation_limit_exceeded"
    TARGET_RESERVE_LIQUIDITY_INSUFFICIENT = "target_reserve_liquidity_insufficient"
    FLASH_LIQUIDITY_INSUFFICIENT = "flash_liquidity_insufficient"
    FINANCING_TARGET_COMBINATION_UNSUPPORTED = "financing_target_combination_unsupported"
    UNWIND_ROUTE_NOT_EXECUTABLE = "unwind_route_not_executable"
    UNWIND_SLIPPAGE_EXCESSIVE = "unwind_slippage_excessive"
    LIQUIDATION_STRATEGY_CAP_EXCEEDED = "liquidation_strategy_cap_exceeded"
    LIQUIDATION_PLAN_NOT_COMPOSABLE = "liquidation_plan_not_composable"
    LIQUIDATION_POSTCONDITION_UNPROVEN = "liquidation_postcondition_unproven"
    SIMULATED_LIQUIDATION_REPAYMENT_FAILED = "simulated_liquidation_repayment_failed"
    SIMULATED_LIQUIDATION_UNPROFITABLE = "simulated_liquidation_unprofitable"
    SIMULATED_LIQUIDATION_RECONCILED = "simulated_liquidation_reconciled"


@dataclass(frozen=True, slots=True)
class ProtocolDeploymentSpec:
    protocol: LendingProtocol
    cluster: str
    program_id: str
    supported_version: str
    pinned_source: str
    pinned_commit: str
    idl_sha256: str
    verified_on: str
    enabled: bool
    disabled_reason: LiquidationReason | None = None


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    mint: str
    bank_or_reserve: str
    amount: int
    decimals: int
    role: str


@dataclass(frozen=True, slots=True)
class OracleSnapshot:
    source: str
    price_numerator: int
    price_denominator: int
    confidence_numerator: int
    confidence_denominator: int
    exponent: int
    publish_slot: int
    status: str
    raw_hash: str


@dataclass(frozen=True, slots=True)
class RiskConfigSnapshot:
    close_factor_bps: int | None
    max_liquidatable_value: int | None
    liquidation_bonus_bps: int | None
    protocol_fee_bps: int
    insurance_fee_bps: int
    health_assets_value: int
    health_liabilities_value: int
    risk_hash: str
    flags: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LiquidationTargetSnapshot:
    protocol: LendingProtocol
    deployment: ProtocolDeploymentSpec
    market: str
    target_account: str
    slot: int
    raw_hash: str
    positions: tuple[PositionSnapshot, ...]
    risk: RiskConfigSnapshot
    oracles: Mapping[str, OracleSnapshot]
    indexer_health_assets: int
    indexer_health_liabilities: int


@dataclass(frozen=True, slots=True)
class LiquiditySnapshot:
    debt_reserve_liquidity: int
    flash_capacity: int
    route_capacity: int
    route_min_out: int
    route_is_executable: bool
    token2022_transfer_fee_bps: int
    slot: int
    provenance: str


@dataclass(frozen=True, slots=True)
class LiquidationEligibility:
    status: LiquidationStatus
    reason: LiquidationReason | None
    debt: PositionSnapshot | None = None
    collateral: PositionSnapshot | None = None
    max_repay: int = 0
    trace: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LiquidationSizingResult:
    status: LiquidationStatus
    reason: LiquidationReason | None
    repay_amount: int = 0
    min_collateral_seized: int = 0
    minimum_final_output: int = 0
    exact_flash_repayment: int = 0
    conservative_profit: int = 0
    sizing_hash: str = ""
    bounds: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LiquidationInstruction:
    program_id: str
    name: str
    accounts: tuple[str, ...]
    data_hex: str


@dataclass(frozen=True, slots=True)
class LiquidationInstructionPlan:
    status: LiquidationStatus
    reason: LiquidationReason | None
    instructions: tuple[LiquidationInstruction, ...]
    end_flashloan_index: int
    message_hash: str
    plan_hash: str


@dataclass(frozen=True, slots=True)
class LiquidationSimulationEvidence:
    status: LiquidationStatus
    reason: LiquidationReason | None
    flash_repaid: bool
    postconditions_proven: bool
    simulated_profit: int
    simulation_slot: int
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class LiquidationShadowOutcome:
    status: LiquidationStatus
    reason: LiquidationReason | None
    target_account: str
    protocol: LendingProtocol
    plan_hash: str | None
    evidence_hash: str | None
    sent_transaction: bool = False
    live_permit_issued: bool = False


def canonical_hash(value: object) -> str:
    def default(obj: object):
        if isinstance(obj, Enum):
            return obj.value
        if hasattr(obj, "__dataclass_fields__"):
            return {k: getattr(obj, k) for k in obj.__dataclass_fields__}
        if isinstance(obj, bytes):
            return obj.hex()
        raise TypeError(type(obj).__name__)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=default).encode()).hexdigest()
