# P0-3 verification receipt — Raydium CLMM account LEN constants (offline)

**Date:** 2026-11-14 · **Audited main:** bcbc1501 · **Method:** offline re-derivation from the blob-verified vendor snapshot; zero network, zero RPC.

## Conflict being closed

Two P0-3 lanes landed with different CLMM layout constants: lane #613 originally carried `TickArrayState = 10720`, session #607 landed `TickArrayState = 10240 / TickState = 168` ("blob-verified"). Main carries the 10240 version (`src/providers/raydium_clmm_native.py:43 TICK_ARRAY_STATE_LEN = 10240`). CI cannot arbitrate (tests are offline by design), so this receipt re-derives both constants directly from the pinned snapshot.

## Re-derivation from pinned source

Snapshot: `docs/integrations/offline/solana-p0/vendor-reference/raydium/clmm/tick_array.rs.txt` (+ `pool.rs.txt` for REWARD_NUM).

- `pub const REWARD_NUM: usize = 3` (pool.rs.txt:23)
- `TickState::LEN = 4 + 16 + 16 + 16 + 16 + 16*REWARD_NUM + 4*8 + 16 + 4*1`
  = 4 (tick i32) + 16×4 (liquidity_net/liquidity_gross/fee_growth_outside_0/1, i128/u128) + 16×3 (reward_growths [u128;3]) + 32 (order_phase/orders_amount/part_filled_orders_remaining, u64) + 16 (unfilled_ratio_x64 u128) + 12 (padding [u32;3]) = **168**
- `TickArrayState::LEN = 8 + 32 + 4 + TickState::LEN*60 + 1 + 115`
  = 8 (borsh disc) + 32 (pool_id) + 4 (start_tick_index i32) + 168×60 (ticks [TickState; 60], TICK_ARRAY_SIZE_USIZE=60) + 1 (initialized_tick_count u8) + 8 (recent_epoch u64) + 107 (padding [u8;107]) = **10240**

Both groupings of the snapshot's LEN expressions and the raw struct field sums agree: 168 and 10240.

## Verdict

| Constant | Main | Snapshot re-derivation | Verdict |
|---|---|---|---|
| TickState::LEN | 168 | 168 | CORRECT |
| TickArrayState::LEN | 10240 | 10240 | CORRECT |

The #613 value 10720 is factually wrong (it does not match any grouping of the pinned layout). The merged main decoder is verified against the pinned vendor snapshot. This closes the open verification task recorded in the 2026-11-14 coordination notes; no code change required.

## Safety
Offline doc receipt only; no src change; no live claims.
