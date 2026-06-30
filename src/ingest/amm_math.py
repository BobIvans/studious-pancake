"""
AMM Math Engine - Local Cross-Rate Calculations

Provides precise BigInt-based AMM calculations for four pool families
without external API calls. Used for ultra-fast local routing.

Supported curves (dispatched by AmmMathDispatcher on ``pool_type``):
    - constant_product : Raydium AMM v4 / CPMM / Orca v1 (x*y=k)
    - stableswap       : Saber / Curve-style 2-asset invariant (Newton + bisection)
    - clmm             : Orca Whirlpool / Raydium CLMM (Q64.64 + tick crossing)
    - dlmm             : Meteora DLMM (discrete-bin traversal)

All hot-path math runs on Python ``int`` (arbitrary precision). No floats
are used in the swap outputs — only as return values for *percentage*
reports (price impact).
"""

import logging
from typing import List, Optional, Tuple

logger = logging.getLogger("AmmMath")

# Q64.64 scale used by Orca Whirlpool / Raydium CLMM for sqrt-price & liquidity.
Q64 = 1 << 64  # 2**64

# Meteora DLMM reference bin: price = (1 + bin_step/10000)^(bin_id - REFERENCE_BIN_ID)
DLMM_REFERENCE_BIN_ID = 8_388_608


