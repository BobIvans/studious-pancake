"""Kamino lending/liquidation promotion contracts for PR-050.

The module is deliberately sender-free. It models only verified deployment
provenance, supported asset/market combinations, fixture decoding, integer
health/profitability math, and a shadow planner decision. A missing or
unverified registry fails closed instead of falling back to guessed Kamino
programs, reserves, or oracle layouts.

R02-CAP-B addition: a strictly read-only klend Reserve capacity/fee reader
for the pinned klend program (see the reader section below). It decodes
caller-supplied offline account bytes only; it performs no I/O, holds no
signer/sender authority, and never qualifies a FlashCapitalEdge. Effective
flash borrow capacity stays UNKNOWN (never zero) until audited program math
is proven against a live rooted-RPC snapshot with independent quorum.
"""

from __future__ import annotations

from dataclasses import dataclass, fields as dataclass_fields, is_dataclass
from enum import StrEnum
from fractions import Fraction
from importlib import resources
import hashlib
import json
import re
import struct
from typing import Any, Mapping, TYPE_CHECKING
from urllib.parse import urlparse

from solders.pubkey import Pubkey

from src.config.chain_registry import ChainRegistryError, validate_pubkey

if TYPE_CHECKING:
    from src.assets.resolution.evidence import Evidence

KAMINO_REGISTRY_SCHEMA = "pr050.kamino-supported-combinations.v1"
KAMINO_RESERVE_FIXTURE_DISCRIMINATOR = b"KAMRESV1"
_RESERVE_FIXTURE_FORMAT = "<8sQQQHHHH"
_HEX_64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_OFFICIAL_HOSTS = {"kamino.com", "docs.kamino.finance", "github.com"}


class KaminoRegistryError(ValueError):
    """Raised when Kamino protocol evidence is missing or malformed."""


