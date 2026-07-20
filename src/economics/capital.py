"""Capital-aware sizing and native SOL reservation policy for PR-032.

This module is intentionally side-effect free: it does not fetch quotes, sign,
simulate, or submit transactions.  It gives the future planner/paper/live
runners one deterministic gate for answering the only safe question before
compilation: is this candidate economically and operationally affordable with
the wallet SOL that must pay fees, rent and tips?
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
import threading
from typing import Any, Iterable, Mapping

from src.config.runtime import RuntimeConfig
from src.domain.money import LAMPORTS_PER_SOL, U64_MAX


class CapitalEngineError(ValueError):
    """Raised when PR-032 capital inputs are malformed."""


class PolicyProfile(StrEnum):
    """Execution policy surface; live remains admission-gated elsewhere."""

    PAPER = "paper"
    CANARY = "canary"
    LIVE = "live"


class NoTradeReason(StrEnum):
    """Stable machine-readable rejection reasons for the capital gate."""

    TRADE_PERMITTED = "trade_permitted"
    INVALID_CANDIDATE = "invalid_candidate"
    INSUFFICIENT_NATIVE_BALANCE = "insufficient_native_balance"
    PRIORITY_FEE_EXCEEDS_POLICY = "priority_fee_exceeds_policy"
    JITO_TIP_EXCEEDS_POLICY = "jito_tip_exceeds_policy"
    PEAK_RENT_EXCEEDS_POLICY = "peak_rent_exceeds_policy"
    FLASH_LOAN_SIZE_EXCEEDS_POLICY = "flash_loan_size_exceeds_policy"
    NON_POSITIVE_GROSS_PROFIT = "non_positive_gross_profit"
    NON_POSITIVE_CONSERVATIVE_NET_PROFIT = "non_positive_conservative_net_profit"
    BELOW_MINIMUM_NET_PROFIT = "below_minimum_net_profit"
    NO_CANDIDATES = "no_candidates"


def _strict_lamports(value: int, *, field: str, upper: int = U64_MAX) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CapitalEngineError(f"{field} must be integer lamports")
    if value < 0 or value > upper:
        raise CapitalEngineError(f"{field} outside allowed lamport range")
    return value


def _strict_signed_lamports(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CapitalEngineError(f"{field} must be integer lamports")
    return value


@dataclass(frozen=True, slots=True)
class CapitalPolicy:
    """Operator policy for wallet-native SOL and profitability checks."""

    profile: PolicyProfile = PolicyProfile.PAPER
    protected_reserve_lamports: int = 10_000_000
    minimum_net_profit_lamports: int = 100_000
    maximum_priority_fee_lamports: int = 1_000_000
    maximum_jito_tip_lamports: int = 1_000_000
    maximum_peak_rent_lamports: int = 20_000_000
    contingency_lamports: int = 500_000
    maximum_flash_loan_lamports: int | None = None

    def __post_init__(self) -> None:
        _strict_lamports(
            self.protected_reserve_lamports,
            field="protected_reserve_lamports",
        )
        _strict_lamports(
            self.minimum_net_profit_lamports,
            field="minimum_net_profit_lamports",
        )
        _strict_lamports(
            self.maximum_priority_fee_lamports,
            field="maximum_priority_fee_lamports",
        )
        _strict_lamports(
            self.maximum_jito_tip_lamports,
            field="maximum_jito_tip_lamports",
        )
        _strict_lamports(
            self.maximum_peak_rent_lamports,
            field="maximum_peak_rent_lamports",
        )
        _strict_lamports(self.contingency_lamports, field="contingency_lamports")
        if self.maximum_flash_loan_lamports is not None:
            _strict_lamports(
                self.maximum_flash_loan_lamports,
                field="maximum_flash_loan_lamports",
                upper=2**128 - 1,
            )

    @classmethod
    def from_runtime_config(
        cls,
        config: RuntimeConfig,
        *,
        profile: PolicyProfile = PolicyProfile.PAPER,
        maximum_jito_tip_lamports: int | None = None,
        maximum_peak_rent_lamports: int = 20_000_000,
        maximum_flash_loan_lamports: int | None = None,
    ) -> "CapitalPolicy":
        """Build PR-032 policy from the PR-026 typed runtime config."""

        return cls(
            profile=profile,
            protected_reserve_lamports=config.monetary.protected_reserve_lamports,
            minimum_net_profit_lamports=(
                config.monetary.minimum_net_profit_lamports
            ),
            maximum_priority_fee_lamports=(
                config.monetary.maximum_priority_fee_lamports
            ),
            maximum_jito_tip_lamports=(
                config.providers.jito.min_tip_lamports
                if maximum_jito_tip_lamports is None
                else maximum_jito_tip_lamports
            ),
            maximum_peak_rent_lamports=maximum_peak_rent_lamports,
            contingency_lamports=config.monetary.contingency_lamports,
            maximum_flash_loan_lamports=maximum_flash_loan_lamports,
        )

    @property
    def fingerprint(self) -> str:
        return (
            f"pr032:{self.profile}:reserve={self.protected_reserve_lamports}:"
            f"min_net={self.minimum_net_profit_lamports}:"
            f"max_prio={self.maximum_priority_fee_lamports}:"
            f"max_tip={self.maximum_jito_tip_lamports}:"
            f"max_rent={self.maximum_peak_rent_lamports}:"
            f"contingency={self.contingency_lamports}:"
            f"max_flash={self.maximum_flash_loan_lamports}"
        )


@dataclass(frozen=True, slots=True)
class MessageFeeQuote:
    """Network base fee quote derived from Solana `getFeeForMessage`."""

    message_hash: str
    base_fee_lamports: int
    context_slot: int | None = None
    source: str = "getFeeForMessage"

    def __post_init__(self) -> None:
        if not self.message_hash:
            raise CapitalEngineError("message_hash is required for fee quote")
        _strict_lamports(self.base_fee_lamports, field="base_fee_lamports")
        if self.context_slot is not None:
            _strict_lamports(self.context_slot, field="context_slot", upper=2**63 - 1)

    @classmethod
    def from_rpc_payload(
        cls,
        *,
        message_hash: str,
        payload: Mapping[str, Any],
    ) -> "MessageFeeQuote":
        """Parse a minimal `getFeeForMessage` response and fail closed."""

        try:
            value = payload["result"]["value"]
        except (KeyError, TypeError) as exc:
            raise CapitalEngineError("missing getFeeForMessage result.value") from exc
        if value is None:
            raise CapitalEngineError("getFeeForMessage returned null fee")
        slot = None
        try:
            context = payload["result"].get("context")
        except AttributeError:
            context = None
        if isinstance(context, Mapping) and "slot" in context:
            slot = context["slot"]
        return cls(
            message_hash=message_hash,
            base_fee_lamports=_strict_lamports(value, field="base_fee_lamports"),
            context_slot=(
                None
                if slot is None
                else _strict_lamports(slot, field="context_slot", upper=2**63 - 1)
            ),
        )


@dataclass(frozen=True, slots=True)
class NativeCostBreakdown:
    """Worst-case SOL paid or locked by the wallet for one candidate."""

    base_network_fee_lamports: int
    priority_fee_lamports: int = 0
    jito_tip_lamports: int = 0
    peak_rent_lamports: int = 0
    rent_loss_lamports: int = 0

    def __post_init__(self) -> None:
        _strict_lamports(
            self.base_network_fee_lamports,
            field="base_network_fee_lamports",
        )
        _strict_lamports(self.priority_fee_lamports, field="priority_fee_lamports")
        _strict_lamports(self.jito_tip_lamports, field="jito_tip_lamports")
        _strict_lamports(self.peak_rent_lamports, field="peak_rent_lamports")
        _strict_lamports(self.rent_loss_lamports, field="rent_loss_lamports")
        if self.rent_loss_lamports > self.peak_rent_lamports:
            raise CapitalEngineError(
                "rent_loss_lamports cannot exceed peak_rent_lamports"
            )

    @classmethod
    def from_message_fee(
        cls,
        fee_quote: MessageFeeQuote,
        *,
        priority_fee_lamports: int = 0,
        jito_tip_lamports: int = 0,
        peak_rent_lamports: int = 0,
        rent_loss_lamports: int = 0,
    ) -> "NativeCostBreakdown":
        return cls(
            base_network_fee_lamports=fee_quote.base_fee_lamports,
            priority_fee_lamports=priority_fee_lamports,
            jito_tip_lamports=jito_tip_lamports,
            peak_rent_lamports=peak_rent_lamports,
            rent_loss_lamports=rent_loss_lamports,
        )

    def required_wallet_lamports(self, policy: CapitalPolicy) -> int:
        return (
            self.base_network_fee_lamports
            + self.priority_fee_lamports
            + self.jito_tip_lamports
            + self.peak_rent_lamports
            + policy.contingency_lamports
        )

    def settled_native_cost_lamports(self) -> int:
        return (
            self.base_network_fee_lamports
            + self.priority_fee_lamports
            + self.jito_tip_lamports
            + self.rent_loss_lamports
        )


@dataclass(frozen=True, slots=True)
class CapitalCandidate:
    """Native-denominated executable candidate economics.

    PR-032 intentionally accepts only native/wSOL-denominated conservative
    economics.  Non-native settlement assets must be converted upstream using
    a verified oracle/conversion contract before reaching this gate.
    """

    candidate_id: str
    guaranteed_min_out_lamports: int
    flash_repayment_lamports: int
    requested_flash_loan_lamports: int
    native_costs: NativeCostBreakdown
    protocol_fee_lamports: int = 0
    slippage_buffer_lamports: int = 0
    uncertainty_buffer_lamports: int = 0
    message_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise CapitalEngineError("candidate_id is required")
        _strict_lamports(
            self.guaranteed_min_out_lamports,
            field="guaranteed_min_out_lamports",
            upper=2**128 - 1,
        )
        _strict_lamports(
            self.flash_repayment_lamports,
            field="flash_repayment_lamports",
            upper=2**128 - 1,
        )
        _strict_lamports(
            self.requested_flash_loan_lamports,
            field="requested_flash_loan_lamports",
            upper=2**128 - 1,
        )
        _strict_lamports(self.protocol_fee_lamports, field="protocol_fee_lamports")
        _strict_lamports(
            self.slippage_buffer_lamports,
            field="slippage_buffer_lamports",
        )
        _strict_lamports(
            self.uncertainty_buffer_lamports,
            field="uncertainty_buffer_lamports",
        )

    def gross_profit_lamports(self) -> int:
        return _strict_signed_lamports(
            self.guaranteed_min_out_lamports - self.flash_repayment_lamports,
            field="gross_profit_lamports",
        )

    def conservative_net_profit_lamports(self) -> int:
        return (
            self.gross_profit_lamports()
            - self.protocol_fee_lamports
            - self.native_costs.settled_native_cost_lamports()
            - self.slippage_buffer_lamports
            - self.uncertainty_buffer_lamports
        )

    def required_wallet_lamports(self, policy: CapitalPolicy) -> int:
        return self.native_costs.required_wallet_lamports(policy)


@dataclass(frozen=True, slots=True)
class CapitalDecision:
    allowed: bool
    reason: NoTradeReason
    candidate_id: str | None
    available_native_lamports: int
    required_native_lamports: int
    conservative_net_profit_lamports: int
    policy_fingerprint: str
    reservation_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason.value,
            "candidate_id": self.candidate_id,
            "available_native_lamports": str(self.available_native_lamports),
            "required_native_lamports": str(self.required_native_lamports),
            "conservative_net_profit_lamports": str(
                self.conservative_net_profit_lamports
            ),
            "policy_fingerprint": self.policy_fingerprint,
            "reservation_id": self.reservation_id,
        }


@dataclass(frozen=True, slots=True)
class CapitalReservation:
    reservation_id: str
    candidate_id: str
    reserved_lamports: int
    conservative_net_profit_lamports: int
    message_hash: str | None
    policy_fingerprint: str

    def __post_init__(self) -> None:
        if not self.reservation_id or not self.candidate_id:
            raise CapitalEngineError("reservation and candidate IDs are required")
        _strict_lamports(self.reserved_lamports, field="reserved_lamports")
        _strict_signed_lamports(
            self.conservative_net_profit_lamports,
            field="conservative_net_profit_lamports",
        )


@dataclass(frozen=True, slots=True)
class CapitalLedgerSnapshot:
    wallet_lamports: int
    protected_reserve_lamports: int
    active_reserved_lamports: int
    available_native_lamports: int
    reservations: tuple[CapitalReservation, ...]


class AtomicCapitalLedger:
    """Single-process atomic native SOL reservation ledger.

    The durable journal/recovery layer belongs to PR-041.  This class keeps
    PR-032's concurrency invariant local and deterministic: two candidates
    cannot both reserve the same available lamports inside one process.
    """

    def __init__(self, *, wallet_lamports: int, policy: CapitalPolicy) -> None:
        self._wallet_lamports = _strict_lamports(
            wallet_lamports,
            field="wallet_lamports",
        )
        self._policy = policy
        self._lock = threading.RLock()
        self._reservations: dict[str, CapitalReservation] = {}
        self._sequence = 0

    @property
    def policy(self) -> CapitalPolicy:
        return self._policy

    def update_wallet_lamports(self, wallet_lamports: int) -> None:
        checked = _strict_lamports(wallet_lamports, field="wallet_lamports")
        with self._lock:
            self._wallet_lamports = checked

    def active_reserved_lamports(self) -> int:
        with self._lock:
            return sum(item.reserved_lamports for item in self._reservations.values())

    def available_native_lamports(self) -> int:
        with self._lock:
            return self._available_native_lamports_unlocked()

    def _available_native_lamports_unlocked(self) -> int:
        reserved = sum(item.reserved_lamports for item in self._reservations.values())
        available = (
            self._wallet_lamports
            - self._policy.protected_reserve_lamports
            - reserved
        )
        return max(0, available)

    def evaluate(self, candidate: CapitalCandidate) -> CapitalDecision:
        with self._lock:
            return self._evaluate_unlocked(candidate)

    def _evaluate_unlocked(self, candidate: CapitalCandidate) -> CapitalDecision:
        available = self._available_native_lamports_unlocked()
        required = candidate.required_wallet_lamports(self._policy)
        net = candidate.conservative_net_profit_lamports()

        reason = NoTradeReason.TRADE_PERMITTED
        if candidate.native_costs.priority_fee_lamports > (
            self._policy.maximum_priority_fee_lamports
        ):
            reason = NoTradeReason.PRIORITY_FEE_EXCEEDS_POLICY
        elif candidate.native_costs.jito_tip_lamports > (
            self._policy.maximum_jito_tip_lamports
        ):
            reason = NoTradeReason.JITO_TIP_EXCEEDS_POLICY
        elif candidate.native_costs.peak_rent_lamports > (
            self._policy.maximum_peak_rent_lamports
        ):
            reason = NoTradeReason.PEAK_RENT_EXCEEDS_POLICY
        elif (
            self._policy.maximum_flash_loan_lamports is not None
            and candidate.requested_flash_loan_lamports
            > self._policy.maximum_flash_loan_lamports
        ):
            reason = NoTradeReason.FLASH_LOAN_SIZE_EXCEEDS_POLICY
        elif candidate.gross_profit_lamports() <= 0:
            reason = NoTradeReason.NON_POSITIVE_GROSS_PROFIT
        elif net <= 0:
            reason = NoTradeReason.NON_POSITIVE_CONSERVATIVE_NET_PROFIT
        elif net < self._policy.minimum_net_profit_lamports:
            reason = NoTradeReason.BELOW_MINIMUM_NET_PROFIT
        elif available < required:
            reason = NoTradeReason.INSUFFICIENT_NATIVE_BALANCE

        return CapitalDecision(
            allowed=reason is NoTradeReason.TRADE_PERMITTED,
            reason=reason,
            candidate_id=candidate.candidate_id,
            available_native_lamports=available,
            required_native_lamports=required,
            conservative_net_profit_lamports=net,
            policy_fingerprint=self._policy.fingerprint,
        )

    def reserve(self, candidate: CapitalCandidate) -> CapitalDecision:
        with self._lock:
            decision = self._evaluate_unlocked(candidate)
            if not decision.allowed:
                return decision

            self._sequence += 1
            reservation_id = (
                f"capres-{self._sequence:08d}-{candidate.candidate_id[:24]}"
            )
            reservation = CapitalReservation(
                reservation_id=reservation_id,
                candidate_id=candidate.candidate_id,
                reserved_lamports=decision.required_native_lamports,
                conservative_net_profit_lamports=(
                    decision.conservative_net_profit_lamports
                ),
                message_hash=candidate.message_hash,
                policy_fingerprint=self._policy.fingerprint,
            )
            self._reservations[reservation_id] = reservation
            return CapitalDecision(
                allowed=True,
                reason=NoTradeReason.TRADE_PERMITTED,
                candidate_id=candidate.candidate_id,
                available_native_lamports=decision.available_native_lamports,
                required_native_lamports=decision.required_native_lamports,
                conservative_net_profit_lamports=(
                    decision.conservative_net_profit_lamports
                ),
                policy_fingerprint=self._policy.fingerprint,
                reservation_id=reservation_id,
            )

    def release(self, reservation_id: str) -> bool:
        """Release a reservation idempotently.

        Returns True only when an active reservation was removed.  Repeating
        the same release is safe and returns False.
        """

        with self._lock:
            return self._reservations.pop(reservation_id, None) is not None

    def snapshot(self) -> CapitalLedgerSnapshot:
        with self._lock:
            reservations = tuple(self._reservations.values())
            reserved = sum(item.reserved_lamports for item in reservations)
            return CapitalLedgerSnapshot(
                wallet_lamports=self._wallet_lamports,
                protected_reserve_lamports=self._policy.protected_reserve_lamports,
                active_reserved_lamports=reserved,
                available_native_lamports=self._available_native_lamports_unlocked(),
                reservations=reservations,
            )

    def choose_best_candidate(
        self,
        candidates: Iterable[CapitalCandidate],
    ) -> CapitalDecision:
        """Return the highest conservative-net candidate without reserving it."""

        best_allowed: CapitalDecision | None = None
        first_rejection: CapitalDecision | None = None
        for candidate in candidates:
            decision = self.evaluate(candidate)
            if decision.allowed:
                if best_allowed is None or (
                    decision.conservative_net_profit_lamports
                    > best_allowed.conservative_net_profit_lamports
                ):
                    best_allowed = decision
            elif first_rejection is None:
                first_rejection = decision

        if best_allowed is not None:
            return best_allowed
        if first_rejection is not None:
            return first_rejection
        return CapitalDecision(
            allowed=False,
            reason=NoTradeReason.NO_CANDIDATES,
            candidate_id=None,
            available_native_lamports=self.available_native_lamports(),
            required_native_lamports=0,
            conservative_net_profit_lamports=0,
            policy_fingerprint=self._policy.fingerprint,
        )


def lamports_from_sol_string(sol: str) -> int:
    """Helper for tests/config glue that keeps PR-032 away from floats."""

    text = sol.strip()
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)?", text):
        raise CapitalEngineError("SOL amount must be a non-negative decimal string")
    if "." in text:
        whole, fraction = text.split(".", 1)
        if len(fraction) > 9:
            raise CapitalEngineError("SOL amount has more than 9 decimal places")
        fraction = fraction.ljust(9, "0")
        return int(whole) * LAMPORTS_PER_SOL + int(fraction)
    return int(text) * LAMPORTS_PER_SOL
