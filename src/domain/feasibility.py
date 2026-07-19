"""Canonical PR-010 trade feasibility, cost, capital, and sizing engine."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
import hashlib, json, threading
from typing import Callable, Iterable, Optional, Protocol

from .money import (
    ComputeBudget, ComputeUnitPrice, FeeComponentKind, Lamports, MonetaryUnitError,
    NATIVE_SOL_MINT, RoundingMode, TOKEN_2022_PROGRAM, TOKEN_PROGRAM, TokenAmount,
    WSOL_MINT, _ceil_div,
)


class FeasibilityReason(str, Enum):
    FEASIBLE_FOR_SIMULATION = "feasible_for_simulation"
    INVALID_UNITS = "invalid_units"
    MISSING_CONFIGURATION = "missing_configuration"
    STALE_WALLET_STATE = "stale_wallet_state"
    MISSING_WALLET_BALANCE = "missing_wallet_balance"
    MISSING_PROTECTED_RESERVE = "missing_protected_reserve"
    UNKNOWN_OUTSTANDING_BUDGET = "unknown_outstanding_budget"
    INSUFFICIENT_OPERATIONAL_SOL = "insufficient_operational_sol"
    MISSING_BASE_FEE = "missing_base_fee"
    MISSING_PRIORITY_FEE = "missing_priority_fee"
    PRIORITY_FEE_CAP_EXCEEDED = "priority_fee_cap_exceeded"
    MISSING_OR_STALE_TIP = "missing_or_stale_tip"
    TIP_CAP_EXCEEDED = "tip_cap_exceeded"
    MISSING_RENT_ESTIMATE = "missing_rent_estimate"
    ATA_ACCOUNT_INVALID = "ata_account_invalid"
    MISSING_OR_STALE_CONVERSION = "missing_or_stale_conversion"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_CAPACITY_EXCEEDED = "provider_capacity_exceeded"
    ROUTE_STALE = "route_stale"
    ROUTE_CAPACITY_EXCEEDED = "route_capacity_exceeded"
    ROUTE_NOT_COMPOSABLE = "route_not_composable"
    REPAYMENT_NOT_GUARANTEED = "repayment_not_guaranteed"
    TRANSACTION_TOO_LARGE = "transaction_too_large"
    ACCOUNT_LIMIT_EXCEEDED = "account_limit_exceeded"
    COMPUTE_LIMIT_EXCEEDED = "compute_limit_exceeded"
    BELOW_MIN_NET_PROFIT = "below_min_net_profit"
    BELOW_MIN_ROI = "below_min_roi"
    SIMULATION_REQUIRED = "simulation_required"
    RESERVATION_CONFLICT = "reservation_conflict"


PRIMARY_REASON_PRIORITY = tuple(r for r in FeasibilityReason if r is not FeasibilityReason.FEASIBLE_FOR_SIMULATION)


@dataclass(frozen=True)
class RationalConversionSnapshot:
    base_mint: str
    base_decimals: int
    quote_mint: str
    quote_decimals: int
    numerator: int
    denominator: int
    source: str
    observed_at: datetime
    source_slot: Optional[int]
    healthy: bool = True

    def __post_init__(self):
        if self.numerator <= 0 or self.denominator <= 0:
            raise MonetaryUnitError("conversion ratio must be positive")
        if self.base_decimals < 0 or self.quote_decimals < 0:
            raise MonetaryUnitError("conversion decimals must be known")

    def validate(self, *, now: datetime, max_age: timedelta, max_future_skew: timedelta = timedelta(seconds=1), require_slot: bool = False) -> None:
        if not self.healthy:
            raise TimeoutError("conversion source unhealthy")
        if require_slot and self.source_slot is None:
            raise TimeoutError("conversion slot unknown")
        if self.observed_at - now > max_future_skew:
            raise TimeoutError("conversion timestamp is in the future")
        if now - self.observed_at > max_age:
            raise TimeoutError("conversion is stale")

    def _convert(self, amount: TokenAmount, rounding: RoundingMode) -> TokenAmount:
        if amount.mint == self.quote_mint and amount.decimals == self.quote_decimals:
            return amount
        if amount.mint != self.base_mint or amount.decimals != self.base_decimals:
            raise MonetaryUnitError("conversion direction mismatch")
        raw = amount.base_units * self.numerator
        out = _ceil_div(raw, self.denominator) if rounding is RoundingMode.ROUND_UP else raw // self.denominator
        return TokenAmount(self.quote_mint, out, self.quote_decimals)

    def convert_cost_up(self, amount: TokenAmount) -> TokenAmount:
        return self._convert(amount, RoundingMode.ROUND_UP)

    def convert_revenue_down(self, amount: TokenAmount) -> TokenAmount:
        return self._convert(amount, RoundingMode.ROUND_DOWN)

    def reciprocal(self) -> "RationalConversionSnapshot":
        return RationalConversionSnapshot(self.quote_mint, self.quote_decimals, self.base_mint, self.base_decimals, self.denominator, self.numerator, f"{self.source}:reciprocal", self.observed_at, self.source_slot, self.healthy)


@dataclass(frozen=True)
class WalletReservePolicy:
    protected_reserve: Optional[Lamports]
    max_additional_failed_attempts: int
    failed_attempt_charge_cap: Lamports
    configuration_version: str
    daily_failure_cost_cap: Optional[Lamports] = None


@dataclass(frozen=True)
class WalletResourceSnapshot:
    wallet_balance: Optional[Lamports]
    observed_at: datetime
    observed_slot: Optional[int]
    outstanding_reserved: Optional[Lamports]
    reservation_ids: tuple[str, ...] = ()
    healthy: bool = True


@dataclass(frozen=True)
class TipQuoteSnapshot:
    lamports: Lamports
    source: str
    observed_at: datetime
    submission_mode: str = "rpc"
    floor_lamports: Lamports = Lamports(0)
    instruction_hash: Optional[str] = None


@dataclass(frozen=True)
class AccountRequirement:
    derived_address: str
    wallet_owner: str
    mint: str
    token_program: str
    expected_data_size: Optional[int]
    exists: bool
    validated_owner: bool
    validated_mint: bool
    validated_token_program: bool
    rent_exemption: Optional[Lamports]
    close_refund: Optional[Lamports]
    observed_at: datetime
    observed_slot: Optional[int]

    def new_rent_lamports(self) -> Lamports:
        if self.exists:
            if not (self.validated_owner and self.validated_mint and self.validated_token_program):
                raise PermissionError("ATA/account exists but owner/mint/program validation failed")
            return Lamports(0)
        if self.expected_data_size is None or self.rent_exemption is None:
            raise LookupError("missing rent estimate")
        return self.rent_exemption


@dataclass(frozen=True)
class NativeCostEstimate:
    base_fee: Optional[Lamports]
    expected_message_hash: str
    fee_message_hash: Optional[str]
    signature_count: int
    cu_limit: int
    cu_price: Optional[ComputeUnitPrice]
    priority_fee_cap: Lamports
    tip: TipQuoteSnapshot
    account_requirements: tuple[AccountRequirement, ...] = ()
    temporary_wsol_rent: Lamports = Lamports(0)
    temporary_wsol_funding: Lamports = Lamports(0)
    other_native_debit: Lamports = Lamports(0)
    failed_attempt_charge_cap: Optional[Lamports] = None
    compiler_tip_instruction_hash: Optional[str] = None

    def priority_fee(self) -> Lamports:
        if self.cu_price is None:
            raise LookupError("missing priority fee")
        return ComputeBudget(self.cu_limit, self.cu_price).priority_fee()

    def account_rent(self) -> Lamports:
        total = 0
        for req in self.account_requirements:
            total += req.new_rent_lamports().value
        return Lamports(total)


@dataclass(frozen=True)
class ProviderCapacity:
    provider: str
    bank: str
    asset_mint: str
    min_borrow: TokenAmount
    max_borrow: TokenAmount
    available_liquidity: TokenAmount
    borrow_allowed: bool
    exact_repayment: Optional[TokenAmount]
    observed_at: datetime
    observed_slot: Optional[int]
    version: str
    healthy: bool = True


@dataclass(frozen=True)
class RouteCapacity:
    settlement_asset: str
    input_asset: str
    output_asset: str
    proposed_principal: TokenAmount
    expected_final_output: TokenAmount
    guaranteed_min_final_output: TokenAmount
    non_embedded_token_costs: tuple[TokenAmount, ...] = ()
    embedded_fee_metadata: tuple[str, ...] = ()
    price_impact_bps: int = 0
    min_executable_input: Optional[TokenAmount] = None
    max_executable_input: Optional[TokenAmount] = None
    quote_id_hash: str = ""
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    composable: bool = True
    complete_legs: bool = True
    healthy: bool = True


@dataclass(frozen=True)
class TransactionFeasibility:
    wire_size: int
    wire_size_limit: int
    required_signatures: int
    static_accounts: int
    lookup_accounts: int
    total_accounts: int
    account_limit: int
    alts_resolved: bool
    alts_fresh: bool
    estimated_cu: Optional[int]
    chosen_cu_limit: int
    cu_limit_cap: int
    diagnostics: tuple[str, ...] = ()
    complete: bool = True
    known: bool = True


@dataclass(frozen=True)
class FeasibilityPolicy:
    min_absolute_net_profit: TokenAmount
    min_net_profit_bps: int
    profit_safety_buffer: TokenAmount
    max_quote_age: timedelta = timedelta(milliseconds=1500)
    max_conversion_age: timedelta = timedelta(seconds=5)
    max_wallet_age: timedelta = timedelta(seconds=2)
    max_account_age: timedelta = timedelta(seconds=2)
    max_tip_age: timedelta = timedelta(seconds=2)
    max_price_impact_bps: int = 10_000
    tip_absolute_cap: Lamports = Lamports(0)
    priority_fee_absolute_cap: Lamports = Lamports(0)
    live_readiness: bool = False
    config_version: str = "test"


@dataclass(frozen=True)
class ResourceBudget:
    protected_reserve: Lamports
    outstanding_attempt_budget: Lamports
    current_base_fee: Lamports
    current_priority_fee_cap: Lamports
    current_tip: Lamports
    current_account_rent_funding: Lamports
    current_temporary_wsol_funding: Lamports
    other_current_native_debit: Lamports
    current_success_debit_cap: Lamports
    per_failure_charge_cap: Lamports
    remaining_failure_attempts: int
    future_failure_budget: Lamports
    total_required_operational_lamports: Lamports
    spendable_lamports: Lamports
    remaining_free_lamports_after_approval: Lamports


@dataclass(frozen=True)
class TradeFeasibilityDecision:
    stage: str
    feasible: bool
    feasible_for_next_stage: bool
    primary_reason: FeasibilityReason
    reasons: tuple[FeasibilityReason, ...]
    principal: TokenAmount
    exact_repayment: Optional[TokenAmount]
    guaranteed_minimum_output: TokenAmount
    guaranteed_surplus: Optional[TokenAmount]
    converted_native_costs: Optional[TokenAmount]
    guaranteed_net_profit: Optional[TokenAmount]
    expected_profit: Optional[TokenAmount]
    roi_bps: Optional[int]
    resource_budget: Optional[ResourceBudget]
    provider: ProviderCapacity
    route: RouteCapacity
    transaction: TransactionFeasibility
    config_version: str
    decision_hash: str
    reservation_mode: str = "process_local_reservation_only"


class TradeFeasibilityEngine:
    def evaluate(self, *, stage: str, wallet_policy: WalletReservePolicy, wallet: WalletResourceSnapshot, native_cost: NativeCostEstimate, provider: ProviderCapacity, route: RouteCapacity, transaction: TransactionFeasibility, conversion: RationalConversionSnapshot, policy: FeasibilityPolicy, now: datetime) -> TradeFeasibilityDecision:
        reasons: list[FeasibilityReason] = []
        budget = None
        repayment = provider.exact_repayment
        guaranteed_surplus = converted_native = net = expected_profit = None
        roi_bps = None
        try:
            self._units(provider, route, policy)
        except Exception:
            reasons.append(FeasibilityReason.INVALID_UNITS)
        if wallet_policy.protected_reserve is None:
            reasons.append(FeasibilityReason.MISSING_PROTECTED_RESERVE)
        if wallet.wallet_balance is None:
            reasons.append(FeasibilityReason.MISSING_WALLET_BALANCE)
        if wallet.outstanding_reserved is None:
            reasons.append(FeasibilityReason.UNKNOWN_OUTSTANDING_BUDGET)
        if not wallet.healthy or now - wallet.observed_at > policy.max_wallet_age:
            reasons.append(FeasibilityReason.STALE_WALLET_STATE)
        if not provider.healthy or not provider.borrow_allowed or provider.exact_repayment is None:
            reasons.append(FeasibilityReason.PROVIDER_UNAVAILABLE)
        elif not self._between(route.proposed_principal, provider.min_borrow, provider.max_borrow) or route.proposed_principal.base_units > provider.available_liquidity.base_units:
            reasons.append(FeasibilityReason.PROVIDER_CAPACITY_EXCEEDED)
        if not route.healthy or (route.expires_at and now > route.expires_at) or now - route.observed_at > policy.max_quote_age:
            reasons.append(FeasibilityReason.ROUTE_STALE)
        if not route.composable or not route.complete_legs:
            reasons.append(FeasibilityReason.ROUTE_NOT_COMPOSABLE)
        if route.max_executable_input and route.proposed_principal.base_units > route.max_executable_input.base_units:
            reasons.append(FeasibilityReason.ROUTE_CAPACITY_EXCEEDED)
        if route.price_impact_bps > policy.max_price_impact_bps:
            reasons.append(FeasibilityReason.ROUTE_CAPACITY_EXCEEDED)
        if repayment and route.guaranteed_min_final_output.base_units < repayment.base_units:
            reasons.append(FeasibilityReason.REPAYMENT_NOT_GUARANTEED)
        if transaction.wire_size > transaction.wire_size_limit or not transaction.known or not transaction.complete:
            reasons.append(FeasibilityReason.TRANSACTION_TOO_LARGE)
        if transaction.total_accounts > transaction.account_limit or not transaction.alts_resolved or not transaction.alts_fresh:
            reasons.append(FeasibilityReason.ACCOUNT_LIMIT_EXCEEDED)
        if transaction.chosen_cu_limit > transaction.cu_limit_cap or (transaction.estimated_cu and transaction.estimated_cu > transaction.chosen_cu_limit):
            reasons.append(FeasibilityReason.COMPUTE_LIMIT_EXCEEDED)
        try:
            conversion.validate(now=now, max_age=policy.max_conversion_age)
        except Exception:
            reasons.append(FeasibilityReason.MISSING_OR_STALE_CONVERSION)
        try:
            if native_cost.base_fee is None or native_cost.fee_message_hash != native_cost.expected_message_hash:
                reasons.append(FeasibilityReason.MISSING_BASE_FEE)
            priority = native_cost.priority_fee()
            if priority.value > native_cost.priority_fee_cap.value or priority.value > policy.priority_fee_absolute_cap.value:
                reasons.append(FeasibilityReason.PRIORITY_FEE_CAP_EXCEEDED)
        except LookupError:
            priority = Lamports(0); reasons.append(FeasibilityReason.MISSING_PRIORITY_FEE)
        try:
            tip = native_cost.tip
            if now - tip.observed_at > policy.max_tip_age or tip.lamports.value < tip.floor_lamports.value:
                reasons.append(FeasibilityReason.MISSING_OR_STALE_TIP)
            if tip.submission_mode == "rpc" and tip.lamports.value != 0:
                reasons.append(FeasibilityReason.TIP_CAP_EXCEEDED)
            if tip.lamports.value > policy.tip_absolute_cap.value:
                reasons.append(FeasibilityReason.TIP_CAP_EXCEEDED)
            if native_cost.compiler_tip_instruction_hash and tip.instruction_hash and native_cost.compiler_tip_instruction_hash != tip.instruction_hash:
                reasons.append(FeasibilityReason.TIP_CAP_EXCEEDED)
        except Exception:
            reasons.append(FeasibilityReason.MISSING_OR_STALE_TIP)
        try:
            rent = native_cost.account_rent()
        except PermissionError:
            rent = Lamports(0); reasons.append(FeasibilityReason.ATA_ACCOUNT_INVALID)
        except LookupError:
            rent = Lamports(0); reasons.append(FeasibilityReason.MISSING_RENT_ESTIMATE)
        if wallet_policy.protected_reserve and wallet.wallet_balance and wallet.outstanding_reserved is not None and native_cost.base_fee is not None:
            failure_cap = native_cost.failed_attempt_charge_cap or wallet_policy.failed_attempt_charge_cap
            current_success = Lamports(native_cost.base_fee.value + min(priority.value, native_cost.priority_fee_cap.value) + native_cost.tip.lamports.value + rent.value + native_cost.temporary_wsol_rent.value + native_cost.temporary_wsol_funding.value + native_cost.other_native_debit.value)
            future = Lamports(wallet_policy.max_additional_failed_attempts * failure_cap.value)
            spendable_value = wallet.wallet_balance.value - wallet_policy.protected_reserve.value - wallet.outstanding_reserved.value
            spendable = Lamports(max(0, spendable_value))
            required = Lamports(current_success.value + future.value)
            remaining = Lamports(max(0, spendable.value - required.value))
            budget = ResourceBudget(wallet_policy.protected_reserve, wallet.outstanding_reserved, native_cost.base_fee, priority, native_cost.tip.lamports, rent, Lamports(native_cost.temporary_wsol_rent.value + native_cost.temporary_wsol_funding.value), native_cost.other_native_debit, current_success, failure_cap, wallet_policy.max_additional_failed_attempts, future, required, spendable, remaining)
            if required.value > spendable.value:
                reasons.append(FeasibilityReason.INSUFFICIENT_OPERATIONAL_SOL)
        try:
            if repayment is None:
                reasons.append(FeasibilityReason.PROVIDER_UNAVAILABLE)
            else:
                token_costs = sum(c.base_units for c in route.non_embedded_token_costs)
                surplus_units = route.guaranteed_min_final_output.base_units - repayment.base_units - token_costs
                guaranteed_surplus = TokenAmount(route.settlement_asset, max(0, surplus_units), route.guaranteed_min_final_output.decimals)
                native_non_refundable = native_cost.base_fee.value if native_cost.base_fee else 0
                native_non_refundable += min(priority.value, native_cost.priority_fee_cap.value) + native_cost.tip.lamports.value + (rent.value if rent.value else 0)
                converted_native = conversion.convert_cost_up(TokenAmount(NATIVE_SOL_MINT, native_non_refundable, 9))
                net_units = surplus_units - converted_native.base_units - policy.profit_safety_buffer.base_units
                net = TokenAmount(route.settlement_asset, max(0, net_units), route.guaranteed_min_final_output.decimals)
                expected_profit = TokenAmount(route.settlement_asset, max(0, route.expected_final_output.base_units - repayment.base_units - token_costs), route.expected_final_output.decimals)
                roi_bps = (net_units * 10_000) // route.proposed_principal.base_units if route.proposed_principal.base_units else None
                if net_units < policy.min_absolute_net_profit.base_units:
                    reasons.append(FeasibilityReason.BELOW_MIN_NET_PROFIT)
                if roi_bps is None or roi_bps < policy.min_net_profit_bps:
                    reasons.append(FeasibilityReason.BELOW_MIN_ROI)
        except Exception:
            reasons.append(FeasibilityReason.MISSING_OR_STALE_CONVERSION)
        if stage != "simulated":
            reasons.append(FeasibilityReason.SIMULATION_REQUIRED)
        unique = tuple(dict.fromkeys(reasons))
        hard = tuple(r for r in unique if r is not FeasibilityReason.SIMULATION_REQUIRED)
        feasible = not hard and stage == "simulated"
        feasible_next = not hard and stage in {"prebuild", "compiled"}
        primary = FeasibilityReason.FEASIBLE_FOR_SIMULATION if feasible_next and not feasible else self._primary(unique)
        dh = hashlib.sha256(json.dumps({"stage": stage, "reasons": [r.value for r in unique], "principal": route.proposed_principal.base_units, "net": None if net is None else net.base_units, "config": policy.config_version}, sort_keys=True).encode()).hexdigest()
        return TradeFeasibilityDecision(stage, feasible, feasible_next, primary, unique, route.proposed_principal, repayment, route.guaranteed_min_final_output, guaranteed_surplus, converted_native, net, expected_profit, roi_bps, budget, provider, route, transaction, policy.config_version, dh)

    def _primary(self, reasons: tuple[FeasibilityReason, ...]) -> FeasibilityReason:
        for r in PRIMARY_REASON_PRIORITY:
            if r in reasons:
                return r
        return FeasibilityReason.FEASIBLE_FOR_SIMULATION

    def _between(self, v: TokenAmount, lo: TokenAmount, hi: TokenAmount) -> bool:
        return (v.mint, v.decimals) == (lo.mint, lo.decimals) == (hi.mint, hi.decimals) and lo.base_units <= v.base_units <= hi.base_units

    def _units(self, provider: ProviderCapacity, route: RouteCapacity, policy: FeasibilityPolicy) -> None:
        for amount in (provider.min_borrow, provider.max_borrow, provider.available_liquidity, route.proposed_principal, route.expected_final_output, route.guaranteed_min_final_output, policy.min_absolute_net_profit, policy.profit_safety_buffer):
            if amount.decimals < 0:
                raise MonetaryUnitError("unknown decimals")
        if route.guaranteed_min_final_output.mint != route.settlement_asset:
            raise MonetaryUnitError("minimum output mint mismatch")


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    lamports: Lamports
    terminal: bool = False
    ambiguous: bool = False


class InMemoryReservationStore:
    def __init__(self):
        self._lock = threading.Lock(); self._items: dict[str, Reservation] = {}

    def snapshot(self) -> tuple[Lamports, tuple[str, ...]]:
        with self._lock:
            active = [r for r in self._items.values() if not r.terminal]
            return Lamports(sum(r.lamports.value for r in active)), tuple(sorted(r.reservation_id for r in active))

    def reserve(self, reservation_id: str, amount: Lamports, available: Lamports) -> bool:
        with self._lock:
            used = sum(r.lamports.value for r in self._items.values() if not r.terminal)
            if used + amount.value > available.value or reservation_id in self._items:
                return False
            self._items[reservation_id] = Reservation(reservation_id, amount)
            return True

    def release(self, reservation_id: str, *, terminal: bool, ambiguous: bool = False) -> None:
        with self._lock:
            if reservation_id in self._items and terminal and not ambiguous:
                self._items[reservation_id] = Reservation(reservation_id, self._items[reservation_id].lamports, terminal=True)


class CandidateEvaluator(Protocol):
    def __call__(self, principal: TokenAmount) -> TradeFeasibilityDecision: ...


@dataclass(frozen=True)
class SizingResult:
    best: Optional[TradeFeasibilityDecision]
    evaluated: int
    reasons: dict[str, int]
    candidates: tuple[int, ...]


@dataclass(frozen=True)
class SizingPolicy:
    min_principal: TokenAmount
    max_principal: TokenAmount
    max_evaluations: int
    coarse_points: int = 5
    seed_sizes: tuple[int, ...] = ()


class OptimalTradeSizer:
    def choose(self, *, provider: ProviderCapacity, route_min: TokenAmount, route_max: TokenAmount, policy: SizingPolicy, evaluator: CandidateEvaluator) -> SizingResult:
        lo = max(provider.min_borrow.base_units, route_min.base_units, policy.min_principal.base_units)
        hi = min(provider.max_borrow.base_units, provider.available_liquidity.base_units, route_max.base_units, policy.max_principal.base_units)
        if lo > hi or policy.max_evaluations <= 0:
            return SizingResult(None, 0, {FeasibilityReason.PROVIDER_CAPACITY_EXCEEDED.value: 1}, ())
        points = max(1, min(policy.coarse_points, policy.max_evaluations))
        step = max(1, (hi - lo) // max(1, points - 1))
        candidates = {lo, hi, *policy.seed_sizes}
        for i in range(points):
            candidates.add(min(hi, lo + i * step))
        ordered = [c for c in sorted(candidates) if lo <= c <= hi][:policy.max_evaluations]
        decisions: list[TradeFeasibilityDecision] = []
        reasons: Counter[str] = Counter()
        for c in ordered:
            try:
                d = evaluator(TokenAmount(provider.asset_mint, c, provider.min_borrow.decimals))
                decisions.append(d)
                if not (d.feasible or d.feasible_for_next_stage):
                    reasons[d.primary_reason.value] += 1
            except Exception:
                reasons[FeasibilityReason.ROUTE_STALE.value] += 1
        feasible = [d for d in decisions if d.feasible or d.feasible_for_next_stage]
        if not feasible:
            return SizingResult(None, len(ordered), dict(reasons), tuple(ordered))
        best = sorted(feasible, key=lambda d: (-(d.guaranteed_net_profit.base_units if d.guaranteed_net_profit else -1), d.principal.base_units, d.resource_budget.current_success_debit_cap.value if d.resource_budget else 0, d.route.price_impact_bps))[0]
        return SizingResult(best, len(ordered), dict(reasons), tuple(ordered))
