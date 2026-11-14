"""SX-08 utilization/rate-curve + refinance classification model (RESEARCH_ONLY).

Deterministic, offline model of lending-market utilization/rate curves and
debt-refinance opportunity evaluation. This module is RESEARCH ONLY and its
refusals are part of its contract:

- it performs no network or file I/O, no live rate/oracle reads, no provider
  enablement, no signing, sending, borrowing or execution of any kind; every
  number it produces is advisory research output, never an execution
  authority;
- every curve parameter is ``Optional``. Any missing parameter yields the
  typed rejection ``curve_parameters_unknown`` and NO rate is produced;
  parameters are never defaulted to zero ("unknown is not zero");
- all arithmetic is exact integer/rational arithmetic (``fractions.Fraction``,
  the ``Rational`` alias of :mod:`src.lending_indexer.models`). ``float``
  inputs are rejected outright because binary floating point cannot
  represent decimal rate parameters exactly;
- a supplied utilization above 1 is rejected with
  ``utilization_above_one`` (a negative one with ``utilization_negative``);
- refinance classification is separated and enforced:
  ``RefinanceKind.INTRA_TX_ATOMIC`` (flashloan-bridgeable) requires proven
  injected financing terms plus same-transaction postcondition flags, while
  ``RefinanceKind.MULTI_PERIOD_CARRY`` is always ``HEDGED_NON_ATOMIC``,
  records funding/withdrawal risk, and flash principal can never finance it
  (attaching flash financing raises ``FlashFinancingNotAllowedError``);
- projected interest deltas are computed over an explicit horizon given as
  data (integer seconds and/or integer blocks with an integer seconds-per-
  block factor); a missing horizon yields ``horizon_unprovided``;
- switch-cost fields (flash fee via injected financing terms, exit fee,
  entry fee) are ``Optional``. An unknown cost is never treated as zero: it
  is excluded from the profit arithmetic, flagged by name, and prevents a
  candidate conclusion (``switch_costs_unknown``) because unknown costs can
  never make a candidate look better;
- the post-switch health factor (``hf_after``) never comes from this model:
  it is read from an injected ``HealthFactorProvider`` result computed
  externally. A missing/unproven result yields
  ``health_factor_unproven`` whenever a positive-saving candidate would
  otherwise be concluded. Collateral double-counting is prevented by
  unique position keys: a duplicate key raises ``DuplicatePositionKeyError``;
- a non-positive net saving over known costs yields the typed
  ``RefinanceDecisionStatus.NO_TRADE`` result, not an exception.

Health-factor vocabulary is aligned with (not modified):
``src.lending_indexer.models.RiskAssessment.health_factor`` /
``src.lending_indexer.risk.health_factor`` — a health factor is a
``Rational`` (``Fraction``) or ``None`` when unproven.

Design input: OP-10 "Debt refinance and collateral swap"
(docs/web3-market-scale/design-input/25_OPPORTUNITY_ATLAS_RU.md;
class SERVICE_OR_COST_SAVING, flash role INTRA_TX_BRIDGE, "new debt is
collateralized funding, not flashloan profit").
Family: CREDIT-RATE (HEDGED_NON_ATOMIC) per
docs/strategy-expansion/2026-11-14/STRATEGY_ACCEPTANCE_MATRIX.json.

Not proven by this module: any live utilization observation, any
protocol-specific curve parameter pin, any actual savings. Curve parameters
must come from per-protocol offline dossiers before any of this is evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from typing import Optional, Protocol, Sequence, Tuple

from .models import Rational

EXECUTION_CLASS = "RESEARCH_ONLY"
SUBMISSION_ENABLED = False

SECONDS_PER_YEAR = 31_536_000  # 365d × 24h × 60m × 60s, exact integer

CurveParameter = Rational  # exact rate/amount parameter (int or Fraction)


class RateCurveError(Exception):
    """Base class for programming errors raised by the SX-08 model."""


class DuplicatePositionKeyError(RateCurveError):
    """Position keys must be unique so collateral is never double counted."""


class FlashFinancingNotAllowedError(RateCurveError):
    """Flash principal cannot finance a multi-period carry position."""


class RateCurveRejection(str, Enum):
    """Typed rejection codes. A rejection value is data, not an exception."""

    CURVE_PARAMETERS_UNKNOWN = "curve_parameters_unknown"
    UTILIZATION_ABOVE_ONE = "utilization_above_one"
    UTILIZATION_NEGATIVE = "utilization_negative"
    HORIZON_UNPROVIDED = "horizon_unprovided"
    SWITCH_COSTS_UNKNOWN = "switch_costs_unknown"
    FLASH_FINANCING_UNPROVEN = "flash_financing_unproven"
    FLASH_FEE_UNKNOWN = "flash_fee_unknown"
    REPAYMENT_UNPROVEN = "repayment_unproven"
    HEALTH_FACTOR_UNPROVEN = "health_factor_unproven"


class RefinanceKind(str, Enum):
    """Refinance classification; the two kinds are strictly separated."""

    INTRA_TX_ATOMIC = "intra_tx_atomic"
    MULTI_PERIOD_CARRY = "multi_period_carry"


class RefinanceDecisionStatus(str, Enum):
    """Outcome of a refinance evaluation. NO_TRADE is typed, not raised."""

    CANDIDATE = "candidate"
    NO_TRADE = "no_trade"
    BLOCKED = "blocked"


class ExecutionClass(str, Enum):
    """Execution-class vocabulary from the strategy catalog."""

    LOCAL_ATOMIC_CANDIDATE = "LOCAL_ATOMIC_CANDIDATE"
    HEDGED_NON_ATOMIC = "HEDGED_NON_ATOMIC"


def require_rational(value: object, field_name: str) -> Rational:
    """Coerce an exact numeric input to ``Fraction``; reject float drift.

    Accepts ``int``, ``Fraction`` and exact decimal ``str``. Rejects
    ``float`` (and ``bool``) with ``TypeError``: binary floating point
    cannot represent decimal rate parameters exactly and must never enter
    this model.
    """
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(
            f"{field_name}: float/bool rate inputs are rejected; supply an "
            "exact int, Fraction or decimal string (no float drift)"
        )
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, str):
        return Fraction(value)  # exact decimal string, e.g. "0.1" -> 1/10
    raise TypeError(
        f"{field_name}: unsupported type {type(value).__name__}; expected "
        "int, Fraction or exact decimal string"
    )


def require_nonnegative_rational(value: object, field_name: str) -> Rational:
    rational = require_rational(value, field_name)
    if rational < 0:
        raise ValueError(f"{field_name}: must be non-negative, got {rational}")
    return rational


class CurveSide(str, Enum):
    BORROW = "borrow"
    SUPPLY = "supply"


@dataclass(frozen=True)
class CurveProvenance:
    """Where the curve parameters came from (offline evidence reference)."""

    curve_id: str
    source: str  # e.g. an immutable offline dossier pin; never a live read
    note: str = ""


@dataclass(frozen=True)
class UtilizationRateCurve:
    """Two-slope (kinked) borrow curve with derived supply curve.

    Borrow APY as a function of utilization ``u`` (exact rational math)::

        0 <= u <= kink:  base_rate + slope_low  * (u / kink)
        kink < u <= 1:   base_rate + slope_low + slope_high
                                       * ((u - kink) / (1 - kink))

    Supply APY::

        supply_apy(u) = borrow_apy(u) * u * (1 - protocol_fee)

    ALL parameters are ``Optional``. A missing parameter is never defaulted
    to zero: evaluation yields the typed rejection
    ``curve_parameters_unknown`` instead of a rate. Provided values must be
    exact (int/Fraction/decimal string); floats are rejected.
    """

    base_rate: Optional[CurveParameter] = None
    slope_low: Optional[CurveParameter] = None
    slope_high: Optional[CurveParameter] = None
    kink_utilization: Optional[CurveParameter] = None
    protocol_fee: Optional[CurveParameter] = None
    provenance: Optional[CurveProvenance] = None

    def __post_init__(self) -> None:
        for name in (
            "base_rate",
            "slope_low",
            "slope_high",
            "kink_utilization",
            "protocol_fee",
        ):
            value = getattr(self, name)
            if value is not None:
                # frozen dataclass: normalize via object.__setattr__
                object.__setattr__(self, name, require_rational(value, name))
        if self.base_rate is not None:
            require_nonnegative_rational(self.base_rate, "base_rate")
        if self.slope_low is not None:
            require_nonnegative_rational(self.slope_low, "slope_low")
        if self.slope_high is not None:
            require_nonnegative_rational(self.slope_high, "slope_high")
        if self.kink_utilization is not None:
            kink = self.kink_utilization
            if not (0 < kink < 1):
                raise ValueError(
                    f"kink_utilization: must lie strictly between 0 and 1, got {kink}"
                )
        if self.protocol_fee is not None:
            fee = self.protocol_fee
            if not (0 <= fee <= 1):
                raise ValueError(f"protocol_fee: must lie in [0, 1], got {fee}")

    @property
    def curve_id(self) -> str:
        if self.provenance is not None:
            return self.provenance.curve_id
        return "unpinned_curve"

    def borrow_apy(self, utilization: CurveParameter) -> "CurveQuote":
        """Quote the borrow APY at ``utilization`` (exact, typed rejections)."""
        u = require_rational(utilization, "utilization")
        rejection = self._borrow_rejection(u)
        if rejection is not None:
            return CurveQuote(
                curve_id=self.curve_id,
                side=CurveSide.BORROW,
                utilization=u,
                apy=None,
                rejection=rejection,
            )
        assert self.base_rate is not None
        assert self.slope_low is not None
        assert self.slope_high is not None
        assert self.kink_utilization is not None
        kink = self.kink_utilization
        if u <= kink:
            apy = self.base_rate + self.slope_low * (u / kink)
        else:
            apy = (
                self.base_rate
                + self.slope_low
                + self.slope_high * ((u - kink) / (1 - kink))
            )
        return CurveQuote(
            curve_id=self.curve_id,
            side=CurveSide.BORROW,
            utilization=u,
            apy=apy,
            rejection=None,
        )

    def supply_apy(self, utilization: CurveParameter) -> "CurveQuote":
        """Quote the supply APY (borrow APY × u × (1 − protocol_fee))."""
        borrow_quote = self.borrow_apy(utilization)
        u = borrow_quote.utilization
        if borrow_quote.rejection is not None:
            return CurveQuote(
                curve_id=self.curve_id,
                side=CurveSide.SUPPLY,
                utilization=u,
                apy=None,
                rejection=borrow_quote.rejection,
            )
        if self.protocol_fee is None:
            return CurveQuote(
                curve_id=self.curve_id,
                side=CurveSide.SUPPLY,
                utilization=u,
                apy=None,
                rejection=RateCurveRejection.CURVE_PARAMETERS_UNKNOWN,
            )
        assert borrow_quote.apy is not None
        apy = borrow_quote.apy * u * (1 - self.protocol_fee)
        return CurveQuote(
            curve_id=self.curve_id,
            side=CurveSide.SUPPLY,
            utilization=u,
            apy=apy,
            rejection=None,
        )

    def _borrow_rejection(self, u: Rational) -> Optional[RateCurveRejection]:
        if u < 0:
            return RateCurveRejection.UTILIZATION_NEGATIVE
        if u > 1:
            return RateCurveRejection.UTILIZATION_ABOVE_ONE
        missing = [
            name
            for name in (
                "base_rate",
                "slope_low",
                "slope_high",
                "kink_utilization",
            )
            if getattr(self, name) is None
        ]
        if missing:
            return RateCurveRejection.CURVE_PARAMETERS_UNKNOWN
        return None


@dataclass(frozen=True)
class CurveQuote:
    """Exact curve quote or typed rejection (exactly one is present)."""

    curve_id: str
    side: CurveSide
    utilization: Rational
    apy: Optional[Rational]
    rejection: Optional[RateCurveRejection]

    def __post_init__(self) -> None:
        if (self.apy is None) == (self.rejection is None):
            raise ValueError(
                "CurveQuote invariant violated: exactly one of apy / "
                "rejection must be present"
            )

    @property
    def proven(self) -> bool:
        return self.rejection is None and self.apy is not None


@dataclass(frozen=True)
class DebtPosition:
    """An outstanding debt position identified by a unique key."""

    position_key: str
    asset: str
    balance: CurveParameter  # base units; integer-valued
    current_borrow_apr: CurveParameter  # decimal fraction per year, exact

    def __post_init__(self) -> None:
        if not self.position_key:
            raise ValueError("position_key: must be a non-empty identifier")
        if not self.asset:
            raise ValueError("asset: must be a non-empty identifier")
        balance = require_rational(self.balance, "balance")
        if balance < 0 or balance.denominator != 1:
            raise ValueError(
                f"balance: must be a non-negative integer amount of base "
                f"units, got {balance}"
            )
        object.__setattr__(self, "balance", balance)
        object.__setattr__(
            self,
            "current_borrow_apr",
            require_nonnegative_rational(self.current_borrow_apr, "current_borrow_apr"),
        )


@dataclass(frozen=True)
class FlashFinancingTerms:
    """Injected, externally proven flash-financing terms (never fetched)."""

    provider: str
    proven: bool
    flash_fee: Optional[CurveParameter] = None  # fraction of principal

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("provider: must be a non-empty identifier")
        if self.flash_fee is not None:
            object.__setattr__(
                self,
                "flash_fee",
                require_nonnegative_rational(self.flash_fee, "flash_fee"),
            )


@dataclass(frozen=True)
class SameTxPostconditions:
    """Same-transaction postcondition flags for intra-tx refinance."""

    repayment_proven: bool = False
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CarryRisk:
    """Funding/withdrawal risk recorded for multi-period carry."""

    funding_risk: str
    withdrawal_risk: str
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Horizon:
    """Explicit evaluation horizon given as data (integer seconds/blocks)."""

    seconds: Optional[int] = None
    blocks: Optional[int] = None
    seconds_per_block: Optional[int] = None

    def __post_init__(self) -> None:
        for name in ("seconds", "blocks", "seconds_per_block"):
            value = getattr(self, name)
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise TypeError(f"{name}: must be an int or None")
                if value < 0:
                    raise ValueError(f"{name}: must be non-negative, got {value}")

    def to_seconds(self) -> Optional[int]:
        """Resolve to exact integer seconds, or ``None`` when unprovided."""
        if self.seconds is not None:
            return self.seconds
        if self.blocks is not None and self.seconds_per_block is not None:
            return self.blocks * self.seconds_per_block
        return None


@dataclass(frozen=True)
class RateSpreadOpportunity:
    """Debt refinance opportunity: a debt position vs a target curve.

    For ``RefinanceKind.MULTI_PERIOD_CARRY`` flash financing is forbidden:
    attaching ``flash_financing`` raises ``FlashFinancingNotAllowedError``
    (carry is persistent collateralized funding, not flashloan profit).
    """

    opportunity_id: str
    position: DebtPosition
    refinance_kind: RefinanceKind
    target_curve: UtilizationRateCurve
    target_utilization: CurveParameter
    horizon: Horizon = field(default_factory=Horizon)
    flash_financing: Optional[FlashFinancingTerms] = None
    same_tx_postconditions: Optional[SameTxPostconditions] = None
    entry_fee: Optional[CurveParameter] = None  # fraction of principal
    exit_fee: Optional[CurveParameter] = None  # fraction of principal
    carry_risk: Optional[CarryRisk] = None

    def __post_init__(self) -> None:
        if not self.opportunity_id:
            raise ValueError("opportunity_id: must be a non-empty identifier")
        if self.refinance_kind is RefinanceKind.MULTI_PERIOD_CARRY:
            if self.flash_financing is not None:
                raise FlashFinancingNotAllowedError(
                    f"{self.opportunity_id}: flash principal cannot finance "
                    "MULTI_PERIOD_CARRY (persistent collateralized funding, "
                    "not flashloan profit)"
                )
        # INTRA_TX_ATOMIC without injected financing terms is constructible
        # but never evaluates to a candidate: the evaluator blocks it with
        # the typed rejection ``flash_financing_unproven`` (missing data is
        # a typed rejection, not an exception).
        object.__setattr__(
            self,
            "target_utilization",
            require_rational(self.target_utilization, "target_utilization"),
        )
        for name in ("entry_fee", "exit_fee"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self,
                    name,
                    require_nonnegative_rational(value, name),
                )


@dataclass(frozen=True)
class HealthFactorPostcondition:
    """Externally computed post-switch health factor (model computes none).

    ``hf_after`` follows the ``risk.health_factor`` vocabulary: a
    ``Rational``, or ``None`` when the external provider could not prove it.
    """

    position_key: str
    hf_after: Optional[Rational]
    source: str

    def __post_init__(self) -> None:
        if not self.position_key:
            raise ValueError("position_key: must be a non-empty identifier")
        if not self.source:
            raise ValueError("source: must be a non-empty provenance string")
        if self.hf_after is not None:
            hf = require_rational(self.hf_after, "hf_after")
            object.__setattr__(self, "hf_after", hf)


class HealthFactorProvider(Protocol):
    """Injected provider of externally computed HF postconditions."""

    def postcondition_for(
        self, position_key: str
    ) -> Optional[HealthFactorPostcondition]:
        """Return the postcondition for a position, or ``None`` if unknown."""
        ...


@dataclass(frozen=True)
class RefinanceDecision:
    """Advisory evaluation result (research output, never an authority)."""

    opportunity_id: str
    position_key: str
    refinance_kind: RefinanceKind
    status: RefinanceDecisionStatus
    execution_class: ExecutionClass
    horizon_seconds: Optional[int]
    current_borrow_apr: Rational
    target_borrow_apr: Optional[Rational]
    interest_saving: Optional[Rational]
    known_switch_costs: Rational
    unknown_switch_cost_fields: Tuple[str, ...]
    net_saving_over_known_costs: Optional[Rational]
    hf_after: Optional[Rational]
    rejection: Optional[RateCurveRejection]
    carry_risk: Optional[CarryRisk]
    notes: Tuple[str, ...]

    @property
    def actionable(self) -> bool:
        """True only for fully proven candidates (advisory, not authority)."""
        return self.status is RefinanceDecisionStatus.CANDIDATE


class RefinanceEvaluator:
    """Evaluates :class:`RateSpreadOpportunity` inputs into typed decisions."""

    def __init__(self, health_factor_provider: HealthFactorProvider) -> None:
        self._health_factor_provider = health_factor_provider

    def evaluate(self, opportunity: RateSpreadOpportunity) -> RefinanceDecision:
        position = opportunity.position
        horizon_seconds = opportunity.horizon.to_seconds()
        notes: list[str] = []
        hf_after = self._external_hf_after(position.position_key)
        known_costs, unknown_fields = self._switch_costs(opportunity)

        if horizon_seconds is None:
            return self._blocked(
                opportunity,
                RateCurveRejection.HORIZON_UNPROVIDED,
                horizon_seconds=None,
                known_costs=known_costs,
                unknown_fields=unknown_fields,
                hf_after=hf_after,
                target_apr=None,
                interest_saving=None,
                notes=notes,
            )

        target_quote = opportunity.target_curve.borrow_apy(
            opportunity.target_utilization
        )
        if target_quote.rejection is not None or target_quote.apy is None:
            rejection = (
                target_quote.rejection or RateCurveRejection.CURVE_PARAMETERS_UNKNOWN
            )
            return self._blocked(
                opportunity,
                rejection,
                horizon_seconds=horizon_seconds,
                known_costs=known_costs,
                unknown_fields=unknown_fields,
                hf_after=hf_after,
                target_apr=None,
                interest_saving=None,
                notes=notes,
            )
        target_apr: Rational = target_quote.apy

        horizon_fraction = Fraction(horizon_seconds, SECONDS_PER_YEAR)
        current_interest = (
            position.balance * position.current_borrow_apr * horizon_fraction
        )
        projected_interest = position.balance * target_apr * horizon_fraction
        interest_saving = current_interest - projected_interest
        net_saving = interest_saving - known_costs

        if net_saving <= 0:
            # Typed no-trade: unknown costs (>= 0) could only make it worse,
            # so this conclusion is safe even when costs are incomplete.
            if unknown_fields:
                notes.append(
                    "no_trade_concluded_despite_unknown_costs:"
                    + ",".join(unknown_fields)
                )
            return RefinanceDecision(
                opportunity_id=opportunity.opportunity_id,
                position_key=position.position_key,
                refinance_kind=opportunity.refinance_kind,
                status=RefinanceDecisionStatus.NO_TRADE,
                execution_class=ExecutionClass.HEDGED_NON_ATOMIC,
                horizon_seconds=horizon_seconds,
                current_borrow_apr=position.current_borrow_apr,
                target_borrow_apr=target_apr,
                interest_saving=interest_saving,
                known_switch_costs=known_costs,
                unknown_switch_cost_fields=unknown_fields,
                net_saving_over_known_costs=net_saving,
                hf_after=hf_after,
                rejection=None,
                carry_risk=opportunity.carry_risk,
                notes=tuple(notes),
            )

        if opportunity.refinance_kind is RefinanceKind.INTRA_TX_ATOMIC:
            # Classification gates are checked before generic cost
            # completeness so the most specific typed rejection is recorded.
            financing = opportunity.flash_financing
            if financing is None or not financing.proven:
                return self._blocked(
                    opportunity,
                    RateCurveRejection.FLASH_FINANCING_UNPROVEN,
                    horizon_seconds=horizon_seconds,
                    known_costs=known_costs,
                    unknown_fields=unknown_fields,
                    hf_after=hf_after,
                    target_apr=target_apr,
                    interest_saving=interest_saving,
                    notes=notes,
                )
            if financing.flash_fee is None:
                return self._blocked(
                    opportunity,
                    RateCurveRejection.FLASH_FEE_UNKNOWN,
                    horizon_seconds=horizon_seconds,
                    known_costs=known_costs,
                    unknown_fields=unknown_fields,
                    hf_after=hf_after,
                    target_apr=target_apr,
                    interest_saving=interest_saving,
                    notes=notes,
                )
            postconditions = opportunity.same_tx_postconditions
            if postconditions is None or not postconditions.repayment_proven:
                return self._blocked(
                    opportunity,
                    RateCurveRejection.REPAYMENT_UNPROVEN,
                    horizon_seconds=horizon_seconds,
                    known_costs=known_costs,
                    unknown_fields=unknown_fields,
                    hf_after=hf_after,
                    target_apr=target_apr,
                    interest_saving=interest_saving,
                    notes=notes,
                )

        if unknown_fields:
            # Unknown costs are excluded from profit and flagged; they can
            # never make a candidate look better, so a positive saving over
            # known costs alone is not enough for a candidate conclusion.
            return self._blocked(
                opportunity,
                RateCurveRejection.SWITCH_COSTS_UNKNOWN,
                horizon_seconds=horizon_seconds,
                known_costs=known_costs,
                unknown_fields=unknown_fields,
                hf_after=hf_after,
                target_apr=target_apr,
                interest_saving=interest_saving,
                notes=notes,
            )

        if hf_after is None:
            # Post-switch health factor must come from the injected external
            # provider; this model never computes a health factor itself.
            return self._blocked(
                opportunity,
                RateCurveRejection.HEALTH_FACTOR_UNPROVEN,
                horizon_seconds=horizon_seconds,
                known_costs=known_costs,
                unknown_fields=unknown_fields,
                hf_after=None,
                target_apr=target_apr,
                interest_saving=interest_saving,
                notes=notes,
            )

        execution_class = (
            ExecutionClass.LOCAL_ATOMIC_CANDIDATE
            if opportunity.refinance_kind is RefinanceKind.INTRA_TX_ATOMIC
            else ExecutionClass.HEDGED_NON_ATOMIC
        )
        if opportunity.refinance_kind is RefinanceKind.MULTI_PERIOD_CARRY:
            if opportunity.carry_risk is None:
                notes.append("carry_risk_not_recorded")
            else:
                notes.append("funding_withdrawal_risk_recorded")
        notes.append("advisory_only_no_execution_authority")
        return RefinanceDecision(
            opportunity_id=opportunity.opportunity_id,
            position_key=position.position_key,
            refinance_kind=opportunity.refinance_kind,
            status=RefinanceDecisionStatus.CANDIDATE,
            execution_class=execution_class,
            horizon_seconds=horizon_seconds,
            current_borrow_apr=position.current_borrow_apr,
            target_borrow_apr=target_apr,
            interest_saving=interest_saving,
            known_switch_costs=known_costs,
            unknown_switch_cost_fields=unknown_fields,
            net_saving_over_known_costs=net_saving,
            hf_after=hf_after,
            rejection=None,
            carry_risk=opportunity.carry_risk,
            notes=tuple(notes),
        )

    def evaluate_all(
        self, opportunities: Sequence[RateSpreadOpportunity]
    ) -> Tuple[RefinanceDecision, ...]:
        """Evaluate a batch; position keys must be unique across the batch.

        Building the candidate set first enforces unique position keys, so
        the same collateralized debt position can never be evaluated (or
        counted) twice in one batch — collateral is never double counted.
        """
        RefinanceCandidateSet.build(
            tuple(opportunity.position for opportunity in opportunities)
        )
        return tuple(self.evaluate(opportunity) for opportunity in opportunities)

    def _external_hf_after(self, position_key: str) -> Optional[Rational]:
        postcondition = self._health_factor_provider.postcondition_for(position_key)
        if postcondition is None:
            return None
        return postcondition.hf_after

    def _switch_costs(
        self, opportunity: RateSpreadOpportunity
    ) -> Tuple[Rational, Tuple[str, ...]]:
        """Sum known costs exactly; name unknown ones (never zeroed)."""
        balance: Rational = opportunity.position.balance
        known = Fraction(0)
        unknown: list[str] = []
        financing = opportunity.flash_financing
        if financing is not None:
            if financing.flash_fee is None:
                unknown.append("flash_fee")
            else:
                known += financing.flash_fee * balance
        for name, fee in (
            ("entry_fee", opportunity.entry_fee),
            ("exit_fee", opportunity.exit_fee),
        ):
            if fee is None:
                unknown.append(name)
            else:
                known += fee * balance
        return known, tuple(unknown)

    def _blocked(
        self,
        opportunity: RateSpreadOpportunity,
        rejection: RateCurveRejection,
        *,
        horizon_seconds: Optional[int],
        known_costs: Rational,
        unknown_fields: Tuple[str, ...],
        hf_after: Optional[Rational],
        target_apr: Optional[Rational],
        interest_saving: Optional[Rational],
        notes: list[str],
    ) -> RefinanceDecision:
        net_saving: Optional[Rational] = None
        if interest_saving is not None:
            net_saving = interest_saving - known_costs
        return RefinanceDecision(
            opportunity_id=opportunity.opportunity_id,
            position_key=opportunity.position.position_key,
            refinance_kind=opportunity.refinance_kind,
            status=RefinanceDecisionStatus.BLOCKED,
            execution_class=ExecutionClass.HEDGED_NON_ATOMIC,
            horizon_seconds=horizon_seconds,
            current_borrow_apr=opportunity.position.current_borrow_apr,
            target_borrow_apr=target_apr,
            interest_saving=interest_saving,
            known_switch_costs=known_costs,
            unknown_switch_cost_fields=unknown_fields,
            net_saving_over_known_costs=net_saving,
            hf_after=hf_after,
            rejection=rejection,
            carry_risk=opportunity.carry_risk,
            notes=tuple(notes) + (f"blocked_by:{rejection.value}",),
        )


@dataclass(frozen=True)
class RefinanceCandidateSet:
    """Position set with unique keys (collateral double-count prevention)."""

    positions: Tuple[DebtPosition, ...]

    @classmethod
    def build(cls, positions: Sequence[DebtPosition]) -> "RefinanceCandidateSet":
        seen: set[str] = set()
        for position in positions:
            if position.position_key in seen:
                raise DuplicatePositionKeyError(
                    f"duplicate position key {position.position_key!r}; "
                    "position keys must be unique so collateral is never "
                    "double counted"
                )
            seen.add(position.position_key)
        return cls(positions=tuple(positions))
