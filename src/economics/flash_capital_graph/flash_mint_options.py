"""SX-02 TRANS-ISSUER: flash-mint vs lender-flashloan financing comparison.

Offline, advisory economic model extending the flash capital graph
vocabulary. ``graph.py`` remains the canonical capital owner; this module
adds a typed comparison between two financing shapes inside one settlement
domain:

* a protocol flash-mint (issuer mint/burn credit, ERC-3156-style terms), and
* a lender flashloan edge modeled on qualified ``FlashCapitalEdge``-like
  inputs.

Exactness rules
---------------
* Repayment is ``amount + fee`` in exact integer math. Flash-mint fees use
  the ERC-3156 reference floor rounding ``(amount * fee_bps) // 10_000``;
  lender fees use the capital edge's conservative ceiling rounding so a
  lender repayment is never understated.
* ``fee_bps=None`` is UNKNOWN and always produces a typed rejection; it is
  never treated as zero. Unknown capacity is likewise never coerced.
* Capacity provenance is declared through an explicit source-kind set; TVL
  proxies are not expressible, and observations whose age falls outside the
  declared freshness window produce a typed rejection.
* Same-transaction burn repayment must be proven before a flash-mint quote
  may claim the LOCAL_ATOMIC classification; without that proof the quote
  is blocked and can never win a comparison.

Safety
------
This module is offline and advisory only: it performs no live capacity
read, enables no provider, and contains no borrow, signing, sending or
execution path. Quotes are deterministic functions of pinned terms plus
the explicit ``now`` argument; fixtures are provenance declarations, never
live evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from src.assets.resolution.evidence import text

__all__ = [
    "CAPACITY_SOURCE_KINDS",
    "CANDIDATE_ATOMICITY",
    "FLASH_MINT_FEE_ROUNDING",
    "INVARIANTS",
    "LENDER_FEE_ROUNDING",
    "LOCAL_ATOMIC_ATOMICITY",
    "LOCAL_ATOMIC_UNPROVEN_ATOMICITY",
    "MAX_BPS",
    "OPTION_KINDS",
    "FinancingBlockReason",
    "FinancingComparison",
    "FinancingQuote",
    "FinancingRejection",
    "FlashMintFinancingOption",
    "FlashMintTerms",
    "LenderFlashLoanOption",
    "ProtocolDocsPin",
    "compare_options",
]

MAX_BPS = 10_000

LOCAL_ATOMIC_ATOMICITY = "LOCAL_ATOMIC"
LOCAL_ATOMIC_UNPROVEN_ATOMICITY = "LOCAL_ATOMIC_UNPROVEN"
CANDIDATE_ATOMICITY = "LOCAL_ATOMIC_CANDIDATE"

FLASH_MINT_FEE_ROUNDING = "floor_bps_erc3156"
LENDER_FEE_ROUNDING = "ceil_bps_flash_capital_edge"

OPTION_KINDS = ("flash_mint", "lender_flashloan")

# Explicit provenance kinds for capacity observations. The set deliberately
# has no TVL-derived kind: a TVL figure is not flash capacity and cannot be
# declared here (acceptance invariant "no TVL-as-capacity").
CAPACITY_SOURCE_KINDS = frozenset(
    {"protocol_docs", "chain_state_read", "sdk_snapshot", "dossier_fixture"}
)

# Mirrors the qualified capital provider set enforced by FlashCapitalEdge in
# graph.py (the canonical owner); kept in lockstep with its chain mapping.
QUALIFIED_LENDER_PROVIDERS = frozenset(
    {"project0", "marginfi", "kamino", "navi", "deepbook", "scallop"}
)
SOLANA_LENDER_PROVIDERS = frozenset({"project0", "marginfi", "kamino"})
SUI_LENDER_PROVIDERS = frozenset({"navi", "deepbook", "scallop"})

INVARIANTS: tuple[str, ...] = (
    "no_tvl_proxies",
    "no_cross_domain_funding",
    "unknown_never_coerced",
)


class FinancingBlockReason(StrEnum):
    """Typed rejection reasons; unknown state blocks, it never coerces."""

    MINT_FEE_UNKNOWN = "mint_fee_unknown"
    MINT_CAP_EXCEEDED = "mint_cap_exceeded"
    CALLER_INELIGIBLE = "caller_ineligible"
    CALLER_ELIGIBILITY_UNPROVEN = "caller_eligibility_unproven"
    RECEIVER_CALLBACK_UNSUPPORTED = "receiver_callback_unsupported"
    SAME_TX_REPAY_UNPROVEN = "same_tx_repay_unproven"
    CAPACITY_STALE = "capacity_stale"
    CAPACITY_UNKNOWN = "capacity_unknown"
    LENDER_FEE_UNKNOWN = "lender_fee_unknown"
    LENDER_CAPACITY_UNKNOWN = "lender_capacity_unknown"
    LENDER_CAPACITY_STALE = "lender_capacity_stale"
    LENDER_CAPACITY_EXCEEDED = "lender_capacity_exceeded"


def _positive_float(value: float, field: str) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{field} must be a finite positive number")
    return float(value)


def _non_negative_int(value: int, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _bps(value: int, field: str) -> int:
    if type(value) is not int or not 0 <= value < MAX_BPS:
        raise ValueError(
            f"{field} must be None (unknown) or an integer in [0, {MAX_BPS})"
        )
    return value


@dataclass(frozen=True, slots=True)
class ProtocolDocsPin:
    """Immutable protocol documentation pin (offline provenance)."""

    url: str
    version: str
    license: str
    accessed_at: float

    def __post_init__(self) -> None:
        for value in (self.url, self.version, self.license):
            text(value)
        _positive_float(self.accessed_at, "protocol_docs_pin.accessed_at")


@dataclass(frozen=True, slots=True)
class FinancingRejection:
    """Typed rejection; a blocked option can never win a comparison."""

    reason: FinancingBlockReason
    detail: str

    def __post_init__(self) -> None:
        text(self.detail)


@dataclass(frozen=True, slots=True)
class FinancingQuote:
    """Typed financing outcome for one option at one amount and time.

    ``fee_amount``/``repayment_amount`` are ``None`` exactly when the fee
    was unknown; populated values are exact integers and satisfy
    ``repayment == amount + fee``. ``blockers`` non-empty means the option
    is not actionable for this amount, whatever numbers it carries.
    """

    option_kind: str
    provider: str
    asset: str
    settlement_domain: str
    amount: int
    fee_amount: Optional[int]
    repayment_amount: Optional[int]
    fee_rounding: str
    capacity_limit: Optional[int]
    capacity_source: Optional[str]
    freshness_margin_s: Optional[float]
    atomicity_class: str
    atomicity_proof: Optional[str]
    blockers: tuple[FinancingRejection, ...]
    source_revision: str
    evaluated_at: float

    def __post_init__(self) -> None:
        for value in (
            self.option_kind,
            self.provider,
            self.asset,
            self.settlement_domain,
            self.fee_rounding,
            self.source_revision,
        ):
            text(value)
        if self.option_kind not in OPTION_KINDS:
            raise ValueError("unknown financing option kind")
        if self.fee_rounding not in {
            FLASH_MINT_FEE_ROUNDING,
            LENDER_FEE_ROUNDING,
        }:
            raise ValueError("unknown fee rounding declaration")
        if type(self.amount) is not int or self.amount <= 0:
            raise ValueError("positive integer financing amount required")
        for blocker in self.blockers:
            if not isinstance(blocker, FinancingRejection):
                raise ValueError("blockers must be FinancingRejection values")
        if (self.repayment_amount is None) != (self.fee_amount is None):
            raise ValueError("fee and repayment must be provided together")
        if self.fee_amount is not None:
            if type(self.fee_amount) is not int or self.fee_amount < 0:
                raise ValueError("fee must be a non-negative integer")
            if self.repayment_amount != self.amount + self.fee_amount:
                raise ValueError(
                    "repayment must equal amount plus fee in exact integer math"
                )
        if self.capacity_limit is not None and (
            type(self.capacity_limit) is not int or self.capacity_limit < 0
        ):
            raise ValueError("capacity limit must be a non-negative integer")
        if self.atomicity_class not in (
            LOCAL_ATOMIC_ATOMICITY,
            LOCAL_ATOMIC_UNPROVEN_ATOMICITY,
        ):
            raise ValueError("unsupported quote atomicity classification")
        if (self.atomicity_class == LOCAL_ATOMIC_ATOMICITY) != (
            self.atomicity_proof is not None
        ):
            raise ValueError(
                "LOCAL_ATOMIC classification requires an atomicity proof; "
                "unproven classification must carry none"
            )
        _positive_float(self.evaluated_at, "evaluated_at")

    @property
    def is_actionable(self) -> bool:
        return not self.blockers and self.repayment_amount is not None


@dataclass(frozen=True, slots=True)
class FlashMintTerms:
    """Declared flash-mint terms with offline provenance pins.

    ``fee_bps=None`` means the fee is UNKNOWN and blocks every quote; it is
    never read as zero. An explicitly documented ``fee_bps=0`` is honored
    because it is pinned, not assumed.

    ``caller_eligibility=True`` without ``eligibility_evidence`` is an
    unproven state: construction is allowed (unknown stays representable)
    but evaluation blocks with ``caller_eligibility_unproven``.

    Capacity is bounded by the pinned protocol ``max_mint_cap`` (timeless
    protocol rule) and, when declared, by a provenance-pinned
    ``observed_capacity`` that expires after ``evidence_freshness_s``.
    TVL-derived sources cannot be declared.

    ``receiver_callback_supported`` mirrors the ``same_tx_burn_required``/
    ``same_tx_burn_proven`` pair: a required receiver callback that this
    integration does not support blocks the route.
    """

    protocol: str
    asset: str
    settlement_domain: str
    source_revision: str
    protocol_docs_pin: ProtocolDocsPin
    caller_eligibility: bool
    receiver_callback_required: bool
    same_tx_burn_required: bool
    same_tx_burn_proven: bool
    eligibility_evidence: Optional[str] = None
    receiver_callback_supported: bool = False
    fee_bps: Optional[int] = None
    max_mint_cap: Optional[int] = None
    observed_capacity: Optional[int] = None
    capacity_source: Optional[str] = None
    capacity_observed_at: Optional[float] = None
    evidence_freshness_s: Optional[float] = None

    def __post_init__(self) -> None:
        for value in (
            self.protocol,
            self.asset,
            self.settlement_domain,
            self.source_revision,
        ):
            text(value)
        if not isinstance(self.protocol_docs_pin, ProtocolDocsPin):
            raise ValueError("protocol docs pin required")
        for flag in (
            self.caller_eligibility,
            self.receiver_callback_required,
            self.receiver_callback_supported,
            self.same_tx_burn_required,
            self.same_tx_burn_proven,
        ):
            if type(flag) is not bool:
                raise ValueError("boolean terms required")
        if self.eligibility_evidence is not None:
            text(self.eligibility_evidence)
        if self.fee_bps is not None:
            _bps(self.fee_bps, "fee_bps")
        if self.max_mint_cap is not None:
            _non_negative_int(self.max_mint_cap, "max_mint_cap")
        if self.observed_capacity is not None:
            _non_negative_int(self.observed_capacity, "observed_capacity")
            if (
                self.capacity_source is None
                or self.capacity_observed_at is None
                or self.evidence_freshness_s is None
            ):
                raise ValueError(
                    "observed capacity requires complete provenance: "
                    "source kind, observation timestamp and freshness window"
                )
            if self.capacity_source not in CAPACITY_SOURCE_KINDS:
                raise ValueError(
                    "capacity_source must declare a known provenance kind; "
                    "TVL proxies are not accepted"
                )
            object.__setattr__(
                self,
                "capacity_observed_at",
                _positive_float(self.capacity_observed_at, "capacity_observed_at"),
            )
            object.__setattr__(
                self,
                "evidence_freshness_s",
                _positive_float(self.evidence_freshness_s, "evidence_freshness_s"),
            )
        elif (
            self.capacity_source is not None
            or self.capacity_observed_at is not None
            or self.evidence_freshness_s is not None
        ):
            raise ValueError("capacity provenance requires an observed_capacity value")


@dataclass(frozen=True, slots=True)
class FlashMintFinancingOption:
    """Advisory flash-mint financing option; evaluate() is pure."""

    terms: FlashMintTerms

    @property
    def option_kind(self) -> str:
        return "flash_mint"

    @property
    def settlement_domain(self) -> str:
        return self.terms.settlement_domain

    @property
    def provider(self) -> str:
        return self.terms.protocol

    def evaluate(self, amount: int, *, now: float) -> FinancingQuote:
        """Return the typed financing quote for ``amount`` at ``now``.

        Deterministic and idempotent for identical arguments. Gates run in
        a fixed order: eligibility, receiver callback, fee knowledge,
        capacity freshness/bounds, same-tx repayment proof. Unknown and
        unproven states block; they never coerce.
        """
        if type(amount) is not int or amount <= 0:
            raise ValueError("positive integer mint amount required")
        if not math.isfinite(now) or now <= 0:
            raise ValueError("finite positive evaluation time required")
        terms = self.terms
        blockers: list[FinancingRejection] = []

        if not terms.caller_eligibility:
            blockers.append(
                FinancingRejection(
                    FinancingBlockReason.CALLER_INELIGIBLE,
                    "caller is not eligible for this flash-mint protocol",
                )
            )
        elif terms.eligibility_evidence is None:
            blockers.append(
                FinancingRejection(
                    FinancingBlockReason.CALLER_ELIGIBILITY_UNPROVEN,
                    "eligibility is claimed without recorded evidence",
                )
            )

        if terms.receiver_callback_required and (not terms.receiver_callback_supported):
            blockers.append(
                FinancingRejection(
                    FinancingBlockReason.RECEIVER_CALLBACK_UNSUPPORTED,
                    "protocol requires a receiver callback this "
                    "integration does not support",
                )
            )

        fee: Optional[int] = None
        if terms.fee_bps is None:
            blockers.append(
                FinancingRejection(
                    FinancingBlockReason.MINT_FEE_UNKNOWN,
                    "mint fee basis points are unknown; unknown fee is "
                    "never treated as zero",
                )
            )
        else:
            # ERC-3156 reference floor rounding in exact integer math.
            fee = (amount * terms.fee_bps) // MAX_BPS

        capacity_limit: Optional[int] = None
        freshness_margin: Optional[float] = None
        if (
            terms.observed_capacity is not None
            and terms.capacity_observed_at is not None
            and terms.evidence_freshness_s is not None
        ):
            age = now - terms.capacity_observed_at
            if 0 <= age <= terms.evidence_freshness_s:
                freshness_margin = terms.evidence_freshness_s - age
                capacity_limit = terms.observed_capacity
            else:
                blockers.append(
                    FinancingRejection(
                        FinancingBlockReason.CAPACITY_STALE,
                        "observed capacity age is outside the declared "
                        "freshness window",
                    )
                )
        if terms.max_mint_cap is not None:
            if capacity_limit is None:
                capacity_limit = terms.max_mint_cap
            else:
                capacity_limit = min(capacity_limit, terms.max_mint_cap)
        if capacity_limit is not None:
            if amount > capacity_limit:
                blockers.append(
                    FinancingRejection(
                        FinancingBlockReason.MINT_CAP_EXCEEDED,
                        f"amount {amount} exceeds binding mint capacity "
                        f"{capacity_limit}",
                    )
                )
        elif terms.observed_capacity is None:
            blockers.append(
                FinancingRejection(
                    FinancingBlockReason.CAPACITY_UNKNOWN,
                    "no pinned mint cap and no observed capacity; unknown "
                    "capacity is never treated as unlimited or zero",
                )
            )

        if terms.same_tx_burn_proven:
            atomicity_class = LOCAL_ATOMIC_ATOMICITY
            atomicity_proof = (
                f"flash_mint_same_tx_burn:{terms.protocol}:" f"{terms.source_revision}"
            )
        else:
            # No proof of same-transaction repayment closure, whether or
            # not the protocol flags the burn as required: the LOCAL_ATOMIC
            # classification stays blocked (fail closed).
            atomicity_class = LOCAL_ATOMIC_UNPROVEN_ATOMICITY
            atomicity_proof = None
            blockers.append(
                FinancingRejection(
                    FinancingBlockReason.SAME_TX_REPAY_UNPROVEN,
                    "same-transaction burn repayment is not proven; "
                    "LOCAL_ATOMIC classification is blocked",
                )
            )

        return FinancingQuote(
            option_kind=self.option_kind,
            provider=terms.protocol,
            asset=terms.asset,
            settlement_domain=terms.settlement_domain,
            amount=amount,
            fee_amount=fee,
            repayment_amount=None if fee is None else amount + fee,
            fee_rounding=FLASH_MINT_FEE_ROUNDING,
            capacity_limit=capacity_limit,
            capacity_source=terms.capacity_source,
            freshness_margin_s=freshness_margin,
            atomicity_class=atomicity_class,
            atomicity_proof=atomicity_proof,
            blockers=tuple(blockers),
            source_revision=terms.source_revision,
            evaluated_at=now,
        )


@dataclass(frozen=True, slots=True)
class LenderFlashLoanOption:
    """Thin adapter over FlashCapitalEdge-like financing inputs.

    ``graph.py`` owns the canonical edge type; this adapter mirrors its
    construction rules: only qualified capital providers, provider/chain
    agreement, and refusal of any non-LOCAL_ATOMIC_CANDIDATE atomicity
    class ("candidate is not authorization"). Fee uses the capital edge's
    conservative ceiling rounding so a lender repayment is never
    understated. No live read and no borrowing happens here.
    """

    provider: str
    asset: str
    settlement_domain: str
    atomicity_class: str
    source_revision: str
    fee_bps: Optional[int] = None
    capacity: Optional[int] = None
    capacity_source: Optional[str] = None
    capacity_observed_at: Optional[float] = None
    evidence_freshness_s: Optional[float] = None

    def __post_init__(self) -> None:
        for value in (
            self.provider,
            self.asset,
            self.settlement_domain,
            self.atomicity_class,
            self.source_revision,
        ):
            text(value)
        if self.provider not in QUALIFIED_LENDER_PROVIDERS:
            raise ValueError("unqualified capital provider")
        if (
            self.provider in SOLANA_LENDER_PROVIDERS
            and self.settlement_domain != "solana"
            or self.provider in SUI_LENDER_PROVIDERS
            and self.settlement_domain != "sui"
        ):
            raise ValueError("capital provider/chain mismatch")
        if self.atomicity_class != CANDIDATE_ATOMICITY:
            raise ValueError(
                "unsupported capital atomicity; candidate is not authorization"
            )
        if self.fee_bps is not None:
            _bps(self.fee_bps, "fee_bps")
        if self.capacity is not None:
            _non_negative_int(self.capacity, "capacity")
            if (
                self.capacity_source is None
                or self.capacity_observed_at is None
                or self.evidence_freshness_s is None
            ):
                raise ValueError(
                    "lender capacity requires complete provenance: source "
                    "kind, observation timestamp and freshness window"
                )
            if self.capacity_source not in CAPACITY_SOURCE_KINDS:
                raise ValueError(
                    "capacity_source must declare a known provenance kind; "
                    "TVL proxies are not accepted"
                )
            object.__setattr__(
                self,
                "capacity_observed_at",
                _positive_float(self.capacity_observed_at, "capacity_observed_at"),
            )
            object.__setattr__(
                self,
                "evidence_freshness_s",
                _positive_float(self.evidence_freshness_s, "evidence_freshness_s"),
            )
        elif (
            self.capacity_source is not None
            or self.capacity_observed_at is not None
            or self.evidence_freshness_s is not None
        ):
            raise ValueError("lender capacity provenance requires a capacity value")

    @property
    def option_kind(self) -> str:
        return "lender_flashloan"

    def evaluate(self, amount: int, *, now: float) -> FinancingQuote:
        """Return the typed financing quote for ``amount`` at ``now``."""
        if type(amount) is not int or amount <= 0:
            raise ValueError("positive integer financing amount required")
        if not math.isfinite(now) or now <= 0:
            raise ValueError("finite positive evaluation time required")
        blockers: list[FinancingRejection] = []

        fee: Optional[int] = None
        if self.fee_bps is None:
            blockers.append(
                FinancingRejection(
                    FinancingBlockReason.LENDER_FEE_UNKNOWN,
                    "lender fee basis points are unknown; unknown fee is "
                    "never treated as zero",
                )
            )
        else:
            # Conservative ceiling rounding, mirroring FlashCapitalEdge.fee.
            fee = (amount * self.fee_bps + MAX_BPS - 1) // MAX_BPS

        capacity_limit: Optional[int] = None
        freshness_margin: Optional[float] = None
        if (
            self.capacity is not None
            and self.capacity_observed_at is not None
            and self.evidence_freshness_s is not None
        ):
            age = now - self.capacity_observed_at
            if 0 <= age <= self.evidence_freshness_s:
                freshness_margin = self.evidence_freshness_s - age
                capacity_limit = self.capacity
            else:
                blockers.append(
                    FinancingRejection(
                        FinancingBlockReason.LENDER_CAPACITY_STALE,
                        "lender capacity observation is outside the "
                        "declared freshness window",
                    )
                )
        if capacity_limit is not None:
            if amount > capacity_limit:
                blockers.append(
                    FinancingRejection(
                        FinancingBlockReason.LENDER_CAPACITY_EXCEEDED,
                        f"amount {amount} exceeds observed lender capacity "
                        f"{capacity_limit}",
                    )
                )
        elif self.capacity is None:
            blockers.append(
                FinancingRejection(
                    FinancingBlockReason.LENDER_CAPACITY_UNKNOWN,
                    "lender capacity is unknown; unknown capacity is "
                    "never treated as unlimited or zero",
                )
            )

        return FinancingQuote(
            option_kind=self.option_kind,
            provider=self.provider,
            asset=self.asset,
            settlement_domain=self.settlement_domain,
            amount=amount,
            fee_amount=fee,
            repayment_amount=None if fee is None else amount + fee,
            fee_rounding=LENDER_FEE_ROUNDING,
            capacity_limit=capacity_limit,
            capacity_source=self.capacity_source,
            freshness_margin_s=freshness_margin,
            atomicity_class=LOCAL_ATOMIC_ATOMICITY,
            atomicity_proof=(
                f"flash_capital_edge:{self.provider}:{self.asset}:"
                f"{CANDIDATE_ATOMICITY}"
            ),
            blockers=tuple(blockers),
            source_revision=self.source_revision,
            evaluated_at=now,
        )


def _selection_key(quote: FinancingQuote) -> tuple[int, float, str, str]:
    """Deterministic winner key: repayment asc, freshness desc, revision.

    A quote without observed-evidence freshness (protocol-cap-only mint)
    ranks as least fresh on ties. The final option-kind component keeps the
    order total so comparison results are fully deterministic.
    """
    if quote.repayment_amount is None:
        raise ValueError("selection requires a computed repayment")
    margin = 0.0 if quote.freshness_margin_s is None else quote.freshness_margin_s
    return (
        quote.repayment_amount,
        -margin,
        quote.source_revision,
        quote.option_kind,
    )


@dataclass(frozen=True, slots=True)
class FinancingComparison:
    """Deterministic flash-mint vs lender comparison for one amount.

    ``winner_kind`` is ``None`` exactly when no compared option is
    actionable. A blocked option can never win. ``selection_key`` records
    the winning (repayment, -freshness_margin, source_revision,
    option_kind) tuple for replay.
    """

    amount: int
    evaluated_at: float
    settlement_domain: str
    lender_quote: FinancingQuote
    flash_mint_quote: FinancingQuote
    winner_kind: Optional[str]
    winner_reason: str
    selection_key: Optional[tuple[int, float, str, str]]
    invariants: tuple[str, ...] = INVARIANTS

    def __post_init__(self) -> None:
        if type(self.amount) is not int or self.amount <= 0:
            raise ValueError("positive integer comparison amount required")
        _positive_float(self.evaluated_at, "evaluated_at")
        text(self.settlement_domain)
        text(self.winner_reason)
        for quote in (self.lender_quote, self.flash_mint_quote):
            if quote.settlement_domain != self.settlement_domain:
                raise ValueError("comparison quotes must share one settlement domain")
            if quote.amount != self.amount:
                raise ValueError("comparison quotes must evaluate one amount")
        if (self.winner_kind is None) != (self.selection_key is None):
            raise ValueError("winner and selection key are provided together")
        if self.winner_kind is None:
            return
        if self.winner_kind not in (
            self.lender_quote.option_kind,
            self.flash_mint_quote.option_kind,
        ):
            raise ValueError("winner must be one of the compared options")
        winner = (
            self.lender_quote
            if self.lender_quote.option_kind == self.winner_kind
            else self.flash_mint_quote
        )
        if not winner.is_actionable:
            raise ValueError("a blocked option can never win")
        if self.selection_key != _selection_key(winner):
            raise ValueError("selection key does not match the winner")


def compare_options(
    lender: LenderFlashLoanOption,
    flash_mint: FlashMintFinancingOption,
    amount: int,
    *,
    now: float,
) -> FinancingComparison:
    """Compare one lender edge and one flash-mint at one amount and time.

    Financing is valid only within one settlement domain: options from
    different domains are refused outright (no cross-domain funding).
    Winner selection is deterministic: lowest repayment, then freshest
    evidence, then lexicographic source revision, then option kind. A
    blocked option can never win; if nothing is actionable the comparison
    reports no winner instead of picking a blocker.
    """
    if not isinstance(lender, LenderFlashLoanOption):
        raise ValueError("lender option must be a LenderFlashLoanOption")
    if not isinstance(flash_mint, FlashMintFinancingOption):
        raise ValueError("flash-mint option must be a FlashMintFinancingOption")
    if lender.settlement_domain != flash_mint.settlement_domain:
        raise ValueError(
            "cross-domain financing is not permitted; financing is valid "
            "only within one settlement domain"
        )
    lender_quote = lender.evaluate(amount, now=now)
    mint_quote = flash_mint.evaluate(amount, now=now)
    actionable = [quote for quote in (lender_quote, mint_quote) if quote.is_actionable]
    winner: Optional[FinancingQuote] = None
    winner_reason: str
    selection_key: Optional[tuple[int, float, str, str]] = None
    if not actionable:
        winner_reason = "no_actionable_option"
    elif len(actionable) == 1:
        winner = actionable[0]
        selection_key = _selection_key(winner)
        winner_reason = "only_actionable_option"
    else:
        first, second = sorted(actionable, key=_selection_key)
        first_key = _selection_key(first)
        second_key = _selection_key(second)
        winner = first
        selection_key = first_key
        if first_key[0] != second_key[0]:
            winner_reason = "repayment_asc"
        elif first_key[1] != second_key[1]:
            winner_reason = "freshness_desc"
        elif first_key[2] != second_key[2]:
            winner_reason = "source_revision_lexicographic"
        else:
            winner_reason = "option_kind_lexicographic"
    return FinancingComparison(
        amount=amount,
        evaluated_at=now,
        settlement_domain=lender.settlement_domain,
        lender_quote=lender_quote,
        flash_mint_quote=mint_quote,
        winner_kind=None if winner is None else winner.option_kind,
        winner_reason=winner_reason,
        selection_key=selection_key,
    )
