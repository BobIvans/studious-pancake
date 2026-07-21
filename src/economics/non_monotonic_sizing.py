"""PR-118 non-monotonic sizing and typed multi-asset cost ledger.

This module is deliberately side-effect free. It does not quote, compile, sign,
simulate, submit, or reserve capital. It provides the exact-amount evaluation
boundary that later route discovery/finalization code can call after PR-113 has
made every quote amount-coupled.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum, StrEnum
import hashlib
import json
import re
from typing import Any

from src.economics.capital import (
    CapitalCandidate,
    CapitalDecision,
    CapitalEngineError,
    NativeCostBreakdown,
)
from src.economics.durable_reservations import (
    DurableCapitalCoordinator,
    WalletBalanceSnapshot,
)

PR118_SIZING_SCHEMA_VERSION = "pr118.non-monotonic-sizing.v1"
PR118_LEDGER_SCHEMA_VERSION = "pr118.typed-multi-asset-ledger.v1"

_ASSET_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9._:-]{1,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_NATIVE_SETTLEMENT_ASSETS = frozenset({"SOL", "WSOL"})


class PR118CostComponentKind(StrEnum):
    """Typed cost component names for the multi-asset ledger."""

    PRINCIPAL = "principal"
    FLASH_FEE = "flash-fee"
    PROTOCOL_ROUNDING = "protocol-rounding"
    PROVIDER_FEE = "provider-fee"
    PLATFORM_FEE = "platform-fee"
    TRANSFER_FEE = "transfer-fee"
    NETWORK_FEE = "network-fee"
    PRIORITY_FEE = "priority-fee"
    TIP = "tip"
    RENT_LOCKED = "rent-locked"
    RENT_REFUNDED = "rent-refunded"
    RENT_LOST = "rent-lost"
    SLIPPAGE = "slippage"
    UNCERTAINTY = "uncertainty"


class PR118LedgerDirection(StrEnum):
    """Whether a ledger component reduces or increases conservative value."""

    DEBIT = "debit"
    CREDIT = "credit"


class PR118SizingStopReason(StrEnum):
    """Why a bounded non-monotonic sizing evaluation stopped."""

    EVALUATED_ALL_POINTS = "evaluated-all-points"
    REQUEST_BUDGET_EXHAUSTED = "request-budget-exhausted"
    NO_POINTS = "no-points"


@dataclass(frozen=True, slots=True)
class PR118AssetAmount:
    """Integer amount in one canonical asset unit."""

    asset_id: str
    amount: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_id", _asset_id(self.asset_id))
        _integer_amount(self.amount, "amount")

    def to_json(self) -> dict[str, str]:
        return {"asset_id": self.asset_id, "amount": str(self.amount)}


@dataclass(frozen=True, slots=True)
class PR118CostLedgerEntry:
    """One typed debit or credit in an asset-specific ledger."""

    asset_id: str
    kind: PR118CostComponentKind
    amount: int
    direction: PR118LedgerDirection = PR118LedgerDirection.DEBIT
    evidence_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_id", _asset_id(self.asset_id))
        if not isinstance(self.kind, PR118CostComponentKind):
            object.__setattr__(self, "kind", PR118CostComponentKind(str(self.kind)))
        if not isinstance(self.direction, PR118LedgerDirection):
            object.__setattr__(
                self,
                "direction",
                PR118LedgerDirection(str(self.direction)),
            )
        _integer_amount(self.amount, "amount")
        if self.amount <= 0:
            raise CapitalEngineError("ledger entry amount must be positive")
        if self.evidence_hash is not None:
            object.__setattr__(
                self,
                "evidence_hash",
                _sha256(self.evidence_hash, "evidence_hash"),
            )

    def signed_amount(self) -> int:
        if self.direction is PR118LedgerDirection.CREDIT:
            return -self.amount
        return self.amount

    def to_json(self) -> dict[str, str | None]:
        return {
            "asset_id": self.asset_id,
            "kind": self.kind.value,
            "amount": str(self.amount),
            "direction": self.direction.value,
            "evidence_hash": self.evidence_hash,
        }


@dataclass(frozen=True, slots=True)
class PR118FlashRepaymentTerms:
    """Unambiguous flash repayment invariant for one borrowed asset."""

    asset_id: str
    principal_amount: int
    flash_fee_amount: int
    protocol_rounding_amount: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_id", _asset_id(self.asset_id))
        _integer_amount(self.principal_amount, "principal_amount")
        _integer_amount(self.flash_fee_amount, "flash_fee_amount")
        _integer_amount(self.protocol_rounding_amount, "protocol_rounding_amount")
        if self.principal_amount <= 0:
            raise CapitalEngineError("principal_amount must be positive")

    @property
    def required_repayment_amount(self) -> int:
        return (
            self.principal_amount
            + self.flash_fee_amount
            + self.protocol_rounding_amount
        )

    def to_json(self) -> dict[str, str]:
        return {
            "asset_id": self.asset_id,
            "principal_amount": str(self.principal_amount),
            "flash_fee_amount": str(self.flash_fee_amount),
            "protocol_rounding_amount": str(self.protocol_rounding_amount),
            "required_repayment_amount": str(self.required_repayment_amount),
        }


@dataclass(frozen=True, slots=True)
class PR118TypedCostLedger:
    """Typed, integer-only multi-asset ledger for one evaluated route size."""

    min_out: PR118AssetAmount
    flash_repayment: PR118FlashRepaymentTerms
    entries: tuple[PR118CostLedgerEntry, ...] = ()
    route_provenance_hash: str | None = None
    schema_version: str = PR118_LEDGER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR118_LEDGER_SCHEMA_VERSION:
            raise CapitalEngineError("unsupported PR-118 ledger schema")
        if not isinstance(self.min_out, PR118AssetAmount):
            raise CapitalEngineError("min_out must be PR118AssetAmount")
        if not isinstance(self.flash_repayment, PR118FlashRepaymentTerms):
            raise CapitalEngineError(
                "flash_repayment must be PR118FlashRepaymentTerms"
            )
        if self.min_out.asset_id != self.flash_repayment.asset_id:
            raise CapitalEngineError(
                "min_out and flash repayment must share an asset without a "
                "verified conversion contract"
            )
        object.__setattr__(self, "entries", tuple(self.entries))
        for entry in self.entries:
            if not isinstance(entry, PR118CostLedgerEntry):
                raise CapitalEngineError("entries must be PR118CostLedgerEntry")
            if entry.kind in {
                PR118CostComponentKind.PRINCIPAL,
                PR118CostComponentKind.FLASH_FEE,
                PR118CostComponentKind.PROTOCOL_ROUNDING,
            }:
                raise CapitalEngineError(
                    "principal, flash fee and protocol rounding belong only in "
                    "flash_repayment"
                )
        if self.route_provenance_hash is not None:
            object.__setattr__(
                self,
                "route_provenance_hash",
                _sha256(self.route_provenance_hash, "route_provenance_hash"),
            )

    @property
    def required_repayment_amount(self) -> int:
        return self.flash_repayment.required_repayment_amount

    @property
    def asset_ids(self) -> tuple[str, ...]:
        assets = {self.min_out.asset_id, self.flash_repayment.asset_id}
        for entry in self.entries:
            assets.add(entry.asset_id)
        return tuple(sorted(assets))

    def net_cost_by_asset(self) -> Mapping[str, int]:
        costs: dict[str, int] = {}
        for entry in self.entries:
            costs[entry.asset_id] = costs.get(entry.asset_id, 0) + entry.signed_amount()
        return dict(sorted(costs.items()))

    def conservative_net_amount(self) -> int:
        net = self.min_out.amount - self.required_repayment_amount
        for entry in self.entries:
            if entry.asset_id != self.min_out.asset_id:
                raise CapitalEngineError(
                    "non-settlement asset cost requires a verified conversion contract"
                )
            net -= entry.signed_amount()
        return net

    def to_capital_candidate(
        self,
        *,
        candidate_id: str,
        native_costs: NativeCostBreakdown,
        message_hash: str | None = None,
    ) -> CapitalCandidate:
        """Convert native/wSOL settlement economics into the existing gate type.

        `CapitalCandidate.protocol_fee_lamports` is intentionally set to zero
        because the PR-118 ledger places flash fee and protocol rounding inside
        `flash_repayment`, preventing double-counting by the legacy PR-032 gate.
        """

        if self.min_out.asset_id not in _NATIVE_SETTLEMENT_ASSETS:
            raise CapitalEngineError(
                "capital candidate conversion requires native/wSOL settlement"
            )
        slippage = self._single_asset_debit(PR118CostComponentKind.SLIPPAGE)
        uncertainty = self._single_asset_debit(PR118CostComponentKind.UNCERTAINTY)
        return CapitalCandidate(
            candidate_id=candidate_id,
            guaranteed_min_out_lamports=self.min_out.amount,
            flash_repayment_lamports=self.required_repayment_amount,
            requested_flash_loan_lamports=self.flash_repayment.principal_amount,
            native_costs=native_costs,
            protocol_fee_lamports=0,
            slippage_buffer_lamports=slippage,
            uncertainty_buffer_lamports=uncertainty,
            message_hash=message_hash,
        )

    def _single_asset_debit(self, kind: PR118CostComponentKind) -> int:
        total = 0
        for entry in self.entries:
            if entry.kind is not kind:
                continue
            if entry.asset_id != self.min_out.asset_id:
                raise CapitalEngineError(f"{kind.value} requires settlement asset")
            if entry.direction is not PR118LedgerDirection.DEBIT:
                raise CapitalEngineError(f"{kind.value} cannot be a credit")
            total += entry.amount
        return total

    def to_json(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class PR118SizingCandidateEvidence:
    """Candidate returned by an exact quote/build request for one amount."""

    amount_lamports: int
    candidate: CapitalCandidate
    quote_hashes: tuple[str, ...]
    route_id: str | None = None

    def __post_init__(self) -> None:
        _integer_amount(self.amount_lamports, "amount_lamports")
        if self.amount_lamports <= 0:
            raise CapitalEngineError("amount_lamports must be positive")
        if not isinstance(self.candidate, CapitalCandidate):
            raise CapitalEngineError("candidate must be CapitalCandidate")
        if self.candidate.requested_flash_loan_lamports != self.amount_lamports:
            raise CapitalEngineError("candidate amount does not match exact request")
        hashes = tuple(_sha256(item, "quote_hash") for item in self.quote_hashes)
        if not hashes:
            raise CapitalEngineError("at least one exact quote hash is required")
        object.__setattr__(self, "quote_hashes", hashes)
        if self.route_id is not None and not self.route_id.strip():
            raise CapitalEngineError("route_id cannot be empty")

    def evidence_hash(self) -> str:
        return _sha256_payload(
            {
                "amount_lamports": self.amount_lamports,
                "candidate_id": self.candidate.candidate_id,
                "quote_hashes": self.quote_hashes,
                "route_id": self.route_id,
            }
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "amount_lamports": str(self.amount_lamports),
            "candidate_id": self.candidate.candidate_id,
            "quote_hashes": list(self.quote_hashes),
            "route_id": self.route_id,
            "evidence_hash": self.evidence_hash(),
        }


@dataclass(frozen=True, slots=True)
class PR118SizingEvaluation:
    """Capital decision for one exact amount-coupled sizing point."""

    amount_lamports: int
    decision: CapitalDecision
    evidence: PR118SizingCandidateEvidence

    def __post_init__(self) -> None:
        _integer_amount(self.amount_lamports, "amount_lamports")
        if self.amount_lamports != self.evidence.amount_lamports:
            raise CapitalEngineError("evaluation amount must match evidence amount")

    @property
    def allowed(self) -> bool:
        return self.decision.allowed

    def to_json(self) -> dict[str, Any]:
        return {
            "amount_lamports": str(self.amount_lamports),
            "allowed": self.allowed,
            "reason": self.decision.reason.value,
            "candidate_id": self.decision.candidate_id,
            "conservative_net_profit_lamports": str(
                self.decision.conservative_net_profit_lamports
            ),
            "evidence": self.evidence.to_json(),
        }


@dataclass(frozen=True, slots=True)
class PR118NonMonotonicSizingResult:
    """Best admissible exact sizing point without monotonicity assumptions."""

    selected_amount_lamports: int | None
    selected: PR118SizingEvaluation | None
    evaluations: tuple[PR118SizingEvaluation, ...]
    stop_reason: PR118SizingStopReason
    schema_version: str = PR118_SIZING_SCHEMA_VERSION

    @property
    def allowed(self) -> bool:
        return self.selected is not None and self.selected.allowed

    @property
    def evaluated_amounts(self) -> tuple[int, ...]:
        return tuple(item.amount_lamports for item in self.evaluations)

    def to_json(self) -> dict[str, Any]:
        return _jsonable(self)


def build_pr118_amount_grid(
    *,
    lower_lamports: int,
    upper_lamports: int,
    max_points: int,
) -> tuple[int, ...]:
    """Build a bounded grid; this is intentionally not a binary search."""

    _integer_amount(lower_lamports, "lower_lamports")
    _integer_amount(upper_lamports, "upper_lamports")
    _integer_amount(max_points, "max_points")
    if lower_lamports <= 0:
        raise CapitalEngineError("lower_lamports must be positive")
    if upper_lamports < lower_lamports:
        raise CapitalEngineError("upper_lamports must be >= lower_lamports")
    if max_points <= 0:
        raise CapitalEngineError("max_points must be positive")
    if max_points == 1:
        return (lower_lamports,)

    span = upper_lamports - lower_lamports
    if span == 0:
        return (lower_lamports,)

    points = {
        lower_lamports,
        upper_lamports,
    }
    for index in range(1, max_points - 1):
        point = lower_lamports + (span * index) // (max_points - 1)
        points.add(point)
    return tuple(sorted(points))


def evaluate_pr118_non_monotonic_sizing(
    *,
    coordinator: DurableCapitalCoordinator,
    wallet_snapshot: WalletBalanceSnapshot,
    amounts_lamports: Iterable[int],
    candidate_factory: Callable[[int], PR118SizingCandidateEvidence],
    max_evaluations: int,
) -> PR118NonMonotonicSizingResult:
    """Evaluate exact points and optimize conservative net, not largest amount."""

    _integer_amount(max_evaluations, "max_evaluations")
    if max_evaluations <= 0:
        raise CapitalEngineError("max_evaluations must be positive")

    unique_amounts = _unique_amounts(amounts_lamports)
    if not unique_amounts:
        return PR118NonMonotonicSizingResult(
            selected_amount_lamports=None,
            selected=None,
            evaluations=(),
            stop_reason=PR118SizingStopReason.NO_POINTS,
        )

    evaluations: list[PR118SizingEvaluation] = []
    for amount in unique_amounts[:max_evaluations]:
        evidence = candidate_factory(amount)
        if not isinstance(evidence, PR118SizingCandidateEvidence):
            raise CapitalEngineError(
                "candidate_factory must return PR118SizingCandidateEvidence"
            )
        if evidence.amount_lamports != amount:
            raise CapitalEngineError("factory returned evidence for a different amount")
        decision = coordinator.evaluate(
            evidence.candidate,
            wallet_snapshot=wallet_snapshot,
        ).decision
        evaluations.append(
            PR118SizingEvaluation(
                amount_lamports=amount,
                decision=decision,
                evidence=evidence,
            )
        )

    selected = _best_allowed(evaluations)
    stop_reason = (
        PR118SizingStopReason.REQUEST_BUDGET_EXHAUSTED
        if len(unique_amounts) > len(evaluations)
        else PR118SizingStopReason.EVALUATED_ALL_POINTS
    )
    return PR118NonMonotonicSizingResult(
        selected_amount_lamports=None if selected is None else selected.amount_lamports,
        selected=selected,
        evaluations=tuple(evaluations),
        stop_reason=stop_reason,
    )


def _best_allowed(
    evaluations: Iterable[PR118SizingEvaluation],
) -> PR118SizingEvaluation | None:
    best: PR118SizingEvaluation | None = None
    for item in evaluations:
        if not item.allowed:
            continue
        if best is None:
            best = item
            continue
        if item.decision.conservative_net_profit_lamports > (
            best.decision.conservative_net_profit_lamports
        ):
            best = item
    return best


def _unique_amounts(amounts_lamports: Iterable[int]) -> tuple[int, ...]:
    amounts: set[int] = set()
    for amount in amounts_lamports:
        _integer_amount(amount, "amount_lamports")
        if amount <= 0:
            raise CapitalEngineError("amount_lamports must be positive")
        amounts.add(amount)
    return tuple(sorted(amounts))


def _asset_id(value: str) -> str:
    cleaned = value.strip().upper()
    if not _ASSET_ID_RE.fullmatch(cleaned):
        raise CapitalEngineError("asset_id must be a normalized asset symbol")
    return cleaned


def _integer_amount(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CapitalEngineError(f"{field} must be an integer amount")
    if value < 0:
        raise CapitalEngineError(f"{field} cannot be negative")


def _sha256(value: str, field: str) -> str:
    lowered = value.lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise CapitalEngineError(f"{field} must be a non-placeholder sha256")
    return lowered


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {
            item.name: _jsonable(getattr(value, item.name)) for item in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _stable_json(payload: Any) -> str:
    return json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


__all__ = [
    "PR118_LEDGER_SCHEMA_VERSION",
    "PR118_SIZING_SCHEMA_VERSION",
    "PR118AssetAmount",
    "PR118CostComponentKind",
    "PR118CostLedgerEntry",
    "PR118FlashRepaymentTerms",
    "PR118LedgerDirection",
    "PR118NonMonotonicSizingResult",
    "PR118SizingCandidateEvidence",
    "PR118SizingEvaluation",
    "PR118SizingStopReason",
    "PR118TypedCostLedger",
    "build_pr118_amount_grid",
    "evaluate_pr118_non_monotonic_sizing",
]