def _require_non_empty(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KaminoRegistryError(f"{field} must be a non-empty string")
    return value.strip()


def _require_int(value: Any, *, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise KaminoRegistryError(f"{field} must be an integer")
    if value < minimum:
        raise KaminoRegistryError(f"{field} must be >= {minimum}")
    return value


def _require_bps(value: Any, *, field: str) -> int:
    checked = _require_int(value, field=field)
    if checked > 10_000:
        raise KaminoRegistryError(f"{field} must be <= 10000 bps")
    return checked


def _require_pubkey(value: Any, *, field: str) -> str:
    try:
        return validate_pubkey(str(value), field=field)
    except ChainRegistryError as exc:
        raise KaminoRegistryError(str(exc)) from exc


def _require_mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise KaminoRegistryError(f"{field} must be an object")
    return value


def _tuple_of_pubkeys(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise KaminoRegistryError(f"{field} must be a list")
    pubkeys = tuple(_require_pubkey(item, field=field) for item in value)
    if len(pubkeys) != len(set(pubkeys)):
        raise KaminoRegistryError(f"{field} must not contain duplicates")
    return pubkeys


@dataclass(frozen=True, slots=True)
class KaminoDeploymentProvenance:
    """Evidence required before a Kamino combination is considered verified."""

    source_url: str
    sdk_package: str
    lending_program_id: str
    idl_sha256: str
    rpc_fixture_sha256: str
    deployment_slot: int
    reviewed_at: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "KaminoDeploymentProvenance":
        return cls(
            source_url=_require_non_empty(
                payload.get("source_url"),
                field="source_url",
            ),
            sdk_package=_require_non_empty(
                payload.get("sdk_package"),
                field="sdk_package",
            ),
            lending_program_id=_require_pubkey(
                payload.get("lending_program_id"),
                field="provenance.lending_program_id",
            ),
            idl_sha256=_require_non_empty(
                payload.get("idl_sha256"),
                field="idl_sha256",
            ),
            rpc_fixture_sha256=_require_non_empty(
                payload.get("rpc_fixture_sha256"),
                field="rpc_fixture_sha256",
            ),
            deployment_slot=_require_int(
                payload.get("deployment_slot"),
                field="deployment_slot",
                minimum=1,
            ),
            reviewed_at=_require_non_empty(
                payload.get("reviewed_at"),
                field="reviewed_at",
            ),
        ).validated()

    def validated(self) -> "KaminoDeploymentProvenance":
        parsed = urlparse(self.source_url)
        if parsed.scheme != "https" or parsed.netloc not in _OFFICIAL_HOSTS:
            raise KaminoRegistryError(
                "Kamino source_url must point to an official HTTPS source"
            )
        if parsed.netloc == "github.com" and not parsed.path.startswith(
            "/Kamino-Finance/"
        ):
            raise KaminoRegistryError("GitHub provenance must be under Kamino-Finance")
        if self.sdk_package != "@kamino-finance/klend-sdk":
            raise KaminoRegistryError("Kamino lending provenance must use klend-sdk")
        if not _HEX_64_RE.fullmatch(self.idl_sha256):
            raise KaminoRegistryError("idl_sha256 must be a 64-character hex digest")
        if not _HEX_64_RE.fullmatch(self.rpc_fixture_sha256):
            raise KaminoRegistryError(
                "rpc_fixture_sha256 must be a 64-character hex digest"
            )
        _require_pubkey(
            self.lending_program_id,
            field="provenance.lending_program_id",
        )
        _require_int(self.deployment_slot, field="deployment_slot", minimum=1)
        return self


@dataclass(frozen=True, slots=True)
class KaminoSupportedCombination:
    """One verified Kamino lending market/asset combination."""

    combination_id: str
    cluster: str
    lending_program_id: str
    market_address: str
    collateral_mint: str
    debt_mint: str
    collateral_reserve: str
    debt_reserve: str
    collateral_oracle: str
    debt_oracle: str
    liquidation_bonus_bps: int
    protocol_fee_bps: int
    flash_loan_fee_bps: int
    min_net_profit_lamports: int
    writable_accounts: tuple[str, ...]
    provenance: KaminoDeploymentProvenance
    verified: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "KaminoSupportedCombination":
        provenance_payload = _require_mapping(
            payload.get("provenance"),
            field="provenance",
        )
        return cls(
            combination_id=_require_non_empty(
                payload.get("combination_id"),
                field="combination_id",
            ),
            cluster=_require_non_empty(payload.get("cluster"), field="cluster"),
            lending_program_id=_require_pubkey(
                payload.get("lending_program_id"),
                field="lending_program_id",
            ),
            market_address=_require_pubkey(
                payload.get("market_address"),
                field="market_address",
            ),
            collateral_mint=_require_pubkey(
                payload.get("collateral_mint"),
                field="collateral_mint",
            ),
            debt_mint=_require_pubkey(payload.get("debt_mint"), field="debt_mint"),
            collateral_reserve=_require_pubkey(
                payload.get("collateral_reserve"),
                field="collateral_reserve",
            ),
            debt_reserve=_require_pubkey(
                payload.get("debt_reserve"),
                field="debt_reserve",
            ),
            collateral_oracle=_require_pubkey(
                payload.get("collateral_oracle"),
                field="collateral_oracle",
            ),
            debt_oracle=_require_pubkey(
                payload.get("debt_oracle"),
                field="debt_oracle",
            ),
            liquidation_bonus_bps=_require_bps(
                payload.get("liquidation_bonus_bps"),
                field="liquidation_bonus_bps",
            ),
            protocol_fee_bps=_require_bps(
                payload.get("protocol_fee_bps"),
                field="protocol_fee_bps",
            ),
            flash_loan_fee_bps=_require_bps(
                payload.get("flash_loan_fee_bps"),
                field="flash_loan_fee_bps",
            ),
            min_net_profit_lamports=_require_int(
                payload.get("min_net_profit_lamports"),
                field="min_net_profit_lamports",
            ),
            writable_accounts=_tuple_of_pubkeys(
                payload.get("writable_accounts"),
                field="writable_accounts",
            ),
            provenance=KaminoDeploymentProvenance.from_mapping(provenance_payload),
            verified=bool(payload.get("verified", False)),
        ).validated()

    def validated(self) -> "KaminoSupportedCombination":
        if self.cluster != "mainnet-beta":
            raise KaminoRegistryError(
                "Kamino combinations must pin mainnet-beta explicitly"
            )
        if self.lending_program_id != self.provenance.lending_program_id:
            raise KaminoRegistryError("combination program does not match provenance")
        required_writable = {
            self.market_address,
            self.collateral_reserve,
            self.debt_reserve,
        }
        if not required_writable.issubset(set(self.writable_accounts)):
            raise KaminoRegistryError(
                "writable_accounts missing required market/reserve accounts"
            )
        if self.collateral_mint == self.debt_mint:
            raise KaminoRegistryError("collateral_mint and debt_mint must differ")
        if self.liquidation_bonus_bps <= 0:
            raise KaminoRegistryError("liquidation_bonus_bps must be positive")
        if len(self.writable_accounts) != len(set(self.writable_accounts)):
            raise KaminoRegistryError("writable_accounts must be unique")
        return self


@dataclass(frozen=True, slots=True)
class KaminoSupportedRegistry:
    """Registry of verified Kamino combinations. Empty is safe idle."""

    combinations: tuple[KaminoSupportedCombination, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "KaminoSupportedRegistry":
        if payload.get("schema_version") != KAMINO_REGISTRY_SCHEMA:
            raise KaminoRegistryError("unexpected Kamino registry schema")
        raw_combinations = payload.get("combinations", [])
        if not isinstance(raw_combinations, list):
            raise KaminoRegistryError("combinations must be a list")
        combinations = tuple(
            KaminoSupportedCombination.from_mapping(
                _require_mapping(item, field="combinations[]")
            )
            for item in raw_combinations
        )
        identifiers = [item.combination_id for item in combinations]
        if len(identifiers) != len(set(identifiers)):
            raise KaminoRegistryError("combination_id values must be unique")
        return cls(combinations=combinations)

    @property
    def verified_combinations(self) -> tuple[KaminoSupportedCombination, ...]:
        return tuple(item for item in self.combinations if item.verified)

    def require_verified(self, combination_id: str) -> KaminoSupportedCombination:
        if not self.verified_combinations:
            raise KaminoRegistryError("no verified Kamino combinations are configured")
        for combination in self.verified_combinations:
            if combination.combination_id == combination_id:
                return combination
        raise KaminoRegistryError(f"unsupported Kamino combination: {combination_id}")


@dataclass(frozen=True, slots=True)
class ProtocolCostBreakdown:
    """All costs used before a Kamino liquidation candidate is accepted."""

    network_fee_lamports: int
    priority_fee_lamports: int
    rent_lamports: int = 0
    slippage_lamports: int = 0
    flash_loan_fee_lamports: int = 0
    protocol_fee_lamports: int = 0

    def __post_init__(self) -> None:
        for name, value in (
            ("network_fee_lamports", self.network_fee_lamports),
            ("priority_fee_lamports", self.priority_fee_lamports),
            ("rent_lamports", self.rent_lamports),
            ("slippage_lamports", self.slippage_lamports),
            ("flash_loan_fee_lamports", self.flash_loan_fee_lamports),
            ("protocol_fee_lamports", self.protocol_fee_lamports),
        ):
            _require_int(value, field=name)

    @property
    def total_lamports(self) -> int:
        return (
            self.network_fee_lamports
            + self.priority_fee_lamports
            + self.rent_lamports
            + self.slippage_lamports
            + self.flash_loan_fee_lamports
            + self.protocol_fee_lamports
        )

    def with_protocol_costs(
        self,
        *,
        flash_loan_fee_lamports: int,
        protocol_fee_lamports: int,
    ) -> "ProtocolCostBreakdown":
        return ProtocolCostBreakdown(
            network_fee_lamports=self.network_fee_lamports,
            priority_fee_lamports=self.priority_fee_lamports,
            rent_lamports=self.rent_lamports,
            slippage_lamports=self.slippage_lamports,
            flash_loan_fee_lamports=flash_loan_fee_lamports,
            protocol_fee_lamports=protocol_fee_lamports,
        )


@dataclass(frozen=True, slots=True)
class UntrustedKaminoLiquidationCandidate:
    """Untrusted candidate from an indexer/RPC fixture before policy acceptance."""

    combination_id: str
    obligation_account: str
    health_factor_bps: int
    max_repay_lamports: int
    expected_bonus_lamports: int
    costs: ProtocolCostBreakdown

    def __post_init__(self) -> None:
        _require_non_empty(self.combination_id, field="combination_id")
        _require_pubkey(self.obligation_account, field="obligation_account")
        _require_int(self.health_factor_bps, field="health_factor_bps")
        _require_int(self.max_repay_lamports, field="max_repay_lamports", minimum=1)
        _require_int(self.expected_bonus_lamports, field="expected_bonus_lamports")


@dataclass(frozen=True, slots=True)
class KaminoProfitabilityEstimate:
    gross_bonus_lamports: int
    total_cost_lamports: int
    net_profit_lamports: int
    meets_min_profit: bool
    costs: ProtocolCostBreakdown


def estimate_liquidation_profitability(
    candidate: UntrustedKaminoLiquidationCandidate,
    combination: KaminoSupportedCombination,
) -> KaminoProfitabilityEstimate:
    """Estimate integer net profit after protocol, flash, and network costs."""

    protocol_fee = (
        candidate.max_repay_lamports * combination.protocol_fee_bps
    ) // 10_000
    flash_fee = (
        candidate.max_repay_lamports * combination.flash_loan_fee_bps
    ) // 10_000
    gross_bonus_cap = (
        candidate.max_repay_lamports * combination.liquidation_bonus_bps
    ) // 10_000
    gross_bonus = min(candidate.expected_bonus_lamports, gross_bonus_cap)
    costs = candidate.costs.with_protocol_costs(
        flash_loan_fee_lamports=flash_fee,
        protocol_fee_lamports=protocol_fee,
    )
    net_profit = gross_bonus - costs.total_lamports
    return KaminoProfitabilityEstimate(
        gross_bonus_lamports=gross_bonus,
        total_cost_lamports=costs.total_lamports,
        net_profit_lamports=net_profit,
        meets_min_profit=net_profit >= combination.min_net_profit_lamports,
        costs=costs,
    )


class KaminoShadowPlanStatus(StrEnum):
    ACCEPTED = "accepted_shadow_only"
    NO_VERIFIED_COMBINATION = "no_verified_kamino_combination"
    OBLIGATION_NOT_LIQUIDATABLE = "obligation_not_liquidatable"
    NOT_PROFITABLE_AFTER_COSTS = "not_profitable_after_all_costs"


@dataclass(frozen=True, slots=True)
class KaminoShadowPlan:
    accepted: bool
    status: KaminoShadowPlanStatus
    combination_id: str
    net_profit_lamports: int
    total_cost_lamports: int
    writable_accounts: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class KaminoShadowLiquidationPlanner:
    """Sender-free Kamino liquidation planner for verified shadow candidates."""

    registry: KaminoSupportedRegistry
    max_liquidatable_health_factor_bps: int = 10_000

    def plan(self, candidate: UntrustedKaminoLiquidationCandidate) -> KaminoShadowPlan:
        try:
            combination = self.registry.require_verified(candidate.combination_id)
        except KaminoRegistryError as exc:
            return KaminoShadowPlan(
                accepted=False,
                status=KaminoShadowPlanStatus.NO_VERIFIED_COMBINATION,
                combination_id=candidate.combination_id,
                net_profit_lamports=0,
                total_cost_lamports=0,
                writable_accounts=(),
                reason=str(exc),
            )
        if candidate.health_factor_bps >= self.max_liquidatable_health_factor_bps:
            return KaminoShadowPlan(
                accepted=False,
                status=KaminoShadowPlanStatus.OBLIGATION_NOT_LIQUIDATABLE,
                combination_id=candidate.combination_id,
                net_profit_lamports=0,
                total_cost_lamports=0,
                writable_accounts=(),
                reason="health factor is not below liquidation threshold",
            )
        estimate = estimate_liquidation_profitability(candidate, combination)
        if not estimate.meets_min_profit:
            return KaminoShadowPlan(
                accepted=False,
                status=KaminoShadowPlanStatus.NOT_PROFITABLE_AFTER_COSTS,
                combination_id=candidate.combination_id,
                net_profit_lamports=estimate.net_profit_lamports,
                total_cost_lamports=estimate.total_cost_lamports,
                writable_accounts=(),
                reason="net profit is below configured minimum after all costs",
            )
        return KaminoShadowPlan(
            accepted=True,
            status=KaminoShadowPlanStatus.ACCEPTED,
            combination_id=candidate.combination_id,
            net_profit_lamports=estimate.net_profit_lamports,
            total_cost_lamports=estimate.total_cost_lamports,
            writable_accounts=combination.writable_accounts,
            reason="verified Kamino shadow plan accepted without sender access",
        )


@dataclass(frozen=True, slots=True)
class KaminoReserveFixture:
    """Small exact binary fixture used to keep decoders fail-closed.

    This is not a production account layout. Production promotion must replace
    it with official IDL/golden-RPC bytes pinned in the registry provenance.
    """

    available_liquidity_lamports: int
    borrowed_liquidity_lamports: int
    oracle_price_microusd: int
    loan_to_value_bps: int
    liquidation_threshold_bps: int
    protocol_fee_bps: int
    liquidation_bonus_bps: int

    @classmethod
    def parse(cls, data: bytes) -> "KaminoReserveFixture":
        expected_size = struct.calcsize(_RESERVE_FIXTURE_FORMAT)
        if len(data) != expected_size:
            raise KaminoRegistryError(
                f"reserve fixture must be exactly {expected_size} bytes, got {len(data)}"
            )
        (
            discriminator,
            available,
            borrowed,
            price,
            ltv_bps,
            threshold_bps,
            protocol_fee_bps,
            bonus_bps,
        ) = struct.unpack(_RESERVE_FIXTURE_FORMAT, data)
        if discriminator != KAMINO_RESERVE_FIXTURE_DISCRIMINATOR:
            raise KaminoRegistryError("reserve fixture discriminator mismatch")
        if ltv_bps > threshold_bps:
            raise KaminoRegistryError(
                "loan-to-value must not exceed liquidation threshold"
            )
        return cls(
            available_liquidity_lamports=available,
            borrowed_liquidity_lamports=borrowed,
            oracle_price_microusd=price,
            loan_to_value_bps=_require_bps(ltv_bps, field="loan_to_value_bps"),
            liquidation_threshold_bps=_require_bps(
                threshold_bps,
                field="liquidation_threshold_bps",
            ),
            protocol_fee_bps=_require_bps(protocol_fee_bps, field="protocol_fee_bps"),
            liquidation_bonus_bps=_require_bps(
                bonus_bps,
                field="liquidation_bonus_bps",
            ),
        )


def load_default_kamino_registry() -> KaminoSupportedRegistry:
    resource = resources.files("src.resources").joinpath(
        "kamino_supported_combinations.json"
    )
    payload = json.loads(resource.read_text(encoding="utf-8"))
    return KaminoSupportedRegistry.from_mapping(
        _require_mapping(payload, field="registry")
    )


# ---------------------------------------------------------------------------
# R02-CAP-B: read-only klend reserve capacity reader (offline, fail-closed)
#
# Source pins (docs/roadmap/r02-capacity-recovery-2026-10-08/, VENDOR_MANIFEST):
# - SDK: @kamino-finance/klend-sdk 13.0.2, MIT, commit 3c3a38d4 (vendored
#   read-only codegen under offline/vendor/kamino/; blob SHAs verified by
#   offline/verify_offline.py).
# - Program source: Kamino-Finance/klend @a08760976f51a3a58c4a0c6ea27b4a0e
#   565bca79 (1.25.0), Business Source License 1.1 — reference only, NOT
#   vendored and NOT copied into this repository.
# - The byte offsets below are derived exclusively from the vendored MIT
#   codegen struct layouts (Reserve.ts, LastUpdate.ts, ReserveLiquidity.ts,
#   ReserveCollateral.ts, ReserveConfig.ts, ReserveFees.ts, fraction.ts) and
#   are cross-checked against offline/kamino_reserve_prefix_layout.json.
# - Fields whose sub-layouts are NOT vendored (BorrowRateCurve, TokenInfo,
#   WithdrawalCaps, and the whole LendingMarket account) are never decoded by
#   guessing offsets: they stay in a typed unpinned tail. Unknown is not zero.
#
# Zero network. Zero signing/sending. Execution authority NONE.
# ---------------------------------------------------------------------------

KLEND_SDK_PACKAGE = "@kamino-finance/klend-sdk"
KLEND_SDK_VERSION = "13.0.2"
KLEND_SDK_UPSTREAM_REPOSITORY = "https://github.com/Kamino-Finance/klend-sdk"
KLEND_SDK_UPSTREAM_COMMIT = "3c3a38d4ff9d7cf7b0380a383b81c9cd4f0f58b8"
KLEND_PROGRAM_ID = Pubkey.from_string("KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD")
KLEND_PROGRAM_SOURCE_REPOSITORY = "https://github.com/Kamino-Finance/klend"
KLEND_PROGRAM_SOURCE_COMMIT = "a08760976f51a3a58c4a0c6ea27b4a0e565bca79"
KLEND_PROGRAM_SOURCE_VERSION = "1.25.0"
KLEND_PROGRAM_SOURCE_LICENSE = "BUSL-1.1 (reference only; not vendored, not copied)"
KLEND_OFFLINE_PACK_PATH = "docs/roadmap/r02-capacity-recovery-2026-10-08/offline"
KLEND_RESERVE_PREFIX_SCHEMA = "kamino_reserve_prefix_layout.json"

# Fraction.ts pins: FRACTIONS = 60, ONE_SF = 2^60, and BigFractionBytes is a
# little-endian [u64; 4] limb array (bfToDecimal: value[i] << (i * 64)).
KLEND_FRACTION_SCALE_BITS = 60
KLEND_ONE_SF = 1 << 60
KLEND_BIG_FRACTION_LIMBS = 4

# Distinct flash borrow/repay instruction pair (R02_UNBLOCK_MATRIX.md, pinned
# in-pack dossier; program source stays BSL reference-only). Flash semantics
# are separate from standard obligation borrow; no Obligation account is
# involved in those instruction structs and none is ever created here.
KAMINO_FLASH_BORROW_INSTRUCTION_NAME = "flash_borrow_reserve_liquidity"
KAMINO_FLASH_REPAY_INSTRUCTION_NAME = "flash_repay_reserve_liquidity"
KAMINO_FLASH_REPAY_CARRIES_BORROW_INSTRUCTION_INDEX_U8 = True
KAMINO_FLASH_IX_OBLIGATION_ACCOUNT_REQUIRED = False

KAMINO_RESERVE_ACCOUNT_DISCRIMINATOR = bytes((43, 242, 204, 202, 26, 247, 59, 127))

# Pinned byte offsets (0-based from account start, including the 8-byte
# Anchor discriminator). Each constant cites its vendored codegen source.
KAMINO_RESERVE_VERSION_OFFSET = 8  # Reserve.ts: borsh.u64("version")
KAMINO_LAST_UPDATE_SLOT_OFFSET = 16  # LastUpdate.ts: borsh.u64("slot")
KAMINO_LAST_UPDATE_STALE_OFFSET = 24  # LastUpdate.ts: borsh.u8("stale")
KAMINO_LAST_UPDATE_PRICE_STATUS_OFFSET = 25  # LastUpdate.ts: borsh.u8("priceStatus")
KAMINO_LAST_UPDATE_ALIGNMENT_PAD_OFFSET = 26  # LastUpdate.ts: 2 x u8
KAMINO_LAST_UPDATE_TIMESTAMP_OFFSET = 28  # LastUpdate.ts: borsh.u32("timestamp")
KAMINO_LENDING_MARKET_OFFSET = 32  # Reserve.ts: borshAddress("lendingMarket")
KAMINO_FARM_COLLATERAL_OFFSET = 64  # Reserve.ts: borshAddress("farmCollateral")
KAMINO_FARM_DEBT_OFFSET = 96  # Reserve.ts: borshAddress("farmDebt")
# ReserveLiquidity.ts layout, starting at byte 128.
KAMINO_LIQUIDITY_MINT_OFFSET = 128  # borshAddress("mintPubkey")
KAMINO_LIQUIDITY_SUPPLY_VAULT_OFFSET = 160  # borshAddress("supplyVault")
KAMINO_LIQUIDITY_FEE_VAULT_OFFSET = 192  # borshAddress("feeVault")
KAMINO_TOTAL_AVAILABLE_AMOUNT_OFFSET = 224  # borsh.u64("totalAvailableAmount")
KAMINO_BORROWED_AMOUNT_SF_OFFSET = 232  # borsh.u128("borrowedAmountSf")
KAMINO_MARKET_PRICE_SF_OFFSET = 248  # borsh.u128("marketPriceSf")
KAMINO_MARKET_PRICE_LAST_UPDATED_TS_OFFSET = (
    264  # borsh.u64("marketPriceLastUpdatedTs")
)
KAMINO_MINT_DECIMALS_OFFSET = 272  # borsh.u64("mintDecimals")
KAMINO_DEPOSIT_LIMIT_CROSSED_TS_OFFSET = (
    280  # borsh.u64("depositLimitCrossedTimestamp")
)
KAMINO_BORROW_LIMIT_CROSSED_TS_OFFSET = 288  # borsh.u64("borrowLimitCrossedTimestamp")
# BigFractionBytes: [u64; 4] (fraction.ts bfToDecimal limb math).
KAMINO_CUMULATIVE_BORROW_RATE_BSF_OFFSET = 296
KAMINO_ACCUMULATED_PROTOCOL_FEES_SF_OFFSET = 328  # borsh.u128
KAMINO_ACCUMULATED_REFERRER_FEES_SF_OFFSET = 344  # borsh.u128
KAMINO_PENDING_REFERRER_FEES_SF_OFFSET = 360  # borsh.u128
KAMINO_ABSOLUTE_REFERRAL_RATE_SF_OFFSET = 376  # borsh.u128
KAMINO_LIQUIDITY_TOKEN_PROGRAM_OFFSET = 392  # borshAddress("tokenProgram")
KAMINO_REWARDS_AMOUNT_AVAILABLE_OFFSET = 424  # borsh.u64("rewardsAmountAvailable")
KAMINO_LIQUIDITY_PADDING2_OFFSET = 432  # 50 x u64
KAMINO_LIQUIDITY_PADDING3_OFFSET = 832  # 32 x u128
KAMINO_RESERVE_LIQUIDITY_PADDING_OFFSET = 1344  # Reserve.ts: 150 x u64
# ReserveCollateral.ts layout, starting at byte 2544.
KAMINO_COLLATERAL_MINT_OFFSET = 2544  # borshAddress("mintPubkey")
KAMINO_COLLATERAL_MINT_TOTAL_SUPPLY_OFFSET = 2576  # borsh.u64("mintTotalSupply")
KAMINO_COLLATERAL_SUPPLY_VAULT_OFFSET = 2584  # borshAddress("supplyVault")
KAMINO_COLLATERAL_PADDING1_OFFSET = 2616  # 32 x u128
KAMINO_COLLATERAL_PADDING2_OFFSET = 3128  # 32 x u128
KAMINO_RESERVE_COLLATERAL_PADDING_OFFSET = 3640  # Reserve.ts: 150 x u64
# ReserveConfig.ts leading fields, starting at byte 4840. Everything in the
# config after ReserveFees (borrowRateCurve, borrowFactorPct, depositLimit,
# borrowLimit, tokenInfo, withdrawal caps, elevation groups, ...) depends on
# sub-layouts that are NOT vendored, so it is never decoded here.
KAMINO_CONFIG_STATUS_OFFSET = 4840  # ReserveConfig.ts: borsh.u8("status")
KAMINO_CONFIG_PADDING_DEPRECATED_ASSET_TIER_OFFSET = 4841  # borsh.u8
KAMINO_CONFIG_HOST_FIXED_INTEREST_RATE_BPS_OFFSET = 4842  # borsh.u16
KAMINO_CONFIG_MIN_DELEVERAGING_BONUS_BPS_OFFSET = 4844  # borsh.u16
KAMINO_CONFIG_BLOCK_CTOKEN_USAGE_OFFSET = 4846  # borsh.u8
KAMINO_CONFIG_EARLY_REPAY_REMAINING_INTEREST_PCT_OFFSET = 4847  # borsh.u8
KAMINO_CONFIG_EMERGENCY_MODE_OFFSET = 4848  # borsh.u8("emergencyMode")
KAMINO_CONFIG_INTEREST_RATE_BASIS_OFFSET = 4849  # borsh.u8
KAMINO_CONFIG_RESERVED1_OFFSET = 4850  # 3 x u8
KAMINO_CONFIG_PROTOCOL_ORDER_EXECUTION_FEE_PCT_OFFSET = 4853  # borsh.u8
KAMINO_CONFIG_PROTOCOL_TAKE_RATE_PCT_OFFSET = 4854  # borsh.u8
KAMINO_CONFIG_PROTOCOL_LIQUIDATION_FEE_PCT_OFFSET = 4855  # borsh.u8
KAMINO_CONFIG_LOAN_TO_VALUE_PCT_OFFSET = 4856  # borsh.u8
KAMINO_CONFIG_LIQUIDATION_THRESHOLD_PCT_OFFSET = 4857  # borsh.u8
KAMINO_CONFIG_MIN_LIQUIDATION_BONUS_BPS_OFFSET = 4858  # borsh.u16
KAMINO_CONFIG_MAX_LIQUIDATION_BONUS_BPS_OFFSET = 4860  # borsh.u16
KAMINO_CONFIG_BAD_DEBT_LIQUIDATION_BONUS_BPS_OFFSET = 4862  # borsh.u16
KAMINO_CONFIG_DELEVERAGING_MARGIN_CALL_PERIOD_SECS_OFFSET = 4864  # borsh.u64
KAMINO_CONFIG_DELEVERAGING_THRESHOLD_DECREASE_BPS_PER_DAY_OFFSET = 4872  # borsh.u64
KAMINO_CONFIG_FEES_ORIGINATION_FEE_SF_OFFSET = 4880  # ReserveFees.ts: borsh.u64
KAMINO_CONFIG_FEES_FLASH_LOAN_FEE_SF_OFFSET = 4888  # ReserveFees.ts: borsh.u64
KAMINO_CONFIG_FEES_PADDING_OFFSET = 4896  # ReserveFees.ts: 8 x u8
# Last byte covered by a vendored layout: end of ReserveFees padding. The
# account region at and beyond this offset is an UNAUDITED tail: it is hashed
# for provenance but never interpreted (no guessed offsets, no guessed LEN).
KAMINO_RESERVE_PINNED_PREFIX_LEN = 4904

KAMINO_RESERVE_PINNED_FIELDS: dict[str, tuple[int, int]] = {
    "version": (KAMINO_RESERVE_VERSION_OFFSET, 8),
    "last_update_slot": (KAMINO_LAST_UPDATE_SLOT_OFFSET, 8),
    "last_update_stale": (KAMINO_LAST_UPDATE_STALE_OFFSET, 1),
    "last_update_price_status": (KAMINO_LAST_UPDATE_PRICE_STATUS_OFFSET, 1),
    "last_update_pad": (KAMINO_LAST_UPDATE_ALIGNMENT_PAD_OFFSET, 2),
    "last_update_timestamp": (KAMINO_LAST_UPDATE_TIMESTAMP_OFFSET, 4),
    "lending_market": (KAMINO_LENDING_MARKET_OFFSET, 32),
    "farm_collateral": (KAMINO_FARM_COLLATERAL_OFFSET, 32),
    "farm_debt": (KAMINO_FARM_DEBT_OFFSET, 32),
    "liquidity_mint": (KAMINO_LIQUIDITY_MINT_OFFSET, 32),
    "liquidity_supply_vault": (KAMINO_LIQUIDITY_SUPPLY_VAULT_OFFSET, 32),
    "liquidity_fee_vault": (KAMINO_LIQUIDITY_FEE_VAULT_OFFSET, 32),
    "total_available_amount": (KAMINO_TOTAL_AVAILABLE_AMOUNT_OFFSET, 8),
    "borrowed_amount_sf": (KAMINO_BORROWED_AMOUNT_SF_OFFSET, 16),
    "market_price_sf": (KAMINO_MARKET_PRICE_SF_OFFSET, 16),
    "market_price_last_updated_ts": (KAMINO_MARKET_PRICE_LAST_UPDATED_TS_OFFSET, 8),
    "mint_decimals": (KAMINO_MINT_DECIMALS_OFFSET, 8),
    "deposit_limit_crossed_ts": (KAMINO_DEPOSIT_LIMIT_CROSSED_TS_OFFSET, 8),
    "borrow_limit_crossed_ts": (KAMINO_BORROW_LIMIT_CROSSED_TS_OFFSET, 8),
    "cumulative_borrow_rate_bsf": (KAMINO_CUMULATIVE_BORROW_RATE_BSF_OFFSET, 32),
    "accumulated_protocol_fees_sf": (KAMINO_ACCUMULATED_PROTOCOL_FEES_SF_OFFSET, 16),
    "accumulated_referrer_fees_sf": (KAMINO_ACCUMULATED_REFERRER_FEES_SF_OFFSET, 16),
    "pending_referrer_fees_sf": (KAMINO_PENDING_REFERRER_FEES_SF_OFFSET, 16),
    "absolute_referral_rate_sf": (KAMINO_ABSOLUTE_REFERRAL_RATE_SF_OFFSET, 16),
    "liquidity_token_program": (KAMINO_LIQUIDITY_TOKEN_PROGRAM_OFFSET, 32),
    "rewards_amount_available": (KAMINO_REWARDS_AMOUNT_AVAILABLE_OFFSET, 8),
    "liquidity_padding2": (KAMINO_LIQUIDITY_PADDING2_OFFSET, 400),
    "liquidity_padding3": (KAMINO_LIQUIDITY_PADDING3_OFFSET, 512),
    "reserve_liquidity_padding": (KAMINO_RESERVE_LIQUIDITY_PADDING_OFFSET, 1200),
    "collateral_mint": (KAMINO_COLLATERAL_MINT_OFFSET, 32),
    "collateral_mint_total_supply": (KAMINO_COLLATERAL_MINT_TOTAL_SUPPLY_OFFSET, 8),
    "collateral_supply_vault": (KAMINO_COLLATERAL_SUPPLY_VAULT_OFFSET, 32),
    "collateral_padding1": (KAMINO_COLLATERAL_PADDING1_OFFSET, 512),
    "collateral_padding2": (KAMINO_COLLATERAL_PADDING2_OFFSET, 512),
    "reserve_collateral_padding": (KAMINO_RESERVE_COLLATERAL_PADDING_OFFSET, 1200),
    "config_status": (KAMINO_CONFIG_STATUS_OFFSET, 1),
    "config_padding_deprecated_asset_tier": (
        KAMINO_CONFIG_PADDING_DEPRECATED_ASSET_TIER_OFFSET,
        1,
    ),
    "config_host_fixed_interest_rate_bps": (
        KAMINO_CONFIG_HOST_FIXED_INTEREST_RATE_BPS_OFFSET,
        2,
    ),
    "config_min_deleveraging_bonus_bps": (
        KAMINO_CONFIG_MIN_DELEVERAGING_BONUS_BPS_OFFSET,
        2,
    ),
    "config_block_ctoken_usage": (KAMINO_CONFIG_BLOCK_CTOKEN_USAGE_OFFSET, 1),
    "config_early_repay_remaining_interest_pct": (
        KAMINO_CONFIG_EARLY_REPAY_REMAINING_INTEREST_PCT_OFFSET,
        1,
    ),
    "config_emergency_mode": (KAMINO_CONFIG_EMERGENCY_MODE_OFFSET, 1),
    "config_interest_rate_basis": (KAMINO_CONFIG_INTEREST_RATE_BASIS_OFFSET, 1),
    "config_reserved1": (KAMINO_CONFIG_RESERVED1_OFFSET, 3),
    "config_protocol_order_execution_fee_pct": (
        KAMINO_CONFIG_PROTOCOL_ORDER_EXECUTION_FEE_PCT_OFFSET,
        1,
    ),
    "config_protocol_take_rate_pct": (KAMINO_CONFIG_PROTOCOL_TAKE_RATE_PCT_OFFSET, 1),
    "config_protocol_liquidation_fee_pct": (
        KAMINO_CONFIG_PROTOCOL_LIQUIDATION_FEE_PCT_OFFSET,
        1,
    ),
    "config_loan_to_value_pct": (KAMINO_CONFIG_LOAN_TO_VALUE_PCT_OFFSET, 1),
    "config_liquidation_threshold_pct": (
        KAMINO_CONFIG_LIQUIDATION_THRESHOLD_PCT_OFFSET,
        1,
    ),
    "config_min_liquidation_bonus_bps": (
        KAMINO_CONFIG_MIN_LIQUIDATION_BONUS_BPS_OFFSET,
        2,
    ),
    "config_max_liquidation_bonus_bps": (
        KAMINO_CONFIG_MAX_LIQUIDATION_BONUS_BPS_OFFSET,
        2,
    ),
    "config_bad_debt_liquidation_bonus_bps": (
        KAMINO_CONFIG_BAD_DEBT_LIQUIDATION_BONUS_BPS_OFFSET,
        2,
    ),
    "config_deleveraging_margin_call_period_secs": (
        KAMINO_CONFIG_DELEVERAGING_MARGIN_CALL_PERIOD_SECS_OFFSET,
        8,
    ),
    "config_deleveraging_threshold_decrease_bps_per_day": (
        KAMINO_CONFIG_DELEVERAGING_THRESHOLD_DECREASE_BPS_PER_DAY_OFFSET,
        8,
    ),
    "config_origination_fee_sf": (KAMINO_CONFIG_FEES_ORIGINATION_FEE_SF_OFFSET, 8),
    "config_flash_loan_fee_sf": (KAMINO_CONFIG_FEES_FLASH_LOAN_FEE_SF_OFFSET, 8),
    "config_fees_padding": (KAMINO_CONFIG_FEES_PADDING_OFFSET, 8),
}

SPL_TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
SPL_TOKEN_2022_PROGRAM_ID = Pubkey.from_string(
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
)
KAMINO_SPL_TOKEN_ACCOUNT_LEN = 165
SUPPORTED_KAMINO_TOKEN_PROGRAMS = (SPL_TOKEN_PROGRAM_ID, SPL_TOKEN_2022_PROGRAM_ID)

READER_DECODER_IDENTITY = "kamino.klend.reserve.capacity-reader.v1"
READER_DECODER_GENERATION = 1
READER_EXECUTION_AUTHORITY = "NONE"

_ZERO_PUBKEY = Pubkey.from_bytes(bytes(32))
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Constraints that are NOT proven by this offline reader. Every member is a
# typed reason why decoded raw amounts must never be presented as effective
# flash borrow capacity. Unknown is not zero.
KAMINO_UNPINNED_CAPACITY_GAPS: tuple[str, ...] = (
    "BORROW_LIMIT_UNDECODABLE_OFFLINE",
    "CONFIG_TAIL_LAYOUT_UNPINNED",
    "CUMULATIVE_BORROW_RATE_UNAUDITED",
    "EMERGENCY_MODE_SEMANTICS_UNPINNED",
    "FLASH_FEE_DEDUCTION_SEMANTICS_UNAUDITED",
    "FEE_ROUNDING_RULE_UNPINNED",
    "INTEREST_ACCRUAL_LAZY_UPDATE_UNAUDITED",
    "LENDING_MARKET_LAYOUT_UNPINNED",
    "MINT_ACCOUNT_NOT_DECODED_OFFLINE",
    "ORACLE_HEALTH_ELIGIBILITY_UNPINNED",
    "ORACLE_PRICE_STATUS_SEMANTICS_UNPINNED",
    "ORIGINATION_FEE_PAYABLE_AMOUNT_UNPINNED",
    "MARKET_PRICE_SEMANTICS_UNAUDITED",
    "REFERRER_FEE_VALUATION_UNPINNED",
    "RESERVE_STATUS_ENUM_UNPINNED",
    "RESERVE_VERSION_SEMANTICS_UNPINNED",
    "RISK_CONFIG_SEMANTICS_UNAUDITED",
    "SUPPLY_VAULT_AUTHORITY_BINDING_UNPROVEN",
    "UTILIZATION_CONFIG_UNDECODABLE_OFFLINE",
)


class KaminoCapacityRejectionCode(StrEnum):
    """Typed fail-closed rejection and blocker codes for the CAP-B reader."""

    RESERVE_UNKNOWN_DISCRIMINATOR = "R02CAPB_RESERVE_UNKNOWN_DISCRIMINATOR"
    RESERVE_TRUNCATED_LAYOUT = "R02CAPB_RESERVE_TRUNCATED_LAYOUT"
    RESERVE_OWNER_MISMATCH = "R02CAPB_RESERVE_OWNER_MISMATCH"
    RESERVE_MARKET_BINDING_MISMATCH = "R02CAPB_RESERVE_MARKET_BINDING_MISMATCH"
    RESERVE_LAST_UPDATE_STALE = "R02CAPB_RESERVE_LAST_UPDATE_STALE"
    RESERVE_CONFIG_STATUS_UNKNOWN = "R02CAPB_RESERVE_CONFIG_STATUS_UNKNOWN"
    RESERVE_EMERGENCY_MODE_NONZERO = "R02CAPB_RESERVE_EMERGENCY_MODE_NONZERO"
    RESERVE_ZERO_MINT = "R02CAPB_RESERVE_ZERO_MINT"
    RESERVE_MINT_BINDING_MISMATCH = "R02CAPB_RESERVE_MINT_BINDING_MISMATCH"
    VAULT_ADDRESS_BINDING_MISMATCH = "R02CAPB_VAULT_ADDRESS_BINDING_MISMATCH"
    VAULT_TOKEN_PROGRAM_MISMATCH = "R02CAPB_VAULT_TOKEN_PROGRAM_MISMATCH"
    VAULT_LAYOUT_MISMATCH = "R02CAPB_VAULT_LAYOUT_MISMATCH"
    VAULT_MINT_BINDING_MISMATCH = "R02CAPB_VAULT_MINT_BINDING_MISMATCH"
    VAULT_FROZEN = "R02CAPB_VAULT_FROZEN"
    VAULT_ACCOUNT_STATE_UNKNOWN = "R02CAPB_VAULT_ACCOUNT_STATE_UNKNOWN"
    VAULT_DELEGATE_UNPROVEN = "R02CAPB_VAULT_DELEGATE_UNPROVEN"
    VAULT_CLOSE_AUTHORITY_UNPROVEN = "R02CAPB_VAULT_CLOSE_AUTHORITY_UNPROVEN"
    CAPACITY_STATE_INVALID = "R02CAPB_CAPACITY_STATE_INVALID"
    MISSING_EFFECTIVE_FLASH_CAP = "MISSING_EFFECTIVE_FLASH_CAP"
    LIVE_ROOTED_RPC_NOT_AUTHORIZED = "LIVE_ROOTED_RPC_NOT_AUTHORIZED"
    GRAPH_ALLOWANCE_PENDING = "GRAPH_ALLOWANCE_PENDING"


class KaminoCapacityReaderError(ValueError):
    """Raised when the klend reserve reader must fail closed; carries a code."""

    def __init__(self, code: KaminoCapacityRejectionCode, message: str) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code


class KaminoCapacityDerivation(StrEnum):
    """How an effective capacity value was proven. Only UNPROVEN exists today.

    A future live reader must add an explicit proven-derivation member backed
    by audited program math on a rooted-RPC quorum snapshot before any integer
    effective capacity may be carried. Until then, carrying an effective
    capacity is structurally impossible (enforced in the observation class).
    """

    UNPROVEN = "R02CAPB_CAPACITY_DERIVATION_UNPROVEN"


class KaminoSlotProvenance(StrEnum):
    OFFLINE_FIXTURE_NOT_ROOTED = "OFFLINE_FIXTURE_NOT_ROOTED"
    LIVE_ROOTED_RPC = "LIVE_ROOTED_RPC"


@dataclass(frozen=True, slots=True)
class KaminoLastUpdateState:
    """Decoded klend LastUpdate (LastUpdate.ts, 16 bytes at offset 16)."""

    slot: int
    stale: int
    price_status: int
    timestamp: int


@dataclass(frozen=True, slots=True)
class KaminoReserveLiquidityState:
    """Decoded klend ReserveLiquidity (ReserveLiquidity.ts, 1216 bytes @128)."""

    mint: Pubkey
    supply_vault: Pubkey
    fee_vault: Pubkey
    total_available_amount: int
    borrowed_amount_sf: int
    market_price_sf: int
    market_price_last_updated_ts: int
    mint_decimals_raw: int
    deposit_limit_crossed_timestamp: int
    borrow_limit_crossed_timestamp: int
    cumulative_borrow_rate_bsf_limbs: tuple[int, int, int, int]
    accumulated_protocol_fees_sf: int
    accumulated_referrer_fees_sf: int
    pending_referrer_fees_sf: int
    absolute_referral_rate_sf: int
    token_program: Pubkey
    rewards_amount_available: int


@dataclass(frozen=True, slots=True)
class KaminoReserveCollateralState:
    """Decoded klend ReserveCollateral (ReserveCollateral.ts, 1096 bytes @2544)."""

    mint: Pubkey
    mint_total_supply: int
    supply_vault: Pubkey


@dataclass(frozen=True, slots=True)
class KaminoReserveConfigPinnedState:
    """ReserveConfig fields pinned by vendored layouts (ReserveConfig.ts)."""

    status_raw: int
    emergency_mode: int
    padding_deprecated_asset_tier: int
    host_fixed_interest_rate_bps: int
    min_deleveraging_bonus_bps: int
    block_ctoken_usage: int
    early_repay_remaining_interest_pct: int
    interest_rate_basis: int
    reserved1: tuple[int, int, int]
    protocol_order_execution_fee_pct: int
    protocol_take_rate_pct: int
    protocol_liquidation_fee_pct: int
    loan_to_value_pct: int
    liquidation_threshold_pct: int
    min_liquidation_bonus_bps: int
    max_liquidation_bonus_bps: int
    bad_debt_liquidation_bonus_bps: int
    deleveraging_margin_call_period_secs: int
    deleveraging_threshold_decrease_bps_per_day: int
    origination_fee_sf: int
    flash_loan_fee_sf: int


@dataclass(frozen=True, slots=True)
class KaminoReserveState:
    """Full reserve decode limited to exactly the vendored pinned layout."""

    version_raw: int
    last_update: KaminoLastUpdateState
    lending_market: Pubkey
    farm_collateral: Pubkey
    farm_debt: Pubkey
    liquidity: KaminoReserveLiquidityState
    collateral: KaminoReserveCollateralState
    config: KaminoReserveConfigPinnedState
    unpinned_tail_len: int
    unpinned_tail_sha256: str


def _read_uint(raw: bytes, offset: int, size: int, label: str) -> int:
    end = offset + size
    if len(raw) < end:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.RESERVE_TRUNCATED_LAYOUT,
            f"truncated reserve field {label} (need bytes [{offset}:{end}])",
        )
    return int.from_bytes(raw[offset:end], "little")


def _read_pubkey(raw: bytes, offset: int, label: str) -> Pubkey:
    end = offset + 32
    if len(raw) < end:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.RESERVE_TRUNCATED_LAYOUT,
            f"truncated reserve field {label} (need bytes [{offset}:{end}])",
        )
    return Pubkey.from_bytes(raw[offset:end])


def decode_kamino_reserve(
    data: bytes,
    *,
    owner: Pubkey,
    lending_market: Pubkey,
) -> KaminoReserveState:
    """Fail-closed decode of one caller-supplied klend Reserve account.

    ``owner`` is the observed on-chain account owner program. ``lending_market``
    is the reviewed market address from a governed registry; the decoded
    ``lendingMarket`` field must bind it exactly. The decode covers exactly the
    vendored pinned layout (through ``config.fees`` padding, byte 4904); the
    remaining tail is hashed, never interpreted. A truncated account, wrong
    discriminator, wrong owner, wrong market binding, stale last-update, or
    unknown reserve status/emergency-mode flag fails closed.
    """

    raw = bytes(data)
    if len(raw) < KAMINO_RESERVE_PINNED_PREFIX_LEN:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.RESERVE_TRUNCATED_LAYOUT,
            "Reserve account is shorter than the pinned layout through "
            f"config.fees ({KAMINO_RESERVE_PINNED_PREFIX_LEN} bytes)",
        )
    if raw[:8] != KAMINO_RESERVE_ACCOUNT_DISCRIMINATOR:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.RESERVE_UNKNOWN_DISCRIMINATOR,
            "Reserve discriminator differs from pinned klend-sdk 13.0.2",
        )
    if owner != KLEND_PROGRAM_ID:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.RESERVE_OWNER_MISMATCH,
            "Reserve owner differs from the pinned klend program",
        )

    bsf_limbs = [
        _read_uint(
            raw,
            KAMINO_CUMULATIVE_BORROW_RATE_BSF_OFFSET + 8 * index,
            8,
            f"cumulativeBorrowRateBsf.value[{index}]",
        )
        for index in range(KLEND_BIG_FRACTION_LIMBS)
    ]

    stale = raw[KAMINO_LAST_UPDATE_STALE_OFFSET]
    if stale != 0:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.RESERVE_LAST_UPDATE_STALE,
            "LastUpdate.stale is nonzero; reserve interest state is stale",
        )
    status_raw = raw[KAMINO_CONFIG_STATUS_OFFSET]
    if status_raw != 0:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.RESERVE_CONFIG_STATUS_UNKNOWN,
            "ReserveConfig.status is nonzero; the offline pack cannot "
            "enumerate the status enum, so the state fails closed",
        )
    emergency_mode = raw[KAMINO_CONFIG_EMERGENCY_MODE_OFFSET]
    if emergency_mode != 0:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.RESERVE_EMERGENCY_MODE_NONZERO,
            "ReserveConfig.emergencyMode is nonzero; reserve state fails closed",
        )

    liquidity = KaminoReserveLiquidityState(
        mint=_read_pubkey(raw, KAMINO_LIQUIDITY_MINT_OFFSET, "liquidity.mint"),
        supply_vault=_read_pubkey(
            raw, KAMINO_LIQUIDITY_SUPPLY_VAULT_OFFSET, "liquidity.supplyVault"
        ),
        fee_vault=_read_pubkey(
            raw, KAMINO_LIQUIDITY_FEE_VAULT_OFFSET, "liquidity.feeVault"
        ),
        total_available_amount=_read_uint(
            raw, KAMINO_TOTAL_AVAILABLE_AMOUNT_OFFSET, 8, "totalAvailableAmount"
        ),
        borrowed_amount_sf=_read_uint(
            raw, KAMINO_BORROWED_AMOUNT_SF_OFFSET, 16, "borrowedAmountSf"
        ),
        market_price_sf=_read_uint(
            raw, KAMINO_MARKET_PRICE_SF_OFFSET, 16, "marketPriceSf"
        ),
        market_price_last_updated_ts=_read_uint(
            raw,
            KAMINO_MARKET_PRICE_LAST_UPDATED_TS_OFFSET,
            8,
            "marketPriceLastUpdatedTs",
        ),
        mint_decimals_raw=_read_uint(
            raw, KAMINO_MINT_DECIMALS_OFFSET, 8, "mintDecimals"
        ),
        deposit_limit_crossed_timestamp=_read_uint(
            raw,
            KAMINO_DEPOSIT_LIMIT_CROSSED_TS_OFFSET,
            8,
            "depositLimitCrossedTimestamp",
        ),
        borrow_limit_crossed_timestamp=_read_uint(
            raw,
            KAMINO_BORROW_LIMIT_CROSSED_TS_OFFSET,
            8,
            "borrowLimitCrossedTimestamp",
        ),
        cumulative_borrow_rate_bsf_limbs=(
            bsf_limbs[0],
            bsf_limbs[1],
            bsf_limbs[2],
            bsf_limbs[3],
        ),
        accumulated_protocol_fees_sf=_read_uint(
            raw,
            KAMINO_ACCUMULATED_PROTOCOL_FEES_SF_OFFSET,
            16,
            "accumulatedProtocolFeesSf",
        ),
        accumulated_referrer_fees_sf=_read_uint(
            raw,
            KAMINO_ACCUMULATED_REFERRER_FEES_SF_OFFSET,
            16,
            "accumulatedReferrerFeesSf",
        ),
        pending_referrer_fees_sf=_read_uint(
            raw,
            KAMINO_PENDING_REFERRER_FEES_SF_OFFSET,
            16,
            "pendingReferrerFeesSf",
        ),
        absolute_referral_rate_sf=_read_uint(
            raw,
            KAMINO_ABSOLUTE_REFERRAL_RATE_SF_OFFSET,
            16,
            "absoluteReferralRateSf",
        ),
        token_program=_read_pubkey(
            raw, KAMINO_LIQUIDITY_TOKEN_PROGRAM_OFFSET, "liquidity.tokenProgram"
        ),
        rewards_amount_available=_read_uint(
            raw, KAMINO_REWARDS_AMOUNT_AVAILABLE_OFFSET, 8, "rewardsAmountAvailable"
        ),
    )
    if liquidity.mint_decimals_raw > 255:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.CAPACITY_STATE_INVALID,
            "decoded mintDecimals exceeds the SPL token decimal range",
        )
    if liquidity.token_program not in SUPPORTED_KAMINO_TOKEN_PROGRAMS:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.VAULT_TOKEN_PROGRAM_MISMATCH,
            "liquidity.tokenProgram is not a pinned SPL token program",
        )

    last_update = KaminoLastUpdateState(
        slot=_read_uint(raw, KAMINO_LAST_UPDATE_SLOT_OFFSET, 8, "lastUpdate.slot"),
        stale=stale,
        price_status=raw[KAMINO_LAST_UPDATE_PRICE_STATUS_OFFSET],
        timestamp=_read_uint(
            raw, KAMINO_LAST_UPDATE_TIMESTAMP_OFFSET, 4, "lastUpdate.timestamp"
        ),
    )
    collateral = KaminoReserveCollateralState(
        mint=_read_pubkey(raw, KAMINO_COLLATERAL_MINT_OFFSET, "collateral.mint"),
        mint_total_supply=_read_uint(
            raw,
            KAMINO_COLLATERAL_MINT_TOTAL_SUPPLY_OFFSET,
            8,
            "collateral.mintTotalSupply",
        ),
        supply_vault=_read_pubkey(
            raw, KAMINO_COLLATERAL_SUPPLY_VAULT_OFFSET, "collateral.supplyVault"
        ),
    )
    config = KaminoReserveConfigPinnedState(
        status_raw=status_raw,
        emergency_mode=emergency_mode,
        padding_deprecated_asset_tier=raw[
            KAMINO_CONFIG_PADDING_DEPRECATED_ASSET_TIER_OFFSET
        ],
        host_fixed_interest_rate_bps=_read_uint(
            raw,
            KAMINO_CONFIG_HOST_FIXED_INTEREST_RATE_BPS_OFFSET,
            2,
            "hostFixedInterestRateBps",
        ),
        min_deleveraging_bonus_bps=_read_uint(
            raw,
            KAMINO_CONFIG_MIN_DELEVERAGING_BONUS_BPS_OFFSET,
            2,
            "minDeleveragingBonusBps",
        ),
        block_ctoken_usage=raw[KAMINO_CONFIG_BLOCK_CTOKEN_USAGE_OFFSET],
        early_repay_remaining_interest_pct=raw[
            KAMINO_CONFIG_EARLY_REPAY_REMAINING_INTEREST_PCT_OFFSET
        ],
        interest_rate_basis=raw[KAMINO_CONFIG_INTEREST_RATE_BASIS_OFFSET],
        reserved1=(
            raw[KAMINO_CONFIG_RESERVED1_OFFSET],
            raw[KAMINO_CONFIG_RESERVED1_OFFSET + 1],
            raw[KAMINO_CONFIG_RESERVED1_OFFSET + 2],
        ),
        protocol_order_execution_fee_pct=raw[
            KAMINO_CONFIG_PROTOCOL_ORDER_EXECUTION_FEE_PCT_OFFSET
        ],
        protocol_take_rate_pct=raw[KAMINO_CONFIG_PROTOCOL_TAKE_RATE_PCT_OFFSET],
        protocol_liquidation_fee_pct=raw[
            KAMINO_CONFIG_PROTOCOL_LIQUIDATION_FEE_PCT_OFFSET
        ],
        loan_to_value_pct=raw[KAMINO_CONFIG_LOAN_TO_VALUE_PCT_OFFSET],
        liquidation_threshold_pct=raw[KAMINO_CONFIG_LIQUIDATION_THRESHOLD_PCT_OFFSET],
        min_liquidation_bonus_bps=_read_uint(
            raw,
            KAMINO_CONFIG_MIN_LIQUIDATION_BONUS_BPS_OFFSET,
            2,
            "minLiquidationBonusBps",
        ),
        max_liquidation_bonus_bps=_read_uint(
            raw,
            KAMINO_CONFIG_MAX_LIQUIDATION_BONUS_BPS_OFFSET,
            2,
            "maxLiquidationBonusBps",
        ),
        bad_debt_liquidation_bonus_bps=_read_uint(
            raw,
            KAMINO_CONFIG_BAD_DEBT_LIQUIDATION_BONUS_BPS_OFFSET,
            2,
            "badDebtLiquidationBonusBps",
        ),
        deleveraging_margin_call_period_secs=_read_uint(
            raw,
            KAMINO_CONFIG_DELEVERAGING_MARGIN_CALL_PERIOD_SECS_OFFSET,
            8,
            "deleveragingMarginCallPeriodSecs",
        ),
        deleveraging_threshold_decrease_bps_per_day=_read_uint(
            raw,
            KAMINO_CONFIG_DELEVERAGING_THRESHOLD_DECREASE_BPS_PER_DAY_OFFSET,
            8,
            "deleveragingThresholdDecreaseBpsPerDay",
        ),
        origination_fee_sf=_read_uint(
            raw,
            KAMINO_CONFIG_FEES_ORIGINATION_FEE_SF_OFFSET,
            8,
            "fees.originationFeeSf",
        ),
        flash_loan_fee_sf=_read_uint(
            raw,
            KAMINO_CONFIG_FEES_FLASH_LOAN_FEE_SF_OFFSET,
            8,
            "fees.flashLoanFeeSf",
        ),
    )

    decoded_market = _read_pubkey(raw, KAMINO_LENDING_MARKET_OFFSET, "lendingMarket")
    if decoded_market != lending_market:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.RESERVE_MARKET_BINDING_MISMATCH,
            "decoded lendingMarket differs from the reviewed market address",
        )
    if liquidity.mint == _ZERO_PUBKEY:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.RESERVE_ZERO_MINT,
            "decoded liquidity.mint is zero; reserve is not initialized",
        )

    tail = raw[KAMINO_RESERVE_PINNED_PREFIX_LEN:]
    return KaminoReserveState(
        version_raw=_read_uint(raw, KAMINO_RESERVE_VERSION_OFFSET, 8, "version"),
        last_update=last_update,
        lending_market=decoded_market,
        farm_collateral=_read_pubkey(
            raw, KAMINO_FARM_COLLATERAL_OFFSET, "farmCollateral"
        ),
        farm_debt=_read_pubkey(raw, KAMINO_FARM_DEBT_OFFSET, "farmDebt"),
        liquidity=liquidity,
        collateral=collateral,
        config=config,
        unpinned_tail_len=len(tail),
        unpinned_tail_sha256=hashlib.sha256(tail).hexdigest(),
    )


