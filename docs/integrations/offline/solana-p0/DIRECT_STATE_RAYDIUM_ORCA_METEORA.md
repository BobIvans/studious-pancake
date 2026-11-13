# Direct pool-state verification — Raydium, Orca, Meteora DLMM

This document is an implementation reference, not a copied SDK. Exact upstream commits, source blob IDs, deployment IDs and license notes are in `SOURCE_MANIFEST.json`.

## Shared verifier contract

For every venue reader:
1. Read pool and all dependent accounts under a consistent finalized commitment (or explicitly provisional state).
2. Assert cluster genesis, pool owner/program ID, expected discriminator/version and exact account length/layout.
3. Verify ordered token mints, token program IDs, vault addresses and vault mint/authority relationships.
4. Read mint decimals and Token-2022 extensions from chain; include transfer-fee/hook semantics in economics.
5. Preserve raw account bytes, SHA-256, account pubkeys, context slot, RPC provider identity and decoder version.
6. Compute exact-in output for an input amount through the venue's current state math. Use integer/fixed-point arithmetic matching the venue implementation; never float for consensus-sensitive values.
7. Reject insufficient initialized liquidity, missing tick/bin data, stale dependent accounts, unsupported program versions and partial RPC snapshots.
8. Never infer executable depth from an API's TVL, token reserve total, pool label, or sum of vault balances alone.

## Raydium CPMM

Mainnet program ID recorded from the pinned program source:
`CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C`.

Relevant upstream source is mirrored as inert text under `vendor-reference/raydium/cpmm/`:
- `pool.rs.txt` — zero-copy pool state, seeds, status and vault/mint configuration.
- `config.rs.txt` — AMM config and fee configuration fields.
- `swap_base_input.rs.txt`, `fees.rs.txt`, `constant_product.rs.txt` — input swap, fee and constant-product math.
- Upstream Apache-2.0 license text is retained at `vendor-reference/raydium/LICENSE-APACHE-2.0.txt`.
- The repo already contains a native Raydium CPMM decoder/collector. **Audit and reuse that canonical owner**; do not write a second CPMM decoder.

Reader must bind the pool account to the expected CPMM program, decode its exact pinned pool state, validate token mints/vaults and fetch vault token-account balances at the same or bounded slot. Decode the current fee configuration and pool status flags before treating swaps as possible. Keep unsupported extensions and changed layouts fail-closed.

## Raydium CLMM

Mainnet program ID recorded from the pinned CLMM program source:
`CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK`.

Selected upstream files are mirrored as inert text under `vendor-reference/raydium/clmm/`:
- `pool.rs.txt` — PoolState, PDA seeds, price/liquidity, fee and status fields.
- `tick_array.rs.txt`, `tick_array_bit_map.rs.txt` — initialized tick array and bitmap traversal.
- `swap_math.rs.txt`, `tick_math.rs.txt` — exact swap and tick math reference.
- `config.rs.txt` — AMM fee/config fields.
- These are from the pinned Apache-2.0 program repository and are not imported as project dependencies.

Exact CLMM depth requires more than pool vault totals:
- pool liquidity and Q64.64 sqrt price/current tick;
- initialized tick arrays and bitmap extension where required;
- per-tick liquidity net/gross and fee-growth/fee state;
- correct direction-specific traversal across initialized ticks;
- current fee configuration and Token-2022 transfer semantics.

A reader that only fetches PoolState but not required tick arrays can report spot state, not amount-specific executable liquidity.

## Orca Whirlpools

Mainnet program ID:
`whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc`.

Pinned source facts:
- Whirlpool state stores config, tick spacing, fee rate, protocol fee rate, u128 liquidity, Q64.64 sqrt price, current tick, token mint/vault A and B, fee-growth and rewards.
- The reviewed source defines `Whirlpool::LEN = 8 + 261 + 384 = 653` bytes.
- Tick arrays have 88 tick slots in the fixed-array path; current program source also distinguishes dynamic tick arrays with a separate discriminator/layout. Decode the exact array variant and only count initialized ticks.
- Relevant pinned source paths: `programs/whirlpool/src/state/whirlpool.rs` and `programs/whirlpool/src/state/tick_array.rs`. Generated client decoders are in the current TS SDK tree.

**License blocker:** the current upstream repo's LICENSE states that code published from 2025-02-27 onward is under a custom Orca License, whereas the prior code was Apache-2.0. Do not vendor Orca implementation, use the SDK as a dependency or copy generated code into this repository until legal approval confirms the intended use is allowed. The public facts above are included as technical research notes only; an independent implementation must be separately reviewed for license compliance. Until this is resolved, report Orca direct-state integration as `BLOCKED_LICENSE_REVIEW`, not PASS.

## Meteora DLMM

Mainnet program ID from the pinned SDK/docs:
`LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo`.

Pinned SDK and offline source snapshots:
- full Anchor IDL mirrored at `vendor-reference/meteora/lb_clmm.idl.json` (IDL metadata version `0.12.0`);
- helpers/types/quote example and SDK entrypoint mirrored as `.ts.txt` under `vendor-reference/meteora/`;
- package `@meteora-ag/dlmm` version `1.9.15`, package metadata declares license `ISC`;
- relevant account types include `LbPair`, `BinArray`, `PositionV2`, limit-order structures and preset parameters;
- account guide describes `LbPair`, reserve vaults, `BinArray`, `BinArrayBitmapExtension`, `Oracle`, position accounts and deterministic PDA derivations;
- SDK `getTokensMintFromPoolAddress` validates the pool account exists then reads X/Y mints; `getTokenProgramId` maps pool flags to SPL Token vs Token-2022.

Exact DLMM liquidity is bin-based. The reader must:
- validate LbPair owner/version, token X/Y mints, token program flags and reserve vaults;
- fetch the active bin and every directionally reachable BinArray required by the quote;
- decode bin reserves/liquidity, bin step/price, bitmap extension and dynamic fee parameters;
- apply the official per-bin price/fee math and transfer-fee semantics for the exact amount;
- reject missing bins, stale bin-array accounts, unsupported pair types and partial state.

An API's pool TVL or total reserve balance is not the amount available at the active price. Only the reachable bins and exact fee logic support an amount-specific estimate.

## Minimum offline fixtures to add in P0-3

For each venue/family:
- known-good pool state;
- wrong owner/program;
- unknown discriminator/version;
- truncated/extra-length account;
- wrong mint or vault mint;
- stale/mismatched context slot;
- missing tick/bin array;
- zero liquidity / paused swap flag;
- unsupported token program or Token-2022 extension;
- exact-in input amounts that cross 0, 1 and multiple tick/bin boundaries;
- rounding/fee edge cases and minimum-output comparison.

All exact quote outputs must be differential-tested against published venue SDK/reference vectors where license-compliant, or against reproducible local fixtures created from observed public chain data. No live chain data or execution is needed for offline tests.
