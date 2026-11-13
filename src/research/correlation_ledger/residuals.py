"""Typed residual series families.

Each family computes a RESIDUAL against a proven anchor (identity/evidence
flags), never a raw nominal price pair. A sample whose proof is missing is
excluded with a typed reason and carries no value: unknown is never zero and a
missing proof is never substituted with a default anchor.

Timestamp alignment is computed from chain positions (slot/checkpoint) and
source timestamps of the paired evidences; unalignable samples are flagged
UNALIGNED so the ledger's lead/lag windows exclude them with a typed reason.

Correlation over these residuals is a scheduling/research signal only; it is
never proof of causation or execution and can never alter execution_class,
evidence_state, heat or a promotion boundary.
"""

from dataclasses import asdict, dataclass
import math

from src.assets.resolution.evidence import Evidence, digest
from src.research.correlation_ledger.ledger import (
    CHAIN_ALIGNED,
    UNALIGNED,
    normalized_residual,
)

STABLE_REDEMPTION = "stable_residual"
LST_PREMIUM = "lst_premium"
WRAPPER_BASIS = "wrapper_basis"
NAV_BASIS = "nav_basis"
VWAP_EXECUTION = "vwap_execution_residual"
DIRECT_SYNTHETIC = "direct_synthetic_residual"
ORACLE_MARKET = "oracle_residual"

REDEMPTION_UNPROVEN = "redemption_anchor_unproven"
COST_UNPROVEN = "conversion_cost_unproven"
LST_RATE_UNPROVEN = "lst_exchange_rate_unproven"
INSTANT_EXIT_UNPROVEN = "instant_exit_unproven"
REFERENCE_UNPROVEN = "underlying_reference_unproven"
NAV_UNPROVEN = "nav_per_share_unproven"
SIZE_MISALIGNED = "exact_size_misaligned"
LEG_MISMATCH = "direct_synthetic_leg_mismatch"
SLOT_MISALIGNED = "oracle_slot_misaligned"

EXCLUSION_REASONS = frozenset(
    (
        REDEMPTION_UNPROVEN,
        COST_UNPROVEN,
        LST_RATE_UNPROVEN,
        INSTANT_EXIT_UNPROVEN,
        REFERENCE_UNPROVEN,
        NAV_UNPROVEN,
        SIZE_MISALIGNED,
        LEG_MISMATCH,
        SLOT_MISALIGNED,
    )
)
DEFAULT_MAX_SLOT_GAP = 3
DEFAULT_MAX_CLOCK_SKEW = 1.0


@dataclass(frozen=True)
class ResidualSample:
    feature: str
    # None when any proof is missing: an excluded sample never reports a
    # residual value, not even zero.
    value: float | None
    timestamp_alignment: str
    exclusions: tuple[str, ...]
    proof_refs: tuple[str, ...]


def _finite(*values: float) -> bool:
    return all(math.isfinite(v) for v in values)


def _alignment(
    *evidences: Evidence,
    max_slot_gap: int = DEFAULT_MAX_SLOT_GAP,
    max_clock_skew: float = DEFAULT_MAX_CLOCK_SKEW,
) -> str:
    slots = [e.slot_or_checkpoint for e in evidences]
    times = [e.observed_at for e in evidences]
    if any(s is None for s in slots) or not _finite(*times):
        return UNALIGNED
    positions = [int(s) for s in slots if s is not None]
    if (
        max(positions) - min(positions) > max_slot_gap
        or max(times) - min(times) > max_clock_skew
    ):
        return UNALIGNED
    return CHAIN_ALIGNED


def _refs(*evidences: Evidence) -> tuple[str, ...]:
    return tuple(sorted({digest(asdict(e)) for e in evidences}))


def _sample(
    feature: str,
    *,
    evidences: tuple[Evidence, ...],
    exclusions: tuple[str, ...],
    value: float | None,
    max_slot_gap: int,
    max_clock_skew: float,
) -> ResidualSample:
    alignment = _alignment(
        *evidences, max_slot_gap=max_slot_gap, max_clock_skew=max_clock_skew
    )
    if exclusions:
        return ResidualSample(
            feature, None, alignment, tuple(sorted(set(exclusions))), _refs(*evidences)
        )
    return ResidualSample(feature, value, alignment, (), _refs(*evidences))


