"""Kamino lending/liquidation promotion contracts for PR-050.

The module is deliberately sender-free. It models only verified deployment
provenance, supported asset/market combinations, fixture decoding, integer
health/profitability math, and a shadow planner decision. A missing or
unverified registry fails closed instead of falling back to guessed Kamino
programs, reserves, or oracle layouts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
import json
import re
import struct
from typing import Any, Mapping
from urllib.parse import urlparse

from src.config.chain_registry import ChainRegistryError, validate_pubkey

KAMINO_REGISTRY_SCHEMA = "pr050.kamino-supported-combinations.v1"
KAMINO_RESERVE_FIXTURE_DISCRIMINATOR = b"KAMRESV1"
_RESERVE_FIXTURE_FORMAT = "<8sQQQHHHH"
_HEX_64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_OFFICIAL_HOSTS = {"kamino.com", "docs.kamino.finance", "github.com"}


class KaminoRegistryError(ValueError):
    """Raised when Kamino protocol evidence is missing or malformed."""


def _require_non_empty(value: str, *, field: str) -> str:
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


def _require_pubkey(value: str, *, field: str) -> str:
    try:
        return validate_pubkey(value, field=field)
    except ChainRegistryError as exc:
        raise KaminoRegistryError(str(exc)) from exc


def _require_mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise KaminoRegistryError(f"{field} must be an object")
    return value


def _tuple_of_strings(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise KaminoRegistryError(f"{field} must be a list")
    result = tuple(_require_non_empty(str(item), field=field) for item in value)
    if len(result) != len(set(result)):
        raise KaminoRegistryError(f"{field} must not contain duplicates")
    return result


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
                str(payload.get("source_url", "")),
                field="source_url",
            ),
            sdk_package=_require_non_empty(
                str(payload.get("sdk_package", "")),
                field="sdk_package",
            ),
            lending_program_id=_require_pubkey(
                str(payload.get("lending_program_id", "")),
                field="provenance.lending_program_id",
            ),
            idl_sha256=_require_non_empty(
                str(payload.get("idl_sha256", "")),
                field="idl_sha256",
            ),
            rpc_fixture_sha256=_require_non_empty(
                str(payload.get("rpc_fixture_sha256", "")),
                field="rpc_fixture_sha256",
            ),
            deployment_slot=_require_int(
                payload.get("deployment_slot"),
                field="deployment_slot",
            ),
            reviewed_at=_require_non_empty(
                str(payload.get("reviewed_at", "")),
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
        _require_pubkey(self.lending_program_id, field="provenance.lending_program_id")
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
        provenance = KaminoDeploymentProvenance.from_mapping(
            _require_mapping(payload.get("provenance"), field="provenance")
        )
        return cls(
            combination_id=_require_non_empty(
                str(payload.get("combination_id", "")),
                field="combination_id",
            ),
            cluster=_require_non_empty(
                str(payload.get("cluster", "")),
                field="cluster",
            ),
            lending_program_id=_require_pubkey(
                str(payload.get("lending_program_id", "")),
                field="lending_program_id",
            ),
            market_address=_require_pubkey(
                str(payload.get("market_address", "")),
                field="market_address",
            ),
            collateral_mint=_require_pubkey(
                str(payload.get("collateral_mint", "")),
                field="collateral_mint",
            ),
            debt_mint=_require_pubkey(
                str(payload.get("debt_mint", "")),
                field="debt_mint",
            ),
            collateral_reserve=_require_pubkey(
                str(payload.get("collateral_reserve", "")),
                field="collateral_reserve",
            ),
            debt_reserve=_require_pubkey(
                str(payload.get("debt_reserve", "")),
                field="debt_reserve",
            ),
            collateral_oracle=_require_pubkey(
                str(payload.get("collateral_oracle", "")),
                field="collateral_oracle",
            ),
            debt_oracle=_require_pubkey(
                str(payload.get("debt_oracle", "")),
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
            writable_accounts=tuple(
                _require_pubkey(account, field="writable_accounts")
                for account in _tuple_of_strings(
                    payload.get("writable_accounts"),
                    field="writable_accounts",
                )
            ),
            provenance=provenance,
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
            KaminoSupportedCombination.from_mapping(item) for item in raw_combinations
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

    protocol_fee = (candidate.max_repay_lamports * combination.protocol_fee_bps) // 10_000
    flash_fee = (candidate.max_repay_lamports * combination.flash_loan_fee_bps) // 10_000
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
    return KaminoSupportedRegistry.from_mapping(_require_mapping(payload, field="registry"))