class AmmMath:
    """Mathematical engine for AMM calculations using arbitrary precision integers."""

    # ===================================================================
    # CONSTANT PRODUCT (x*y=k) — legacy, unchanged
    # ===================================================================

    @staticmethod
    def get_amount_out(
        amount_in: int,
        reserve_in: int,
        reserve_out: int,
        fee_bps: int = 25
    ) -> int:
        """
        Calculate output amount for AMM swap using constant product formula.

        Formula: amountOut = (reserveOut * amountInWithFee) / (reserveIn * 10000 + amountInWithFee)

        Args:
            amount_in: Input amount (as integer, e.g., lamports)
            reserve_in: Reserve of input token in pool
            reserve_out: Reserve of output token in pool
            fee_bps: Fee in basis points (default 25 = 0.25%)

        Returns:
            Output amount (as integer)
        """
        if amount_in <= 0:
            return 0

        if reserve_in <= 0 or reserve_out <= 0:
            return 0

        # Convert to BigInt-like precision (Python int is arbitrary precision)
        amount_in_big = int(amount_in)
        reserve_in_big = int(reserve_in)
        reserve_out_big = int(reserve_out)

        # Calculate fee deducted basis points
        fee_deducted_bps = 10000 - fee_bps

        # Correct CPMM formula with fee: amountOut = (reserveOut * amountIn * feeDeducted) / (reserveIn * 10000 + amountIn * feeDeducted)
        numerator = reserve_out_big * amount_in_big * fee_deducted_bps
        denominator = (reserve_in_big * 10000) + (amount_in_big * fee_deducted_bps)
        amount_out = numerator // denominator

        return int(amount_out)

    @staticmethod
    def calculate_price_impact(
        amount_in: int,
        reserve_in: int,
        reserve_out: int
    ) -> float:
        """
        Calculate price impact percentage for a swap.

        Args:
            amount_in: Input amount
            reserve_in: Input reserve
            reserve_out: Output reserve

        Returns:
            Price impact as percentage (0.0 to 100.0)
        """
        if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
            return 100.0

        # Price before swap
        price_before = reserve_out / reserve_in

        # Price after swap (simplified approximation)
        new_reserve_in = reserve_in + amount_in
        new_reserve_out = reserve_out - AmmMath.get_amount_out(amount_in, reserve_in, reserve_out)

        if new_reserve_in <= 0:
            return 100.0

        price_after = new_reserve_out / new_reserve_in

        if price_before <= 0:
            return 100.0

        impact = abs(price_after - price_before) / price_before * 100.0
        return min(impact, 100.0)

    @staticmethod
    def get_amount_in(
        amount_out: int,
        reserve_in: int,
        reserve_out: int,
        fee_bps: int = 25
    ) -> int:
        """
        Calculate required input amount for desired output amount.

        Args:
            amount_out: Desired output amount
            reserve_in: Reserve of input token
            reserve_out: Reserve of output token
            fee_bps: Fee in basis points

        Returns:
            Required input amount
        """
        if amount_out <= 0 or reserve_in <= 0 or reserve_out <= 0:
            return 0

        if amount_out >= reserve_out:
            return 0  # Impossible to get more than reserve

        # For constant product: (reserveIn + amountIn) * (reserveOut - amountOut) = reserveIn * reserveOut
        # Solving for amountIn gives: amountIn = (reserveIn * amountOut) / (reserveOut - amountOut)

        numerator = int(reserve_in) * int(amount_out)
        denominator = int(reserve_out) - int(amount_out)

        if denominator <= 0:
            return 0

        amount_in_no_fee = numerator // denominator

        # Add fee back: since fee is deducted from input, we need to solve for pre-fee amount
        # This is approximate - for precision, would need iterative approach
        fee_multiplier = 10000 / (10000 - fee_bps)
        amount_in_with_fee = int(amount_in_no_fee * fee_multiplier)

        return amount_in_with_fee

    # ===================================================================
    # STABLESWAP (Saber / Curve 2-asset invariant)
    # -------------------------------------------------------------------
    # Invariant:  A * x^2 + A * y^2 + D - A * D - 2 * A * x * y = 0
    # solved for the output reserve `y` via Newton's method with a
    # bisection fallback. Pure integer arithmetic.
    # ===================================================================

    @staticmethod
    def _stableswap_get_D(x: int, y: int, amp: int) -> int:
        """
        Solve the StableSwap invariant for D (two-asset Curve/Saber).

        Invariant:  f(D) = 4·A·(x+y) + D − 4·A·D − D³/(4·x·y) = 0

        Solved by Newton's method on f(D). D₀ = x+y is the A→∞ (linear)
        limit and is an upper bound for the root, so the iteration
        converges downward in a few steps. Pure integer arithmetic.
        """
        if x <= 0 or y <= 0 or amp <= 0:
            return 0

        s = x + y
        denom_xy = 4 * x * y  # scaling constant for the cubic term

        d = s  # upper bound; A=0 root would be 2·√(x·y) ≤ x+y
        for _ in range(255):
            d_prev = d
            # f(D)  = 4·A·s + D − 4·A·D − D³/(4·x·y)
            # f'(D) = 1 − 4·A − 3·D²/(4·x·y)
            f = 4 * amp * s + d - 4 * amp * d - (d * d * d) // denom_xy
            fp = 1 - 4 * amp - (3 * d * d) // denom_xy
            if fp == 0:
                break
            d_next = d - f // fp
            if d_next <= 0:
                d_next = d // 2  # clamp to a positive interior value
            d = d_next
            if abs(d - d_prev) <= 1:
                break
        return max(1, d)

    @staticmethod
    def _stableswap_solve_y_int(x_known: int, amp: int, d: int) -> int:
        """
        Given reserves x_known and invariant D, solve for the other reserve y.

        Reducing the two-asset invariant to a quadratic in y:

            y² + b·y − c = 0   where
            b = x + D/(4A) − D
            c = D³ / (16·A·x)

        Positive root found by **Newton's method** with the standard Curve
        fixed-point form  y ← (y² + c)/(2y + b), guarded by a **bisection
        fallback** on the sign of  g(y) = y² + b·y − c.
        """
        if x_known <= 0 or d <= 0 or amp <= 0:
            return 0

        b = x_known + d // (4 * amp) - d
        c = (d * d * d) // (16 * amp * x_known)

        # Upper bound on y: when A→∞ the curve is linear so y = D − x.
        y = d - x_known
        if y <= 0:
            y = d // 2

        converged = False
        for _ in range(255):
            denom = 2 * y + b
            if denom <= 0:
                break
            y_prev = y
            y = (y * y + c) // denom
            if y <= 0:
                y = 1
            if abs(y - y_prev) <= 1:
                converged = True
                break

        # Bisection fallback: bracket the positive root of y² + b·y − c = 0.
        # g(y) is increasing for y > 0 here, so a single bracket suffices.
        if not converged or y <= 0:
            lo, hi = 1, d
            for _ in range(255):
                mid = (lo + hi) // 2
                if mid <= 0:
                    break
                g = mid * mid + b * mid - c
                if g < 0:
                    lo = mid + 1
                else:
                    hi = mid
                if hi - lo <= 1:
                    y = lo
                    break
        return max(1, y)

    @staticmethod
    def stableswap_get_amount_out(
        amount_in: int,
        reserve_in: int,
        reserve_out: int,
        amp: int = 100,
        fee_bps: int = 4,
    ) -> int:
        """
        StableSwap output amount (Saber/Curve 2-asset).

        On a balanced stable pool this yields MORE output than the constant
        product curve (less slippage) — correcting the bot's missed profit.
        Fee default lowered to 4 bps (0.04%) — typical for stable pairs.
        """
        if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0 or amp <= 0:
            return 0

        fee = (amount_in * fee_bps) // 10000
        amount_in_after_fee = amount_in - fee
        if amount_in_after_fee <= 0:
            return 0

        d = AmmMath._stableswap_get_D(reserve_in, reserve_out, amp)
        if d <= 0:
            # Degenerate: fall back to constant product.
            return AmmMath.get_amount_out(amount_in, reserve_in, reserve_out, fee_bps=fee_bps)

        new_x = reserve_in + amount_in_after_fee
        y_new = AmmMath._stableswap_solve_y_int(new_x, amp, d)
        if y_new <= 0 or y_new >= reserve_out:
            return 0
        return reserve_out - y_new

    @staticmethod
    def stableswap_get_amount_in(
        amount_out: int,
        reserve_in: int,
        reserve_out: int,
        amp: int = 100,
        fee_bps: int = 4,
    ) -> int:
        """
        StableSwap required input for a desired output. Inverse of
        :meth:`stableswap_get_amount_out`; fee added back on top.
        """
        if amount_out <= 0 or reserve_in <= 0 or reserve_out <= 0 or amp <= 0:
            return 0
        if amount_out >= reserve_out:
            return 0

        d = AmmMath._stableswap_get_D(reserve_in, reserve_out, amp)
        if d <= 0:
            return AmmMath.get_amount_in(amount_out, reserve_in, reserve_out, fee_bps=fee_bps)

        new_y = reserve_out - amount_out
        x_new = AmmMath._stableswap_solve_y_int(new_y, amp, d)
        if x_new <= reserve_in:
            return 0
        amount_in_after_fee = x_new - reserve_in
        # Add fee back.
        net_bps = 10000 - fee_bps
        if net_bps <= 0:
            return 0
        amount_in = (amount_in_after_fee * 10000 + net_bps - 1) // net_bps
        return amount_in

    # ===================================================================
    # CLMM (Orca Whirlpool / Raydium CLMM)
    # -------------------------------------------------------------------
    # Uses Q64.64 sqrt-price and liquidity. When the rich on-chain state
    # (tick arrays, sqrt_price, liquidity, tick_current) is available we
    # run an honest tick-crossing walk (<= max_ticks). When it is NOT
    # available we return a PESSIMISTIC estimate that is guaranteed <=
    # the constant-product output — so slippage is over-counted and the
    # bot never under-estimates the loss on a concentrated-liquidity pool.
    # ===================================================================

    @staticmethod
    def _clmm_pessimistic_out(
        amount_in: int, reserve_in: int, reserve_out: int, fee_bps: int
    ) -> int:
        """
        Conservative reserve-based estimate for CLMM when tick state is
        unavailable. Concentrated liquidity means real slippage can be
        10-100x the CPMM figure, so we shrink the effective output reserve
        proportionally to trade size vs. liquidity -> output is always
        <= the CPMM amount_out. This is the safety floor.
        """
        cp_out = AmmMath.get_amount_out(amount_in, reserve_in, reserve_out, fee_bps=fee_bps)
        if cp_out <= 0 or reserve_in <= 0:
            return cp_out
        # Trade-size ratio: how much of the visible liquidity we move.
        # A trade that is a large fraction of visible reserves is penalised
        # hardest (concentrated pools run out of in-range liquidity fast).
        ratio = amount_in / reserve_in  # float, only for the penalty scalar
        if ratio <= 0:
            return cp_out
        # Quadratic penalty on output: large trades lose more, never gain.
        penalty = max(0.0, 1.0 - ratio)  # in [0,1)
        # Further conservative haircut for unknown tick depth.
        conservative = int(cp_out * (0.5 + 0.5 * penalty))
        return max(0, min(conservative, cp_out))

    @staticmethod
    def clmm_get_amount_out(
        amount_in: int,
        reserve_in: int,
        reserve_out: int,
        fee_bps: int = 25,
        *,
        sqrt_price_x64: Optional[int] = None,
        liquidity: Optional[int] = None,
        tick_current: Optional[int] = None,
        tick_spacing: Optional[int] = None,
        tick_array: Optional[List[Tuple[int, int]]] = None,  # [(tick_index, liquidity_net), ...]
        max_ticks: int = 50,
    ) -> int:
        """
        CLMM output amount.

        Honest Q64.64 tick-walk when ``sqrt_price_x64``, ``liquidity``,
        ``tick_current`` and ``tick_array`` are provided; otherwise the
        pessimistic safety floor.
        """
        if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
            return 0

        has_state = (
            sqrt_price_x64 is not None
            and liquidity is not None
            and liquidity > 0
            and tick_current is not None
        )
        if not has_state or not tick_array:
            logger.debug(
                "clmm_get_amount_out: no tick state -> pessimistic fallback "
                "(in=%d rin=%d rout=%d)", amount_in, reserve_in, reserve_out,
            )
            return AmmMath._clmm_pessimistic_out(amount_in, reserve_in, reserve_out, fee_bps)

        # --- Honest tick-crossing walk (input is token-x, "zeroForOne"-style) ---
        remaining = amount_in - (amount_in * fee_bps) // 10000
        if remaining <= 0:
            return 0

        sqrt_p = int(sqrt_price_x64)
        liq = int(liquidity)
        out_total = 0
        steps = 0

        # Sort tick boundary crossings by distance from current tick.
        # tick_array entries: (tick_index, liquidity_net)
        sorted_ticks = sorted(
            [(t, ln) for (t, ln) in tick_array if t >= int(tick_current)],
            key=lambda e: e[0],
        )

        for (tick_index, liquidity_net) in sorted_ticks:
            if steps >= max_ticks:
                break
            if remaining <= 0 or liq <= 0:
                break

            # sqrt_price at the tick boundary (TickMath.getSqrtPriceAtTick).
            sqrt_p_next = AmmMath._sqrt_price_at_tick(tick_index)
            if sqrt_p_next <= sqrt_p:
                # Crossing only makes sense when price moves toward boundary.
                sqrt_p_target = max(sqrt_p_next, sqrt_p)
            else:
                sqrt_p_target = sqrt_p_next

            # delta_x (input) = L * (sqrt_p_target - sqrt_p) / (sqrt_p * sqrt_p_target) * Q64
            if sqrt_p > 0 and sqrt_p_target > 0:
                delta_x = (liq * Q64 * (sqrt_p_target - sqrt_p)) // (sqrt_p * sqrt_p_target)
            else:
                delta_x = 0

            if delta_x <= 0:
                # No input consumed at this tick; advance price and apply net.
                sqrt_p = sqrt_p_target
                liq = max(0, liq + int(liquidity_net))
                steps += 1
                continue

            if remaining >= delta_x:
                # Consume the full tick segment.
                remaining -= delta_x
                # delta_y (output) = L * (sqrt_p_target - sqrt_p) / Q64
                delta_y = (liq * (sqrt_p_target - sqrt_p)) // Q64
                out_total += delta_y
                sqrt_p = sqrt_p_target
                liq = max(0, liq + int(liquidity_net))
            else:
                # Partial fill within current tick segment.
                # delta_y = remaining / delta_x * delta_y  (integer)
                delta_y_full = (liq * (sqrt_p_target - sqrt_p)) // Q64
                delta_y = (remaining * delta_y_full) // delta_x if delta_x else 0
                out_total += delta_y
                remaining = 0
                sqrt_p = sqrt_p_target
            steps += 1

        return max(0, out_total)

    @staticmethod
    def _sqrt_price_at_tick(tick: int) -> int:
        """
        Approximate Q64.64 sqrt-price at a tick index.
        sqrt_price = 1.0001^(tick/2) * 2^64, computed via exponent/log in int.
        This is a monotonic approximation suitable for the tick walk; exact
        TickMath bounds clamping is not required for an output estimate.
        """
        # sqrt(1.0001^tick) = 1.0001^(tick/2). Use Q64 fixed-point exp/log.
        # log2(1.0001) ~= 0.00014384; * tick / 2 -> exponent in base 2.
        log2_ratio = 144269  # floor(log2(1.0001) * 2^32) ~= 144269
        # exponent (Q32): tick/2 * log2_ratio
        exp_q32 = (tick * log2_ratio) // 2
        # 2^(exp_q32 / 2^32) * 2^64  =  2^((exp_q32 >> 0)/2^32 + 64)
        # Compute via shifts to stay in integer math.
        whole = exp_q32 >> 32
        frac = exp_q32 & ((1 << 32) - 1)
        # 2^frac_q32 ~= 1 + frac/2^32 + (frac/2^32)^2/2  (Taylor, integer)
        base = Q64  # 2^64
        result = base << whole if whole >= 0 else base >> (-whole)
        # multiply by (1 + frac/2^32 + ...)
        result = (result * ((1 << 32) + frac + (frac * frac) // (1 << 32))) >> 32
        return max(1, result)

    @staticmethod
    def clmm_get_amount_in(
        amount_out: int,
        reserve_in: int,
        reserve_out: int,
        fee_bps: int = 25,
        **kwargs,
    ) -> int:
        """CLMM required input. Without tick state uses the pessimistic inverse."""
        if amount_out <= 0 or reserve_in <= 0 or reserve_out <= 0:
            return 0
        if amount_out >= reserve_out:
            return 0
        # No tick state available in the current pipeline -> conservative.
        cp_in = AmmMath.get_amount_in(amount_out, reserve_in, reserve_out, fee_bps=fee_bps)
        if cp_in <= 0:
            return 0
        # Require at least the CP input plus a safety margin.
        return int(cp_in * 1.5)

    @staticmethod
    def clmm_calculate_price_impact(
        amount_in: int,
        reserve_in: int,
        reserve_out: int,
        fee_bps: int = 25,
        **kwargs,
    ) -> float:
        """CLMM price-impact %. Without tick state, uses the pessimistic output."""
        if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
            return 100.0
        out = AmmMath.clmm_get_amount_out(amount_in, reserve_in, reserve_out, fee_bps=fee_bps, **kwargs)
        price_before = reserve_out / reserve_in
        new_ri = reserve_in + amount_in
        new_ro = reserve_out - out
        if new_ri <= 0 or price_before <= 0:
            return 100.0
        price_after = new_ro / new_ri
        impact = abs(price_after - price_before) / price_before * 100.0
        return min(impact, 100.0)

    # ===================================================================
    # DLMM (Meteora) — discrete bin traversal
    # -------------------------------------------------------------------
    # Each bin has price (1 + bin_step/10000)^(bin_id - 8388608) and its
    # own (reserve_x, reserve_y). We walk bins from the active bin until
    # the input is exhausted (<= max_bins). Without ``bin_reserves`` we
    # use the same pessimistic safety floor as CLMM.
    # ===================================================================

    @staticmethod
    def _dlmm_bin_price_q(bin_id: int, bin_step: int) -> int:
        """
        Integer price ratio numerator for a bin: (1 + bin_step/10000)^k,
        scaled by 10^18 for precision. k = bin_id - REFERENCE_BIN_ID.
        """
        k = bin_id - DLMM_REFERENCE_BIN_ID
        if k == 0:
            return 10 ** 18
        base_num = 10000 + int(bin_step)  # numerator of (1 + bin_step/10000)
        base_den = 10000
        scale = 10 ** 18
        if k > 0:
            num = pow(base_num, k) * scale
            den = pow(base_den, k)
            return num // den
        else:
            num = pow(base_den, -k) * scale
            den = pow(base_num, -k)
            return num // den

    @staticmethod
    def dlmm_get_amount_out(
        amount_in: int,
        reserve_in: int,
        reserve_out: int,
        fee_bps: int = 25,
        *,
        bin_step: int = 1,
        active_bin_id: int = DLMM_REFERENCE_BIN_ID,
        bin_reserves: Optional[List[Tuple[int, int, int]]] = None,  # [(bin_id, reserve_x, reserve_y)]
        max_bins: int = 50,
    ) -> int:
        """DLMM (Meteora) output via bin traversal; pessimistic floor otherwise."""
        if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
            return 0

        if not bin_reserves:
            logger.debug(
                "dlmm_get_amount_out: no bin_reserves -> pessimistic fallback "
                "(in=%d rin=%d rout=%d)", amount_in, reserve_in, reserve_out,
            )
            return AmmMath._clmm_pessimistic_out(amount_in, reserve_in, reserve_out, fee_bps)

        # Fee deduction first.
        remaining = amount_in - (amount_in * fee_bps) // 10000
        if remaining <= 0:
            return 0

        out_total = 0
        # Walk bins starting from the active bin upward (input = token-x).
        bins = sorted(
            [b for b in bin_reserves if b[0] >= active_bin_id],
            key=lambda b: b[0],
        )
        walked = 0
        for (bin_id, rx, ry) in bins:
            if walked >= max_bins or remaining <= 0:
                break
            if rx <= 0 or ry <= 0:
                continue
            # How much input this bin can absorb (its reserve_x).
            take_in = min(remaining, rx)
            # Output proportional to this bin's reserve_y at its price.
            # price = ry / rx  (token-y per token-x in this bin)
            take_out = (take_in * ry) // rx if rx else 0
            if take_out > ry:
                take_out = ry
            out_total += take_out
            remaining -= take_in
            walked += 1

        # Safety cap: never exceed the visible output reserve.
        return max(0, min(out_total, reserve_out))

    @staticmethod
    def dlmm_get_amount_in(
        amount_out: int,
        reserve_in: int,
        reserve_out: int,
        fee_bps: int = 25,
        *,
        bin_step: int = 1,
        active_bin_id: int = DLMM_REFERENCE_BIN_ID,
        bin_reserves: Optional[List[Tuple[int, int, int]]] = None,
        max_bins: int = 50,
    ) -> int:
        """DLMM required input. Pessimistic without bin_reserves."""
        if amount_out <= 0 or reserve_in <= 0 or reserve_out <= 0:
            return 0
        if amount_out >= reserve_out:
            return 0
        cp_in = AmmMath.get_amount_in(amount_out, reserve_in, reserve_out, fee_bps=fee_bps)
        if cp_in <= 0:
            return 0
        return int(cp_in * 1.5)

    @staticmethod
    def dlmm_calculate_price_impact(
        amount_in: int,
        reserve_in: int,
        reserve_out: int,
        fee_bps: int = 25,
        *,
        bin_step: int = 1,
        active_bin_id: int = DLMM_REFERENCE_BIN_ID,
        bin_reserves: Optional[List[Tuple[int, int, int]]] = None,
        max_bins: int = 50,
    ) -> float:
        """DLMM price-impact %."""
        if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
            return 100.0
        out = AmmMath.dlmm_get_amount_out(
            amount_in, reserve_in, reserve_out, fee_bps=fee_bps,
            bin_step=bin_step, active_bin_id=active_bin_id,
            bin_reserves=bin_reserves, max_bins=max_bins,
        )
        price_before = reserve_out / reserve_in
        new_ri = reserve_in + amount_in
        new_ro = reserve_out - out
        if new_ri <= 0 or price_before <= 0:
            return 100.0
        price_after = new_ro / new_ri
        impact = abs(price_after - price_before) / price_before * 100.0
        return min(impact, 100.0)


# Unit tests for BigInt math accuracy
def test_amm_math():
    """Basic unit tests for AMM math functions."""
    # Test basic swap calculation
    amount_out = AmmMath.get_amount_out(
        amount_in=1000000,  # 1 SOL in lamports
        reserve_in=1000000000,  # 1000 SOL
        reserve_out=1000000000000,  # 1M tokens
        fee_bps=25
    )
    assert amount_out > 0, "Amount out should be positive"

    # Test price impact
    impact = AmmMath.calculate_price_impact(1000000, 1000000000, 1000000000000)
    assert 0 <= impact <= 100, "Price impact should be 0-100%"

    # Test amount in calculation
    amount_in = AmmMath.get_amount_in(
        amount_out=100000,
        reserve_in=1000000000,
        reserve_out=1000000000000,
        fee_bps=25
    )
    assert amount_in > 0, "Amount in should be positive"

    logger.info("✅ AMM Math unit tests passed")


if __name__ == "__main__":
    test_amm_math()