def kamino_flash_loan_fee_rational(flash_loan_fee_sf_raw: int) -> Fraction:
    """Exact rational flash fee from the decoded ``fees.flashLoanFeeSf``.

    The pinned ``Fraction`` scale is 2^60 (fraction.ts: FRACTIONS = 60), so
    the exact fee factor is ``raw / 2**60`` as a rational; no float, no
    invented ceil/floor rule. The deployed transfer-rounding rule stays
    unpinned and is surfaced as the ``FEE_ROUNDING_RULE_UNPINNED`` gap.
    """

    if type(flash_loan_fee_sf_raw) is not int or flash_loan_fee_sf_raw < 0:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.CAPACITY_STATE_INVALID,
            "flashLoanFeeSf raw value must be a non-negative integer",
        )
    return Fraction(flash_loan_fee_sf_raw, KLEND_ONE_SF)


@dataclass(frozen=True, slots=True)
class KaminoVaultTokenAccountState:
    """Exact 165-byte SPL token account decode of a klend reserve vault."""

    address: Pubkey
    owner_program: Pubkey
    mint: Pubkey
    authority: Pubkey
    amount: int
    account_state: int
    is_native: bool
    delegated_amount: int
    role: str
    delegate: Pubkey | None = None
    close_authority: Pubkey | None = None