def stable_redemption_residual(
    *,
    market_price: float,
    redemption_anchor: float,
    exit_cost: float,
    scale: float,
    redemption_proven: bool,
    exit_cost_known: bool,
    evidences: tuple[Evidence, ...],
    max_slot_gap: int = DEFAULT_MAX_SLOT_GAP,
    max_clock_skew: float = DEFAULT_MAX_CLOCK_SKEW,
) -> ResidualSample:
    """Stable/redemption residual: market price vs proven redemption anchor.

    The anchor is the protocol redemption/par rate with current proof; the
    exit/redemption cost is subtracted before scaling. Unproven anchors or
    costs are excluded, never defaulted to 1.0.
    """
    if not _finite(market_price, redemption_anchor, exit_cost, scale) or scale <= 0:
        raise ValueError("finite residual inputs required")
    exclusions: tuple[str, ...] = ()
    if not redemption_proven:
        exclusions += (REDEMPTION_UNPROVEN,)
    if not exit_cost_known:
        exclusions += (COST_UNPROVEN,)
    value = None
    if not exclusions:
        value = normalized_residual(
            market_price, redemption_anchor, conversion_cost=exit_cost, scale=scale
        )
    return _sample(
        STABLE_REDEMPTION,
        evidences=evidences,
        exclusions=exclusions,
        value=value,
        max_slot_gap=max_slot_gap,
        max_clock_skew=max_clock_skew,
    )


def lst_premium_residual(
    *,
    lst_price: float,
    underlying_price: float,
    exchange_rate: float,
    scale: float,
    rate_proven: bool,
    instant_exit_available: bool,
    instant_exit_cost: float,
    evidences: tuple[Evidence, ...],
    max_slot_gap: int = DEFAULT_MAX_SLOT_GAP,
    max_clock_skew: float = DEFAULT_MAX_CLOCK_SKEW,
) -> ResidualSample:
    """LST premium vs the protocol exchange/instant-exit rate.

    Anchor is underlying_price * protocol exchange rate; the proven
    instant-exit cost is the conversion cost. Without a proven exchange rate
    or a proven instant-exit route the premium is excluded (a tradable
    premium without a proven redemption route is not a residual).
    """
    if (
        not _finite(
            lst_price, underlying_price, exchange_rate, instant_exit_cost, scale
        )
        or scale <= 0
    ):
        raise ValueError("finite residual inputs required")
    exclusions: tuple[str, ...] = ()
    if not rate_proven:
        exclusions += (LST_RATE_UNPROVEN,)
    if not instant_exit_available:
        exclusions += (INSTANT_EXIT_UNPROVEN,)
    value = None
    if not exclusions:
        value = normalized_residual(
            lst_price,
            underlying_price * exchange_rate,
            conversion_cost=instant_exit_cost,
            scale=scale,
        )
    return _sample(
        LST_PREMIUM,
        evidences=evidences,
        exclusions=exclusions,
        value=value,
        max_slot_gap=max_slot_gap,
        max_clock_skew=max_clock_skew,
    )


def wrapper_basis_residual(
    *,
    wrapper_price: float,
    reference_price: float,
    wrap_cost: float,
    scale: float,
    reference_proven: bool,
    wrap_cost_known: bool,
    evidences: tuple[Evidence, ...],
    max_slot_gap: int = DEFAULT_MAX_SLOT_GAP,
    max_clock_skew: float = DEFAULT_MAX_CLOCK_SKEW,
) -> ResidualSample:
    """Wrapped-asset basis vs the proven underlying reference (e.g. BTC)."""
    if not _finite(wrapper_price, reference_price, wrap_cost, scale) or scale <= 0:
        raise ValueError("finite residual inputs required")
    exclusions: tuple[str, ...] = ()
    if not reference_proven:
        exclusions += (REFERENCE_UNPROVEN,)
    if not wrap_cost_known:
        exclusions += (COST_UNPROVEN,)
    value = None
    if not exclusions:
        value = normalized_residual(
            wrapper_price, reference_price, conversion_cost=wrap_cost, scale=scale
        )
    return _sample(
        WRAPPER_BASIS,
        evidences=evidences,
        exclusions=exclusions,
        value=value,
        max_slot_gap=max_slot_gap,
        max_clock_skew=max_clock_skew,
    )


def nav_basis_residual(
    *,
    market_price: float,
    nav_per_share: float,
    redemption_spread: float,
    scale: float,
    nav_proven: bool,
    evidences: tuple[Evidence, ...],
    max_slot_gap: int = DEFAULT_MAX_SLOT_GAP,
    max_clock_skew: float = DEFAULT_MAX_CLOCK_SKEW,
) -> ResidualSample:
    """JLP-style LP-token/NAV basis vs the proven net asset value per share."""
    if not _finite(market_price, nav_per_share, redemption_spread, scale) or scale <= 0:
        raise ValueError("finite residual inputs required")
    exclusions: tuple[str, ...] = ()
    if not nav_proven:
        exclusions += (NAV_UNPROVEN,)
    value = None
    if not exclusions:
        value = normalized_residual(
            market_price,
            nav_per_share,
            conversion_cost=redemption_spread,
            scale=scale,
        )
    return _sample(
        NAV_BASIS,
        evidences=evidences,
        exclusions=exclusions,
        value=value,
        max_slot_gap=max_slot_gap,
        max_clock_skew=max_clock_skew,
    )


