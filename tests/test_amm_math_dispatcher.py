import pytest
pytestmark = pytest.mark.unit
#!/usr/bin/env python3
"""
Unit Tests for AMM Math Dispatcher (БЛОК 2)

Covers:
  - classify_pool_type: program-id → pool-type mapping (all known DEXes)
  - pool_type normalisation (cpmm / "" / None → constant_product)
  - Stableswap: more output than CPMM on a balanced pool; round-trip get_in
  - CLMM: honest tick-walk with state; pessimistic fallback (≤ CPMM) without state
  - DLMM: bin traversal with bin_reserves; pessimistic fallback (≤ CPMM) without
  - backward-compat: constant_product dispatch == legacy AmmMath
"""


import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from ingest.amm_math import AmmMath
from ingest.amm_math_dispatcher import (
    AmmMathDispatcher,
    classify_pool_type,
)


class TestClassifyPoolType(unittest.TestCase):
    def test_known_program_ids(self):
        self.assertEqual(classify_pool_type("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"), "constant_product")
        self.assertEqual(classify_pool_type("CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"), "constant_product")
        self.assertEqual(classify_pool_type("whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"), "clmm")
        self.assertEqual(classify_pool_type("CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"), "clmm")
        self.assertEqual(classify_pool_type("LBUZKhRxPF3XUpBCjp4YzTKgLLjggiJWUna9LZJRQD3"), "dlmm")
        self.assertEqual(classify_pool_type("SSwpkEEcbUqx4uweEw4KsK9cZ4cwvJj2w2mYbFXM7Yr"), "stableswap")

    def test_unknown_and_empty(self):
        # Unknown / None / empty default to the safe constant_product curve.
        self.assertEqual(classify_pool_type(None), "constant_product")
        self.assertEqual(classify_pool_type(""), "constant_product")
        self.assertEqual(classify_pool_type("SomeUnknownProgram123"), "constant_product")

    def test_method_on_dispatcher_class(self):
        self.assertEqual(
            AmmMathDispatcher.classify_pool_type("LBUZKhRxPF3XUpBCjp4YzTKgLLjggiJWUna9LZJRQD3"),
            "dlmm",
        )


class TestPoolTypeNormalisation(unittest.TestCase):
    def test_cpmm_alias_equals_constant_product(self):
        rin, rout, ain = 1_000_000_000, 1_000_000_000, 1_000_000
        legacy = AmmMath.get_amount_out(ain, rin, rout)
        for alias in ("cpmm", "", None, "Constant_Product", "XYK"):
            self.assertEqual(
                AmmMathDispatcher.get_amount_out(ain, rin, rout, pool_type=alias),
                legacy,
                f"alias {alias!r} must match legacy CPMM",
            )


class TestStableswap(unittest.TestCase):
    def test_balanced_pool_gives_more_than_cpmm(self):
        # Balanced stable pool: StableSwap curve is flatter → less slippage → more out.
        rin, rout, ain = 1_000_000_000, 1_000_000_000, 1_000_000
        ss = AmmMathDispatcher.get_amount_out(
            ain, rin, rout, pool_type="stableswap", amp=100, fee_bps=0,
        )
        cp = AmmMath.get_amount_out(ain, rin, rout, fee_bps=0)
        self.assertGreater(ss, cp)
        self.assertLessEqual(ss, ain)  # cannot create money out of thin air

    def test_higher_amp_more_linear(self):
        # As amp → ∞ the curve approaches linear (x+y=D): output → input.
        rin, rout, ain = 1_000_000_000, 1_000_000_000, 1_000_000
        out_low = AmmMathDispatcher.get_amount_out(ain, rin, rout, pool_type="stableswap", amp=10, fee_bps=0)
        out_high = AmmMathDispatcher.get_amount_out(ain, rin, rout, pool_type="stableswap", amp=1000, fee_bps=0)
        self.assertGreaterEqual(out_high, out_low)

    def test_get_amount_in_round_trip(self):
        rin, rout, ain = 1_000_000_000, 1_000_000_000, 1_000_000
        out = AmmMathDispatcher.get_amount_out(
            ain, rin, rout, pool_type="stableswap", amp=100, fee_bps=4,
        )
        ain_back = AmmMathDispatcher.get_amount_in(
            out, rin, rout, pool_type="stableswap", amp=100, fee_bps=4,
        )
        # Allow a small integer-division tolerance.
        self.assertGreater(ain_back, 0)
        self.assertAlmostEqual(ain_back, ain, delta=max(10, ain * 0.001))

    def test_zero_and_degenerate(self):
        self.assertEqual(
            AmmMathDispatcher.get_amount_out(0, 1000, 1000, pool_type="stableswap", amp=100),
            0,
        )
        self.assertEqual(
            AmmMathDispatcher.get_amount_out(1000, 0, 1000, pool_type="stableswap", amp=100),
            0,
        )