def decode_kamino_vault_token_account(
    data: bytes,
    *,
    address: Pubkey,
    owner_program: Pubkey,
    expected_mint: Pubkey,
    expected_token_program: Pubkey,
    role: str,
) -> KaminoVaultTokenAccountState:
    """Fail-closed decode of a klend reserve supply/fee vault token account.

    The vault owner program must be exactly the token program pinned inside
    the reserve liquidity block, the mint must bind the reserve mint, and
    delegation, close authority, frozen or unknown account states fail closed
    because they can silently change which party may move reserve resources.
    """

    if role not in ("supply", "fee"):
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.CAPACITY_STATE_INVALID,
            "vault role must be 'supply' or 'fee'",
        )
    raw = bytes(data)
    if len(raw) != KAMINO_SPL_TOKEN_ACCOUNT_LEN:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.VAULT_LAYOUT_MISMATCH,
            "vault token account length differs from the 165-byte SPL layout",
        )
    if expected_token_program not in SUPPORTED_KAMINO_TOKEN_PROGRAMS:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.VAULT_TOKEN_PROGRAM_MISMATCH,
            "reserve-pinned token program is not a supported SPL token program",
        )
    if owner_program != expected_token_program:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.VAULT_TOKEN_PROGRAM_MISMATCH,
            "vault owner program differs from the reserve-pinned token program",
        )
    mint = Pubkey.from_bytes(raw[0:32])
    if mint != expected_mint:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.VAULT_MINT_BINDING_MISMATCH,
            f"vault token account mint differs from the reserve {role} mint",
        )
    delegate_tag = int.from_bytes(raw[72:76], "little")
    if delegate_tag != 0:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.VAULT_DELEGATE_UNPROVEN,
            "vault carries an unproven delegate authority",
        )
    account_state = raw[108]
    if account_state == 2:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.VAULT_FROZEN,
            f"{role} vault token account is frozen",
        )
    if account_state != 1:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.VAULT_ACCOUNT_STATE_UNKNOWN,
            f"{role} vault token account state is unknown",
        )
    is_native_tag = int.from_bytes(raw[109:113], "little")
    close_tag = int.from_bytes(raw[129:133], "little")
    if close_tag != 0:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.VAULT_CLOSE_AUTHORITY_UNPROVEN,
            "vault carries an unproven close authority",
        )
    return KaminoVaultTokenAccountState(
        address=address,
        owner_program=owner_program,
        mint=mint,
        authority=Pubkey.from_bytes(raw[32:64]),
        amount=int.from_bytes(raw[64:72], "little"),
        account_state=account_state,
        is_native=is_native_tag != 0,
        delegated_amount=int.from_bytes(raw[121:129], "little"),
        role=role,
        delegate=None,
        close_authority=None,
    )