def vwap_execution_residual(
    *,
    amm_vwap: float,
    clob_vwap: float,
    amm_size: int,
    clob_size: int,
    fee_cost: float,
    scale: float,
    evidences: tuple[Evidence, ...],
    max_slot_gap: int = DEFAULT_MAX_SLOT_GAP,
    max_clock_skew: float = DEFAULT_MAX_CLOCK_SKEW,
) -> ResidualSample:
    """AMM-vs-CLOB exact-size VWAP residual.

    Both legs must be priced at the SAME exact size; size-mismatched quotes
    are excluded because they measure depth, not execution residual.
    """
    if not _finite(amm_vwap, clob_vwap, fee_cost, scale) or scale <= 0:
        raise ValueError("finite residual inputs required")
    exclusions: tuple[str, ...] = ()
    if (
        type(amm_size) is not int
        or type(clob_size) is not int
        or (amm_size != clob_size or amm_size <= 0)
    ):
        exclusions += (SIZE_MISALIGNED,)
    value = None
    if not exclusions:
        value = normalized_residual(
            amm_vwap, clob_vwap, conversion_cost=fee_cost, scale=scale
        )
    return _sample(
        VWAP_EXECUTION,
        evidences=evidences,
        exclusions=exclusions,
        value=value,
        max_slot_gap=max_slot_gap,
        max_clock_skew=max_clock_skew,
    )


def direct_synthetic_route_residual(
    *,
    direct_output: float,
    synthetic_output: float,
    input_amount: int,
    legs_proven_equal: bool,
    scale: float,
    evidences: tuple[Evidence, ...],
    max_slot_gap: int = DEFAULT_MAX_SLOT_GAP,
    max_clock_skew: float = DEFAULT_MAX_CLOCK_SKEW,
) -> ResidualSample:
    """Direct-vs-synthetic route residual for the same input amount.

    Requires a proven identical leg set on both routes; mismatched legs are
    excluded because they compare different topologies, not route residual.
    """
    if not _finite(direct_output, synthetic_output, scale) or scale <= 0:
        raise ValueError("finite residual inputs required")
    exclusions: tuple[str, ...] = ()
    if type(input_amount) is not int or input_amount <= 0:
        raise ValueError("positive exact input amount required")
    if not legs_proven_equal:
        exclusions += (LEG_MISMATCH,)
    value = None
    if not exclusions:
        value = normalized_residual(direct_output, synthetic_output, scale=scale)
    return _sample(
        DIRECT_SYNTHETIC,
        evidences=evidences,
        exclusions=exclusions,
        value=value,
        max_slot_gap=max_slot_gap,
        max_clock_skew=max_clock_skew,
    )


def oracle_market_residual(
    *,
    market_price: float,
    oracle_price: float,
    confidence_scale: float,
    evidences: tuple[Evidence, ...],
    max_slot_gap: int = DEFAULT_MAX_SLOT_GAP,
    max_clock_skew: float = DEFAULT_MAX_CLOCK_SKEW,
) -> ResidualSample:
    """Oracle-vs-market residual.

    Requires the oracle update and the market quote to be chain-position
    alignable (slot/checkpoint within max_slot_gap and source timestamps
    within max_clock_skew); misaligned pairs are excluded with a typed reason
    instead of being silently correlated.
    """
    if (
        not _finite(market_price, oracle_price, confidence_scale)
        or confidence_scale <= 0
    ):
        raise ValueError("finite residual inputs required")
    alignment = _alignment(
        *evidences, max_slot_gap=max_slot_gap, max_clock_skew=max_clock_skew
    )
    exclusions: tuple[str, ...] = ()
    if alignment == UNALIGNED:
        exclusions += (SLOT_MISALIGNED,)
    value = None
    if not exclusions:
        value = normalized_residual(market_price, oracle_price, scale=confidence_scale)
    return _sample(
        ORACLE_MARKET,
        evidences=evidences,
        exclusions=exclusions,
        value=value,
        max_slot_gap=max_slot_gap,
        max_clock_skew=max_clock_skew,
    )


def residual_observation(
    sample: ResidualSample,
    *,
    chain: str,
    market_id: str,
    relation_id: str,
    evidence: Evidence,
    liquidity_resources: tuple[str, ...],
    regime: str,
):
    """Materialize a residual sample as a ledger observation, or None.

    Samples with typed exclusions or unproven alignment are never written as
    residuals (unknown is not zero); the caller keeps the typed reason on the
    sample itself.
    """
    from src.research.correlation_ledger.ledger import NormalizedObservation

    if (
        sample.value is None
        or sample.exclusions
        or (sample.timestamp_alignment != CHAIN_ALIGNED)
    ):
        return None
    return NormalizedObservation(
        chain,
        market_id,
        relation_id,
        evidence,
        ((sample.feature, sample.value),),
        liquidity_resources,
        regime,
        timestamp_alignment=sample.timestamp_alignment,
    )
