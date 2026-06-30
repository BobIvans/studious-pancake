"""
AMM Math Dispatcher

Dynamically dispatches AMM calculations to the correct formula based on
``pool_type``:

    - constant_product -> AmmMath.get_amount_out / calculate_price_impact / get_amount_in
    - stableswap       -> AmmMath.stableswap_* (Saber / Curve 2-asset)
    - clmm             -> AmmMath.clmm_*       (Orca Whirlpool / Raydium CLMM)
    - dlmm             -> AmmMath.dlmm_*       (Meteora DLMM)

Also provides :func:`classify_pool_type`, which maps a Solana DEX
``program_id`` to one of the four pool types, and
:func:`get_amount_out_for_hop`, which derives the type from a route ``hop``
dict (``pool_type`` first, then ``programId``) and dispatches accordingly.

Normalisation: the aliases ``"cpmm"``, ``""`` and ``None`` are mapped to
``"constant_product"`` so callers from :mod:`pool_state_manager` (which
tags Raydium/Orca v1 pools as ``"cpmm"``) work without changes.
"""

import logging
from typing import Any, Dict, Optional

from .amm_math import AmmMath

logger = logging.getLogger("AmmMathDispatcher")


# ---------------------------------------------------------------------------
# Program-id → pool-type registry
# ---------------------------------------------------------------------------
#
# Single source of truth for "given a DEX program id, what curve is this?".
# Keep this in sync with src/config/addresses.py.
_POOL_TYPE_BY_PROGRAM_ID: Dict[str, str] = {
    # Constant product (Raydium AMM v4, Raydium CPMM v4, Jupiter route wrapper)
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "constant_product",  # Raydium AMM v4
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C": "constant_product",  # Raydium CPMM
    # Concentrated liquidity (Orca Whirlpool, Raydium CLMM)
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": "clmm",  # Orca Whirlpool
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK": "clmm",  # Raydium CLMM
    "CAMMCkzFhJfPWvTv7SwbeCfFFmCd29S4mxS3vz5S2SEt": "clmm",  # Raydium CLMM (alt)
    "whirLbMi2tG34uFp881tua2RZBY9oXKVvVf9xrq7Rqi": "clmm",  # Orca variant seen in codebase
    # Discrete liquidity (Meteora DLMM)
    "LBUZKhRxPF3XUpBCjp4YzTKgLLjggiJWUna9LZJRQD3": "dlmm",  # Meteora DLMM
    "LbS9W8ioppRE44Yfczz7Spx3SJJ86VNoX8s6iF5K1nL": "dlmm",  # Meteora variant seen in codebase
    # Stableswap (Saber)
    "SSwpkEEcbUqx4uweEw4KsK9cZ4cwvJj2w2mYbFXM7Yr": "stableswap",  # Saber StableSwap
}

# Aliases that all mean "plain constant product".
_CPMM_ALIASES = {"", "cpmm", "constant_product", "xyk", "v1"}


def classify_pool_type(program_id: Optional[str]) -> str:
    """
    Map a Solana DEX ``program_id`` to a pool-type tag.

    Returns one of ``"constant_product"``, ``"stableswap"``, ``"clmm"``,
    ``"dlmm"``. Unknown / ``None`` ids default to ``"constant_product"``
    (the safest assumption: CPMM over-counts slippage, never under-counts).
    """
    if not program_id:
        return "constant_product"
    pid = str(program_id).strip()
    return _POOL_TYPE_BY_PROGRAM_ID.get(pid, "constant_product")


def _normalize_pool_type(pool_type: Optional[str]) -> str:
    """Lower-case + collapse CPMM aliases to ``constant_product``."""
    if not pool_type:
        return "constant_product"
    pt = pool_type.strip().lower()
    if pt in _CPMM_ALIASES:
        return "constant_product"
    return pt