@dataclass(frozen=True, slots=True)
class KaminoReserveCapacityObservation:
    """Typed read-only capacity observation for one klend reserve resource.

    Every ``raw_*`` amount is proven from decoded account bytes only.
    ``effective_capacity_base_units`` stays ``None`` while the derivation is
    UNPROVEN: unknown is not zero, and no ceil/floor fee rounding is invented.
    """

    mint: str
    reserve_address: str
    reserve_owner: str
    lending_market: str
    state: KaminoReserveState
    supply_vault: KaminoVaultTokenAccountState
    fee_vault: KaminoVaultTokenAccountState | None
    reserve_data_sha256: str
    supply_vault_data_sha256: str
    fee_vault_data_sha256: str | None
    raw_total_available_amount: int
    raw_borrowed_amount_sf: int
    raw_supply_vault_amount: int
    raw_fee_vault_amount: int | None
    flash_loan_fee_sf_raw: int
    flash_loan_fee_rational: Fraction
    mint_decimals: int
    capacity_derivation: KaminoCapacityDerivation
    effective_capacity_base_units: int | None
    constraint_gaps: tuple[str, ...]
    blockers: tuple[str, ...]
    slot: int | None = None
    slot_rooted: bool = False
    slot_provenance: str = KaminoSlotProvenance.OFFLINE_FIXTURE_NOT_ROOTED.value
    fee_rounding: str = "UNPINNED"
    decoder_identity: str = READER_DECODER_IDENTITY
    decoder_generation: int = READER_DECODER_GENERATION
    execution_authority: str = READER_EXECUTION_AUTHORITY
    sign_enabled: bool = False
    send_enabled: bool = False

    def __post_init__(self) -> None:
        for name in ("mint", "reserve_address", "reserve_owner", "lending_market"):
            value = getattr(self, name)
            try:
                Pubkey.from_string(value)
            except Exception as exc:
                raise ValueError(f"{name} is not a base58 pubkey") from exc
        for name in ("reserve_data_sha256", "supply_vault_data_sha256"):
            if not _SHA256_RE.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a lowercase sha256 digest")
        if self.fee_vault_data_sha256 is not None and not _SHA256_RE.fullmatch(
            self.fee_vault_data_sha256
        ):
            raise ValueError("fee_vault_data_sha256 must be a sha256 digest or None")
        for name in (
            "raw_total_available_amount",
            "raw_borrowed_amount_sf",
            "raw_supply_vault_amount",
            "flash_loan_fee_sf_raw",
        ):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer")
        if type(self.mint_decimals) is not int or not 0 <= self.mint_decimals <= 255:
            raise ValueError("mint_decimals must be an integer in [0, 255]")
        if self.flash_loan_fee_rational != Fraction(
            self.flash_loan_fee_sf_raw, KLEND_ONE_SF
        ):
            raise ValueError(
                "flash_loan_fee_rational must equal raw/2^60 exactly (no rounding)"
            )
        if self.fee_rounding != "UNPINNED":
            raise ValueError("offline reader must never claim a rounding rule")
        if self.capacity_derivation is KaminoCapacityDerivation.UNPROVEN:
            if self.effective_capacity_base_units is not None:
                raise ValueError(
                    "effective capacity without proven derivation is forbidden; "
                    "unknown is not zero"
                )
            if KaminoCapacityRejectionCode.MISSING_EFFECTIVE_FLASH_CAP.value not in (
                self.blockers
            ):
                raise ValueError(
                    "unproven capacity must carry MISSING_EFFECTIVE_FLASH_CAP"
                )
            if not self.constraint_gaps:
                raise ValueError("unproven capacity must enumerate constraint gaps")
        if not self.slot_rooted:
            if self.slot is not None:
                raise ValueError("unrooted observation cannot claim a slot")
            if (
                self.slot_provenance
                != KaminoSlotProvenance.OFFLINE_FIXTURE_NOT_ROOTED.value
            ):
                raise ValueError("unrooted observation must use offline provenance")
            if (
                KaminoCapacityRejectionCode.LIVE_ROOTED_RPC_NOT_AUTHORIZED.value
                not in self.blockers
            ):
                raise ValueError(
                    "unrooted observation must carry LIVE_ROOTED_RPC_NOT_AUTHORIZED"
                )
        else:
            if (
                self.slot is None
                or type(self.slot) is not int
                or self.slot < 0
                or self.slot_provenance != KaminoSlotProvenance.LIVE_ROOTED_RPC.value
            ):
                raise ValueError("rooted observation requires an integer rooted slot")
        if self.status not in ("PARTIAL_DECODED", "BLOCKED_LIVE_STATE"):
            raise ValueError("unknown observation status")

    @property
    def status(self) -> str:
        return "BLOCKED_LIVE_STATE" if self.blockers else "PARTIAL_DECODED"

    @property
    def last_update(self) -> KaminoLastUpdateState:
        return self.state.last_update

    @property
    def evidence_digest(self) -> str:
        return hashlib.sha256(
            _kamino_reader_canonical_json(self).encode("utf-8")
        ).hexdigest()

    def evidence_record(self) -> dict[str, Any]:
        return {
            "decoder_identity": self.decoder_identity,
            "decoder_generation": self.decoder_generation,
            "evidence_sha256": self.evidence_digest,
            "status": self.status,
            "execution_authority": self.execution_authority,
            "sign_enabled": self.sign_enabled,
            "send_enabled": self.send_enabled,
            "flash_instruction_pair": {
                "borrow": KAMINO_FLASH_BORROW_INSTRUCTION_NAME,
                "repay": KAMINO_FLASH_REPAY_INSTRUCTION_NAME,
                "repay_carries_borrow_instruction_index_u8": (
                    KAMINO_FLASH_REPAY_CARRIES_BORROW_INSTRUCTION_INDEX_U8
                ),
                "obligation_account_required": (
                    KAMINO_FLASH_IX_OBLIGATION_ACCOUNT_REQUIRED
                ),
            },
            "observation": json.loads(_kamino_reader_canonical_json(self)),
        }