class TestCLMM(unittest.TestCase):
    def test_fallback_is_pessimistic(self):
        # Without tick state the dispatcher must return <= CPMM output
        # (never under-estimate slippage on concentrated liquidity).
        rin, rout, ain = 1_000_000_000, 1_000_000_000, 5_000_000
        clmm = AmmMathDispatcher.get_amount_out(ain, rin, rout, pool_type="clmm")
        cp = AmmMath.get_amount_out(ain, rin, rout)
        self.assertGreater(clmm, 0)
        self.assertLessEqual(clmm, cp)

    def test_fallback_worsens_rate_with_trade_size(self):
        # Bigger trades relative to liquidity → worse effective price (more slippage).
        # We compare the per-unit rate (out/in), not absolute output.
        rin, rout = 1_000_000_000, 1_000_000_000
        small_ain = 100_000
        large_ain = 500_000_000
        small = AmmMathDispatcher.get_amount_out(small_ain, rin, rout, pool_type="clmm")
        large = AmmMathDispatcher.get_amount_out(large_ain, rin, rout, pool_type="clmm")
        rate_small = small / small_ain
        rate_large = large / large_ain
        self.assertGreater(rate_small, 0)
        self.assertGreaterEqual(rate_small, rate_large)

    def test_tick_walk_with_state(self):
        # Provide minimal honest state: current sqrt_price, liquidity, ticks.
        # We only assert it returns a deterministic, positive, bounded output.
        rin, rout, ain = 1_000_000_000, 1_000_000_000, 1_000_000
        out = AmmMathDispatcher.get_amount_out(
            ain, rin, rout, pool_type="clmm",
            sqrt_price_x64=1 << 64,  # price ≈ 1.0
            liquidity=10 ** 18,
            tick_current=0,
            tick_spacing=1,
            tick_array=[(1, 10 ** 9), (2, 10 ** 9), (3, 10 ** 9)],
            max_ticks=50,
        )
        self.assertGreater(out, 0)
        self.assertLessEqual(out, rout)


class TestDLMM(unittest.TestCase):
    def test_fallback_is_pessimistic(self):
        rin, rout, ain = 1_000_000_000, 1_000_000_000, 5_000_000
        dlmm = AmmMathDispatcher.get_amount_out(ain, rin, rout, pool_type="dlmm")
        cp = AmmMath.get_amount_out(ain, rin, rout)
        self.assertGreater(dlmm, 0)
        self.assertLessEqual(dlmm, cp)

    def test_bin_traversal(self):
        # Three bins at the reference bin, each holding 1e6 in / 1e6 out.
        rin, rout, ain = 3_000_000, 3_000_000, 2_000_000
        out = AmmMathDispatcher.get_amount_out(
            ain, rin, rout, pool_type="dlmm", bin_step=1,
            active_bin_id=8_388_608,
            bin_reserves=[
                (8_388_608, 1_000_000, 1_000_000),
                (8_388_609, 1_000_000, 1_000_000),
                (8_388_610, 1_000_000, 1_000_000),
            ],
            max_bins=50,
        )
        # Should consume 2 of the 3 bins (after fee) → output proportional.
        self.assertGreater(out, 0)
        self.assertLessEqual(out, rout)

    def test_max_bins_cap(self):
        # max_bins=1 should limit traversal to a single bin.
        out_capped = AmmMathDispatcher.get_amount_out(
            10_000_000, 10_000_000, 10_000_000, pool_type="dlmm", bin_step=1,
            active_bin_id=8_388_608,
            bin_reserves=[(8_388_608 + i, 1_000_000, 1_000_000) for i in range(20)],
            max_bins=1,
        )
        out_full = AmmMathDispatcher.get_amount_out(
            10_000_000, 10_000_000, 10_000_000, pool_type="dlmm", bin_step=1,
            active_bin_id=8_388_608,
            bin_reserves=[(8_388_608 + i, 1_000_000, 1_000_000) for i in range(20)],
            max_bins=50,
        )
        self.assertLessEqual(out_capped, out_full)


class TestBackwardCompat(unittest.TestCase):
    def test_constant_product_identical_to_legacy(self):
        for ain, rin, rout in [
            (1_000_000, 1_000_000_000, 2_000_000_000),
            (5_000, 10_000, 9_000),
            (123_456_789, 999_999_999_999, 1_111_111_111),
        ]:
            self.assertEqual(
                AmmMathDispatcher.get_amount_out(ain, rin, rout, pool_type="constant_product"),
                AmmMath.get_amount_out(ain, rin, rout),
            )
            self.assertEqual(
                AmmMathDispatcher.get_amount_in(1_000, rin, rout, pool_type="constant_product"),
                AmmMath.get_amount_in(1_000, rin, rout),
            )


class TestHopHelper(unittest.TestCase):
    def test_hop_via_program_id(self):
        hop = {"programId": "LBUZKhRxPF3XUpBCjp4YzTKgLLjggiJWUna9LZJRQD3", "fee_bps": 25}
        out = AmmMathDispatcher.get_amount_out_for_hop(
            1_000_000, 1_000_000_000, 1_000_000_000, hop,
        )
        self.assertGreater(out, 0)

    def test_hop_via_pool_type(self):
        hop = {"pool_type": "stableswap", "amp": 100, "fee_bps": 4}
        out = AmmMathDispatcher.get_amount_out_for_hop(
            1_000_000, 1_000_000_000, 1_000_000_000, hop,
        )
        # Stableswap on a balanced pool should beat CPMM.
        cp = AmmMath.get_amount_out(1_000_000, 1_000_000_000, 1_000_000_000, fee_bps=4)
        self.assertGreater(out, cp)


if __name__ == '__main__':
    unittest.main(verbosity=2)