def _pop_protocol_kwargs(pool_type: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract the protocol-specific keyword arguments a given pool type needs
    from a flat ``kwargs`` mapping, so we can forward a clean dict to the
    underlying AmmMath method.
    """
    pool_type = _normalize_pool_type(pool_type)
    out: Dict[str, Any] = {}
    if pool_type == "stableswap":
        if "amp" in kwargs:
            out["amp"] = int(kwargs["amp"])
    elif pool_type == "clmm":
        for k in (
            "sqrt_price_x64", "liquidity", "tick_current", "tick_spacing",
            "tick_array", "max_ticks",
        ):
            if k in kwargs and kwargs[k] is not None:
                out[k] = kwargs[k]
    elif pool_type == "dlmm":
        for k in ("bin_step", "active_bin_id", "bin_reserves", "max_bins"):
            if k in kwargs and kwargs[k] is not None:
                out[k] = kwargs[k]
    return out


class AmmMathDispatcher:
    """Mathematical dispatcher for multi-protocol AMM calculations."""

    # Exposed so callers can reach the classifier through the class too.
    classify_pool_type = staticmethod(classify_pool_type)

    @staticmethod
    def get_amount_out(
        amount_in: int,
        reserve_in: int,
        reserve_out: int,
        pool_type: str = "constant_product",
        fee_bps: int = 25,
        **kwargs,
    ) -> int:
        """
        Calculate output amount dispatching on pool_type.

        Args:
            amount_in: Input amount in smallest units.
            reserve_in: Input reserve in smallest units.
            reserve_out: Output reserve in smallest units.
            pool_type: One of "constant_product", "stableswap", "clmm", "dlmm"
                       (aliases "cpmm"/""/None → constant_product).
            fee_bps: Fee basis points (default 25 = 0.25%).
            **kwargs: Protocol-specific (amp, bin_step, tick_array, …).

        Returns:
            Output amount in smallest units.
        """
        pt = _normalize_pool_type(pool_type)

        if pt == "constant_product":
            return AmmMath.get_amount_out(amount_in, reserve_in, reserve_out, fee_bps=fee_bps)

        if pt == "stableswap":
            kw = _pop_protocol_kwargs(pt, kwargs)
            return AmmMath.stableswap_get_amount_out(
                amount_in, reserve_in, reserve_out, fee_bps=fee_bps, **kw,
            )

        if pt == "clmm":
            kw = _pop_protocol_kwargs(pt, kwargs)
            return AmmMath.clmm_get_amount_out(
                amount_in, reserve_in, reserve_out, fee_bps=fee_bps, **kw,
            )

        if pt == "dlmm":
            kw = _pop_protocol_kwargs(pt, kwargs)
            return AmmMath.dlmm_get_amount_out(
                amount_in, reserve_in, reserve_out, fee_bps=fee_bps, **kw,
            )

        logger.warning("Unknown pool_type '%s', falling back to constant_product", pool_type)
        return AmmMath.get_amount_out(amount_in, reserve_in, reserve_out, fee_bps=fee_bps)

    @staticmethod
    def get_amount_in(
        amount_out: int,
        reserve_in: int,
        reserve_out: int,
        pool_type: str = "constant_product",
        fee_bps: int = 25,
        **kwargs,
    ) -> int:
        """
        Calculate required input amount for desired amount_out dispatching on pool_type.

        Args:
            amount_out: Desired output amount in smallest units.
            reserve_in: Input reserve in smallest units.
            reserve_out: Output reserve in smallest units.
            pool_type: One of "constant_product", "stableswap", "clmm", "dlmm".
            fee_bps: Fee basis points (default 25 = 0.25%).
            **kwargs: Protocol-specific.

        Returns:
            Required input amount in smallest units.
        """
        pt = _normalize_pool_type(pool_type)

        if pt == "constant_product":
            return AmmMath.get_amount_in(amount_out, reserve_in, reserve_out, fee_bps=fee_bps)

        if pt == "stableswap":
            kw = _pop_protocol_kwargs(pt, kwargs)
            return AmmMath.stableswap_get_amount_in(
                amount_out, reserve_in, reserve_out, fee_bps=fee_bps, **kw,
            )

        if pt == "clmm":
            kw = _pop_protocol_kwargs(pt, kwargs)
            return AmmMath.clmm_get_amount_in(
                amount_out, reserve_in, reserve_out, fee_bps=fee_bps, **kw,
            )

        if pt == "dlmm":
            kw = _pop_protocol_kwargs(pt, kwargs)
            return AmmMath.dlmm_get_amount_in(
                amount_out, reserve_in, reserve_out, fee_bps=fee_bps, **kw,
            )

        logger.warning("Unknown pool_type '%s', falling back to constant_product", pool_type)
        return AmmMath.get_amount_in(amount_out, reserve_in, reserve_out, fee_bps=fee_bps)

    @staticmethod
    def calculate_price_impact(
        amount_in: int,
        reserve_in: int,
        reserve_out: int,
        pool_type: str = "constant_product",
        fee_bps: int = 25,
        **kwargs,
    ) -> float:
        """
        Calculate price impact percentage dispatching on pool_type.

        Returns:
            Price impact percentage (0.0 to 100.0).
        """
        pt = _normalize_pool_type(pool_type)

        if pt == "constant_product":
            return AmmMath.calculate_price_impact(amount_in, reserve_in, reserve_out)

        if pt == "clmm":
            kw = _pop_protocol_kwargs(pt, kwargs)
            return AmmMath.clmm_calculate_price_impact(
                amount_in, reserve_in, reserve_out, fee_bps=fee_bps, **kw,
            )

        if pt == "dlmm":
            kw = _pop_protocol_kwargs(pt, kwargs)
            return AmmMath.dlmm_calculate_price_impact(
                amount_in, reserve_in, reserve_out, fee_bps=fee_bps, **kw,
            )

        if pt == "stableswap":
            # Stableswap: derive impact from the swap itself.
            kw = _pop_protocol_kwargs(pt, kwargs)
            amount_out = AmmMath.stableswap_get_amount_out(
                amount_in, reserve_in, reserve_out, fee_bps=fee_bps, **kw,
            )
            new_reserve_in = reserve_in + amount_in
            new_reserve_out = reserve_out - amount_out
            price_before = reserve_out / reserve_in if reserve_in > 0 else 0.0
            price_after = new_reserve_out / new_reserve_in if new_reserve_in > 0 else 0.0
            if price_before <= 0:
                return 100.0
            impact = abs(price_after - price_before) / price_before * 100.0
            return min(impact, 100.0)

        logger.warning("Unknown pool_type '%s', falling back to constant_product", pool_type)
        return AmmMath.calculate_price_impact(amount_in, reserve_in, reserve_out)

    # ------------------------------------------------------------------
    # Hop-driven convenience entry point
    # ------------------------------------------------------------------

    @staticmethod
    def get_amount_out_for_hop(
        amount_in: int,
        reserve_in: int,
        reserve_out: int,
        hop: Dict[str, Any],
        fee_bps: Optional[int] = None,
    ) -> int:
        """
        Dispatch a swap output for a single route ``hop`` dict.

        The pool type is taken from ``hop["pool_type"]`` if present,
        otherwise derived from ``hop["programId"]`` via
        :func:`classify_pool_type`. Protocol kwargs (``amp``, ``bin_step``,
        ``active_bin_id``, ``tick_array``, ``bin_reserves`` …) are pulled
        from the hop and forwarded.

        ``fee_bps`` defaults to ``hop.get("fee_bps", 25)``.
        """
        pool_type = hop.get("pool_type") or classify_pool_type(hop.get("programId"))
        if fee_bps is None:
            fee_bps = int(hop.get("fee_bps", 25))

        # Collect protocol kwargs that may live in the hop dict.
        kwargs: Dict[str, Any] = {}
        for k in (
            "amp", "bin_step", "active_bin_id", "bin_reserves", "max_bins",
            "sqrt_price_x64", "liquidity", "tick_current", "tick_spacing",
            "tick_array",
        ):
            if k in hop and hop[k] is not None:
                kwargs[k] = hop[k]

        return AmmMathDispatcher.get_amount_out(
            amount_in, reserve_in, reserve_out,
            pool_type=pool_type, fee_bps=fee_bps, **kwargs,
        )