def _kamino_reader_canonical_json(value: object) -> str:
    def normalize(node: object) -> object:
        if is_dataclass(node) and not isinstance(node, type):
            return {
                field.name: normalize(getattr(node, field.name))
                for field in dataclass_fields(node)
            }
        if isinstance(node, Pubkey):
            return str(node)
        if isinstance(node, StrEnum):
            return str(node.value)
        if isinstance(node, Fraction):
            return {"numerator": node.numerator, "denominator": node.denominator}
        if isinstance(node, (tuple, list)):
            return [normalize(item) for item in node]
        if isinstance(node, dict):
            return {key: normalize(item) for key, item in node.items()}
        return node

    return json.dumps(
        normalize(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def observe_kamino_reserve_capacity(
    *,
    reserve_bytes: bytes,
    reserve_owner: Pubkey,
    reserve_address: Pubkey,
    lending_market: Pubkey,
    supply_vault_bytes: bytes,
    supply_vault_address: Pubkey,
    supply_vault_owner_program: Pubkey,
    fee_vault_bytes: bytes | None = None,
    fee_vault_address: Pubkey | None = None,
    fee_vault_owner_program: Pubkey | None = None,
    reviewed_mint: Pubkey | None = None,
) -> KaminoReserveCapacityObservation:
    """Decode reserve + vaults offline and return typed capacity evidence.

    Every input is caller-supplied (offline fixture or, in a later authorized
    wave, a live rooted read). No network, no signing, no account creation, no
    Obligation. Effective flash borrow capacity is never derived offline.
    """

    state = decode_kamino_reserve(
        reserve_bytes, owner=reserve_owner, lending_market=lending_market
    )
    gaps = set(KAMINO_UNPINNED_CAPACITY_GAPS)
    if reviewed_mint is not None:
        if state.liquidity.mint != reviewed_mint:
            raise KaminoCapacityReaderError(
                KaminoCapacityRejectionCode.RESERVE_MINT_BINDING_MISMATCH,
                "reviewed mint differs from the decoded liquidity.mint",
            )
    else:
        gaps.add("REVIEWED_MINT_BINDING_ABSENT")
    if state.collateral.mint != state.liquidity.mint:
        gaps.add("COLLATERAL_MINT_MISMATCH")
    if state.collateral.supply_vault != state.liquidity.supply_vault:
        gaps.add("COLLATERAL_VAULT_MISMATCH")

    if supply_vault_address != state.liquidity.supply_vault:
        raise KaminoCapacityReaderError(
            KaminoCapacityRejectionCode.VAULT_ADDRESS_BINDING_MISMATCH,
            "observed supply vault address differs from the decoded "
            "liquidity.supplyVault",
        )
    supply_vault = decode_kamino_vault_token_account(
        supply_vault_bytes,
        address=supply_vault_address,
        owner_program=supply_vault_owner_program,
        expected_mint=state.liquidity.mint,
        expected_token_program=state.liquidity.token_program,
        role="supply",
    )

    fee_vault: KaminoVaultTokenAccountState | None = None
    fee_vault_data_sha256: str | None = None
    raw_fee_vault_amount: int | None = None
    if fee_vault_bytes is not None:
        if fee_vault_address is None or fee_vault_owner_program is None:
            raise KaminoCapacityReaderError(
                KaminoCapacityRejectionCode.CAPACITY_STATE_INVALID,
                "fee vault bytes require the fee vault address and owner program",
            )
        if fee_vault_address != state.liquidity.fee_vault:
            raise KaminoCapacityReaderError(
                KaminoCapacityRejectionCode.VAULT_ADDRESS_BINDING_MISMATCH,
                "observed fee vault address differs from the decoded "
                "liquidity.feeVault",
            )
        fee_vault = decode_kamino_vault_token_account(
            fee_vault_bytes,
            address=fee_vault_address,
            owner_program=fee_vault_owner_program,
            expected_mint=state.liquidity.mint,
            expected_token_program=state.liquidity.token_program,
            role="fee",
        )
        fee_vault_data_sha256 = hashlib.sha256(bytes(fee_vault_bytes)).hexdigest()
        raw_fee_vault_amount = fee_vault.amount

    blockers = (
        KaminoCapacityRejectionCode.MISSING_EFFECTIVE_FLASH_CAP.value,
        KaminoCapacityRejectionCode.LIVE_ROOTED_RPC_NOT_AUTHORIZED.value,
    )
    return KaminoReserveCapacityObservation(
        mint=str(state.liquidity.mint),
        reserve_address=str(reserve_address),
        reserve_owner=str(reserve_owner),
        lending_market=str(lending_market),
        state=state,
        supply_vault=supply_vault,
        fee_vault=fee_vault,
        reserve_data_sha256=hashlib.sha256(bytes(reserve_bytes)).hexdigest(),
        supply_vault_data_sha256=hashlib.sha256(bytes(supply_vault_bytes)).hexdigest(),
        fee_vault_data_sha256=fee_vault_data_sha256,
        raw_total_available_amount=state.liquidity.total_available_amount,
        raw_borrowed_amount_sf=state.liquidity.borrowed_amount_sf,
        raw_supply_vault_amount=supply_vault.amount,
        raw_fee_vault_amount=raw_fee_vault_amount,
        flash_loan_fee_sf_raw=state.config.flash_loan_fee_sf,
        flash_loan_fee_rational=kamino_flash_loan_fee_rational(
            state.config.flash_loan_fee_sf
        ),
        mint_decimals=state.liquidity.mint_decimals_raw,
        capacity_derivation=KaminoCapacityDerivation.UNPROVEN,
        effective_capacity_base_units=None,
        constraint_gaps=tuple(sorted(gaps)),
        blockers=blockers,
    )


@dataclass(frozen=True, slots=True)
class KaminoCapitalEdgeGate:
    """Capacity-edge emission verdict; ``edge`` is None until fully proven."""

    edge: None
    blocker: str
    blockers: tuple[str, ...]
    note: str


def kamino_reserve_capital_edge_gate(
    observation: KaminoReserveCapacityObservation,
) -> KaminoCapitalEdgeGate:
    """Gate edge emission behind rooted-RPC proof and the frozen graph owner.

    Offline fixture evidence never qualifies a FlashCapitalEdge. The
    FlashCapitalGraph owner is frozen this wave, and full evidence plus
    independent quorum is required before any narrow kamino allowance.
    """

    if (
        KaminoCapacityRejectionCode.LIVE_ROOTED_RPC_NOT_AUTHORIZED.value
        in observation.blockers
    ):
        return KaminoCapitalEdgeGate(
            edge=None,
            blocker=KaminoCapacityRejectionCode.LIVE_ROOTED_RPC_NOT_AUTHORIZED.value,
            blockers=observation.blockers,
            note=(
                "no live rooted-RPC snapshot with independent quorum was "
                "authorized; offline fixture evidence never qualifies an edge"
            ),
        )
    if observation.effective_capacity_base_units is None:
        return KaminoCapitalEdgeGate(
            edge=None,
            blocker=KaminoCapacityRejectionCode.MISSING_EFFECTIVE_FLASH_CAP.value,
            blockers=observation.blockers,
            note="effective flash borrow cap is unknown, not zero",
        )
    return KaminoCapitalEdgeGate(
        edge=None,
        blocker=KaminoCapacityRejectionCode.GRAPH_ALLOWANCE_PENDING.value,
        blockers=observation.blockers,
        note=(
            "FlashCapitalGraph provider allowance for kamino requires full "
            "evidence and independent quorum; graph owner is frozen"
        ),
    )


def build_kamino_capital_reader_result(
    observation: KaminoReserveCapacityObservation,
    *,
    observed_at: float,
    generation: str,
) -> tuple[dict[str, Any], "Evidence"]:
    """Type the observation into the existing KaminoCapitalProvider port.

    The frozen FlashCapitalGraph consumes readers via
    ``KaminoCapitalProvider(reader, assets)`` where ``reader`` returns a
    ``(payload, Evidence)`` pair. Offline, no asset row is ever qualified
    (``assets`` is empty) and the evidence carries the typed blocker as its
    negative reason, so ``discover_assets()`` records negative evidence and
    emits zero edges. graph.py is not modified by this reader.
    """

    from src.assets.resolution.evidence import Evidence

    blockers = list(observation.blockers)
    payload = {
        "schema": "dynamic-universe.capital.v1",
        "provider": "kamino",
        "assets": [],
        "blockers": blockers,
        "constraint_gaps": list(observation.constraint_gaps),
        "evidence_digest": observation.evidence_digest,
        "decoder_identity": observation.decoder_identity,
        "decoder_generation": observation.decoder_generation,
        "execution_authority": observation.execution_authority,
    }
    negative_reason = (
        KaminoCapacityRejectionCode.LIVE_ROOTED_RPC_NOT_AUTHORIZED.value
        if KaminoCapacityRejectionCode.LIVE_ROOTED_RPC_NOT_AUTHORIZED.value in blockers
        else "+".join(blockers)
    )
    request_hash = hashlib.sha256(
        _kamino_reader_canonical_json(
            {
                "decoder_identity": observation.decoder_identity,
                "reserve_address": observation.reserve_address,
                "mint": observation.mint,
                "constraint_gaps": observation.constraint_gaps,
            }
        ).encode("utf-8")
    ).hexdigest()
    evidence = Evidence(
        source="kamino-capacity-reader",
        provider="kamino",
        correlation_group="flash-capital",
        generation=generation,
        observed_at=observed_at,
        response_hash=observation.evidence_digest,
        request_hash=request_hash,
        slot_or_checkpoint=None,
        negative_reason=negative_reason,
    )
    return payload, evidence
