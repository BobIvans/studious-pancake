# DATA CAPTURE → EXACT MARKET → PAPER QUALIFICATION GATES

## 1. Three distinct campaign states

| State | Purpose | Allowed actions | What it does NOT prove |
|---|---|---|---|
| `CAPTURE_ONLY` | Build broad market universe and source-quality evidence | Governed read-only discovery, identity resolution, bounded account reads where separately authorized, event/reference capture, raw journal, replay | Exact executable depth, profitable route, loan capacity, paper qualification |
| `EXACT_SHADOW_CANDIDATE` | Prove complete amount-specific direct edges and route economics | Exact local quote math, cross-check, PR118 size-grid evaluation, route/resource dedup, offline builds and authorized exact simulation prerequisites | Lender qualification or paper PASS by itself |
| `PAPER_QUALIFICATION` | Installed canonical sender-free qualification | Only through R06/QPR/campaign authority, accepted R02+R03, required R05 simulation and installed paper service | Live trading / signer / production readiness |

The first run requested here is `CAPTURE_ONLY`. It can start before every R02/R03/R05 paper prerequisite is complete, but it must report exact blockers and may not claim `PAPER_QUALIFIED`.

## 2. Gate 0 — campaign authority and source preflight

Before any read:
- Pin current main SHA, runtime authority generation/hash, policy bundle, source registry and manifest digest.
- Validate `CAMPAIGN_START_V1`; require current docs, license/ToS, auth scope, endpoint, schema, limits, rate/physical attempt budgets, storage cap and rollback.
- Verify each provider's owner, source/operator identity, correlation group and whether it is actually independent from another provider.
- No credential probing. A configured secret reference may be declared by the human/operator, but its value never enters source code, PR text, logs or this pack.
- Keep public/shared Solana RPC exploratory only. A single RPC can produce candidate capture but status stays `BLOCKED_SINGLE_SOURCE` for rooted verdict.
- For a claimed independent rooted source set, require at least two separately operated providers/correlation groups, same genesis and compatible rooted/finalized commitment, explicit slot/context for every response, bounded observed skew and state/account hash comparison.

## 3. Gate A — read-only universe capture

Start with SOL/USDC as a benchmark **search hint**, plus broad ranked discovery from existing DEX Screener, GeckoTerminal, Raydium and Meteora source adapters. Do not hardcode that any pair or pool exists. Add USDC/USDT, SOL/JitoSOL, SOL/mSOL, SOL/JupSOL and other discovered assets only after exact mint, token program, decimals and extension checks.

Capture per candidate:
- source id/generation/provider/operator/correlation group; request fingerprint and raw response hash;
- chain genesis, venue/program/deployment id, pool/market address and exact mint ordering;
- listed fee/tier, pool version/config metadata and source time, clearly flagged as indexed vs rooted;
- decision: admitted to identity check, discovery-only, unsupported, duplicate/alias, stale, rate-limited, schema drift, missing source or other typed reject;
- quota physical attempt count, latency, response size, retries/backoff and storage consumption.

Use source rotation by pair/venue/market diversity and candidate value, plus explicit negative-control fraction from the campaign manifest. Don't over-index one popular pair or one discovery provider.

## 4. Gate B — identity and exact-state qualification

For identity:
- exact mint address + token program + decimals + relevant Token-2022 extensions; chain genesis, not ticker, creates asset identity;
- exact venue program/deployment + pool id + token order + vault/reserve/resource identities;
- alias/wrapper assets are distinct unless a canonical conversion relation proves equivalence.

For account reads:
- preserve exact raw bytes, account pubkey, owner, discriminator/layout/version, context slot, commitment, endpoint/operator/source generation and SHA-256.
- Use `getMultipleAccounts` batches of at most 100 accounts (the RPC contract limit); every response has its own context. For more than one batch, keep per-batch context and enforce the approved minContextSlot/bounded-skew policy. Never label separately fetched batches as one shared slot.
- Capture the full dependent state closure, not just PoolState/vault balances: CLMM tick arrays and bitmap extension/dynamic fee; DLMM active and directionally reachable BinArrays/bitmap extension/dynamic fee/clock/epoch/token extensions; CPMM config/fee/vaults; orderbook snapshot + deltas and sequence where applicable.
- If the data collector can't guarantee coherent state, store the negative reason and keep the candidate unqualified.
- Helius/Yellowstone/gRPC/shred feed can trigger a refresh but do not replace the full rooted account snapshot required for exact quotes.

## 5. Gate C — quote and route candidate

