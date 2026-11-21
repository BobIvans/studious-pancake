# Route and multi-tracer plan — CLMM / DLMM / Jupiter Lend

## 1. Working architecture

DEX Screener / Raydium API V3 / Meteora Data API
                 |
                 v
 Existing MarketSourceCatalog + Discovery + provider governance
                 |
                 v
 canonical mint/pool identity resolution (exact addresses only)
                 |
                 v
 Primary + independent secondary Solana RPC account snapshots
                 |
        +--------+---------+
        |                  |
        v                  v
 Raydium CLMM           Meteora DLMM
 Pool/Config/           LbPair/Bitmap/
 BitmapExt/Ticks         BinArrays/Clock
 DynamicFee             DynamicFee/Token-2022
 exact-in quote          exact-in quote
        |                  |
        +--------+---------+
                 |
                 v
 MarketObservationV2 + durable cursor/watermark/provenance
                 |
                 v
 Graph + R10-1 cycle binding + R13-K pool/route de-dup
                 |
                 v
 PR118 per-size sequential re-quote + all-in costs
                 |
                 v
 Jupiter Lend CAP-A resource gate + R03 unsigned plan gate
                 |
                 v
 R05 atomic simulation gate (blocked until required live proof)
                 |
                 v
 R06 sender-free paper evidence (only after QPR readiness)

The diagram is the planned wiring. Current P0 venue decoders, R10-1 and source adapters have different evidence levels; they are not currently one continuously running live service.

## 2. What counts as a route edge

An exact venue edge needs:
- canonical mint from/to identities (chain genesis, mint, token program, decimals, extension facts);
- physical pool identity (program ID, pool address, venue family, fee/config revision, vault/resource IDs);
- exact account dependency set and hashes (ticks or bins, bitmap extension, fee state, vault/mint state);
- account context slot / source generation / timestamp and freshness;
- raw input, consumed input, output, all fees and rounding, min output and quote expiry;
- exact venue math revision and external source pin.

A quote from Jupiter or 0x is a route observation, not an executable physical pool edge unless each underlying pool is resolved and deduplicated. If route lineage is opaque, mark resource independence UNKNOWN.

## 3. Pair and route seed plan

Seed hints for discovery (not hardcoded market assumptions):
- SOL/USDC: primary benchmark. These assets already appear in the existing core-jupiter-lend-jupiter-v1 profile / runtime discovery. Use exact mint identities; don't assume all venues currently have a pool.
- USDC/USDT: optional stable pair if both exact mints and venue markets are discovered.
- SOL/mSOL or SOL/JitoSOL: only direct DEX swap pools. Do not model staking, unstake queues, epoch exits or redeem functions as immediate swap edges.
- Long-tail pairs: include only after pool, mint, Token-2022 extensions and source freshness are verified.

Required baseline route patterns:
- Two-leg same pair: A → B on Raydium CLMM + B → A on Meteora DLMM; run both orientations when exact pools exist.
- Mixed 3-leg triangle: e.g. SOL → USDC → USDT → SOL, only when all three actual pools are discovered and exact.
- Mixed 4-leg cycle: only after 3-leg mixed cycle passes; all edges must be rooted, current and amount-specific.
- Include CPMM legs in mixed routes using the R10-1 exact CPMM evaluator after #659 is merged.

## 4. Split flow and orderbook dependencies

Split-flow is strongly adjacent but must not be the first task. Only after a single CLMM/DLMM route has exact capacity and common-state resource identities should the current src/economics/split_flow.py owner be extended. The same physical pool/bin/tick/account resource must be consumed jointly across branches. Never give every split branch the pool's full liquidity.

Orderbook/AMM is a later workstream, not a blocker for CLMM/DLMM. Reuse PR #507/#512 owners and require verified Phoenix/OpenBook subscriptions, sequence/slot continuity, depth, tick/lot sizes, VWAP, partial fills, cancel/IOC and settlement/account readiness before routing any CLOB leg.

## 5. Financing and signer separation

Jupiter Lend belongs after route economics as a separate funding resource:
- market path asks “is the route profitable before/after financing?”;
- lender gate asks “is this mint/amount actually borrowable right now under the deployed program's current fee/capacity rules?”;
- builder gate assembles borrow + swap legs + payback as unsigned instructions;
- simulator gate proves the same complete atomic transaction under rooted state;
- signer is a distinct authority subsystem and remains disabled.

Docs say Jupiter Lend flashloans have no collateral and no fees if repaid in the same transaction. The repository must still read and validate the live on-chain fee field, TokenReserve, vault, borrow position and capacity. Documentation is not current capacity evidence and must not override flashloan_fee decoded by the existing adapter.

## 6. Tracing metrics

Keep these populations distinct and split fixture vs live:
- indexed discovery candidates;
- canonical identity verified pools;
- CLMM complete state / dynamic fee qualified;
- DLMM complete state / fee/token extension qualified;
- exact quotes by venue and amount;
- mixed exact route candidates;
- unique underlying physical resource routes;
- aliases/correlation-group collisions;
- non-positive net economics;
- qualified lender amount/resource;
- unsigned build-conformant routes;
- exact simulation pass;
- paper completed / rejected.

Report by pair mint addresses, venue pair, route hop count, input amount, data age, context slot skew, fees, source operator, RPC quorum and rejection reason. Do not publish one aggregate “success rate” without its denominator and evidence class.

## 7. Minimum trace success

The data substrate is ready for a read-only live campaign when:
1. source APIs are documented, pinned, governed and bounded;
2. a bounded discovery response produces verified current pool addresses;
3. at least two independent RPC sources provide fresh coherent account sets (with explicit bounded slot skew);
4. both CLMM and DLMM direct quote engines return exact amount-specific outputs for a set of supported pools, with all fees and consumed input explained;
5. each observation enters the existing canonical market/graph path with provenance;
6. mixed route replay is deterministic and pool-resource dedup passes;
7. R02/R03 and R05/R06 blockers are listed independently, not hidden behind market-trace success.

Live paper or trade promotion is a later gate. This PR does not enable it.