- Direct evaluator is source of exact amount-specific quote. Jupiter V2 / 0x / Titan / other aggregator are route comparators only. Do not count 2 aggregators or two routes to same underlying pool as 2 independent pools.
- For every amount, quote freshly. Require same raw input, same canonical input/output, compatible taker/fee assumption and bounded time skew for comparisons. Never scale a quote or marginal price.
- Require full consumed input for cycle eligibility. A partial-fill quote is separately labeled and cannot close a flashloan cycle unless the exact residual/repayment model is proven.
- Route path uses existing observation → graph → #659 cycle binding → R13-K physical resource dedup → PR118 amount grid → all-in economics. Do not add a second cycle solver.
- Account for embedded pool fees, token transfer fees, protocol fees, priority fee, relay tip, lender fee, rent/setup cost, provider charges, CU limit, failure/revert fees and residual assets. UNKNOWN cost blocks positive net result.
- Store all candidates, including negative, no-trade, stale, incomplete, alias, underfunded, no-route and non-profitable outcomes.

## 6. Gate D — lender, builder and exact simulation

- R02 one provider at a time: Solana priority Project 0, Kamino, Jupiter Lend; Save/Solend only after current support proof; MarginFi remains independent and gate-limited. Sui NAVI/DeepBook later under Sui checkpoint/PTB rules.
- Effective capacity needs resource identity, deployed owner/version, mint/decimals, reserve/vault, utilization/ceilings/liabilities, exact fee+rounding, availability, slot/freshness and independent provenance. Vault cash or TVL does not equal borrowable capacity.
- R03 unsigned builder must prove same mint/principal, repay math, callback/bookend or hot-potato receipt, account requirements and instruction ordering. `BUILT_OFFLINE_UNQUALIFIED` is not capacity-qualified.
- R05 must simulate the final exact message/PTB with all route, lender, compute-budget, priority-fee, tip, rent/account and repayment instructions and matching state-generation fingerprints. It is not enough to simulate swap legs independently.
- R04/R02/R03/R05 gates must be consumed by the existing candidate selector; no manually asserted boolean can override a blocker.

## 7. Gate E — existing R06 installed paper qualification

Only start after the R06 owner/QPR-01/02/03 + campaign authority returns its exact PASS. Use the installed canonical sender-free paper service and existing durable lifecycle/journal, not a custom while-loop or independent paper runner.

Mandatory evidence:
- exact main/config/source generation and campaign manifest;
- candidate/event counts derived from unique journal ids, not manually entered totals;
- source observations and every quote/build/simulation/economic/terminal event;
- deterministic network-disabled replay with zero outbound calls;
- all admitted candidates have durable terminal outcomes; no UNKNOWN terminal;
- provider outage, quota exhaustion, RPC quorum loss, clock/slot skew, stale state, DB contention, cancellation, restart recovery, backpressure/storage pressure and replay mismatch scenarios;
- measured queue age, worker heartbeat, event loop lag, terminal SLO, shutdown drain and restart behavior;
- if this is an installed 72-hour soak, use MPR-05 contract (72h, installed wheel/container, production composition root, required dependency hashes, replay and fault injections) rather than treating a short capture as a soak.

A 24-hour data observation window is useful for market coverage; it does not replace the separate 72-hour installed paper qualification requirement or prove profitability.

## 8. Metrics and denominators

Report separately (fixture/replay vs live capture):
- discovery candidates by source/venue/pair;
- canonical identities verified;
- unique physical pools/markets after alias and aggregator-route de-dup;
- complete rooted state sets by venue and source group;
- exact quotes by venue × direction × input amount;
- complete exact routes by hop count;
- partial/incomplete/stale rejects;
- positive gross vs positive all-in net opportunities;
- first-seen / first-positive / last-positive / survival time;
- R02 qualified assets/amounts and unique lender resources;
- R03 builder-conformant plans;
- R05 exact simulations passed/failed;
- R06 paper terminal outcomes and terminal SLO;
- provider request cost, retries, rate-limits, data latency, slot skew, dropped/gapped events, storage bytes and replay divergence.

All percentages must show numerator and denominator. Keep unknowns and unavailable observations in their own population.

## 9. Hard stops

Stop or downgrade to exploratory/BLOCKED on missing campaign authority, one-source quorum claim, source identity drift, docs/license/ToS drift, stale or mixed state, incomplete tick/bin/book, unsupported Token-2022 extension, unknown fee/cost, capacity disagreement, alias collisions, any quote mismatch, incomplete repayment, stale blockhash or ambiguous earlier attempt, journal corruption, worker heartbeat failure, unbounded queue/storage, non-deterministic replay or a requested capability outside this campaign's authorization.
