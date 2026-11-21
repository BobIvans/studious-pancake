# MARKET UNIVERSE + STRATEGY PRIORITY — NOV 2026

## 1. Objective: broadest useful universe, not maximum ticker count

The target is broad **economic and physical market coverage** with explicit evidence tiers. A thousand indexed pools with unknown account state are less useful than a smaller set of verified pool resources with amount-specific quotes and durable traces.

The repository's 33-venue atlas and historic route hypotheses remain discovery coverage targets, not active adapters or proof that every pool exists. The 17-provider flash-funding list is a research inventory, not enabled capital.

## 2. Recommended near-term order

| Priority | Family | Existing owner/status to preserve | Next evidence task | Execution class |
|---|---|---|---|---|
| P0 | CPMM exact cycles | #659 / `src/strategy/cpmm_cycle_binding.py`; offline replay | Reconcile into current canonical observation/data-capture stages; collect no-live proof | Local atomic candidate |
| P0 | Raydium CLMM + Meteora DLMM | PR #660 / native providers | Finish tick/bitmap + dynamic fee and bin array + amount-specific quotes; then rooted capture | Local atomic candidate |
| P0 | Direct Prop AMMs (HumidiFi, SolFi, Tessera, BisonFi, GoonFi, Obric, ZeroFi etc.) | Existing venue/direct-provider research and SUPER-03 boundaries; not one generic AMM | Add source/deployment/program/instruction dossier; validate public SDK/IDL or reverse-engineered bindings against lawful, reproducible vectors; compare direct calls vs Jupiter-composed instructions; exact account closure and fee/compute requirements | Research → local atomic only after proof |
| P1 | Stablecoin peg/triangle | #491 stable-peg owner; R10 historical anchor gap | Prove issuer/redeem anchors where relevant and exact same-chain venue edges; run negative stable mint/pool identity tests | Local atomic or conditional hyperedge |
| P1 | LST spot-market residual | LST residual relations, shells in `src/strategy/strategies.py` | Verify issuer exchange rate and instantaneous exit rights separately; only direct DEX swap edges can be atomic | Spot route local atomic; redemption conditional |
| P1 | Post-swap dislocation / liquidity cliff | EXP-01 / EXP-03, PR118, CLMM/DLMM | Measure first-seen/first-profitable/last-profitable times from coherent post-state; consumed input and survival/crowding | Signal + exact local route candidate |
| P1 | Pump migration / DBC→DAMM | Existing Pump boundary + EXP-02 | Event/migration source and post-migration pool identity, fee/Token-2022 state; never predict migration as a live pool | Discovery/event signal |
| P2 | Phoenix/OpenBook/Manifest orderbook vs AMM | #507/#512 and `src/providers/orderbook/` | Verified live subscriptions, sequence/gap recovery, depth/VWAP/lot/IOC/partial fill and settlement | Local atomic only if one tx fill/settlement proven |
| P2 | Liquidation/health-factor events | `src/liquidation/`, `src/lending_indexer/` | Public rooted account trajectories, oracle freshness, exact liquidation rights, repay + collateral unwind and provider capacity | Conditional/local atomic only if closure proven |
| P2 | Lender selector / flash-mint | R02/R03 + SX-02 | Compare provider assets, caller rules, effective cap, fee, setup/rent, callback, atomic repayment and route asset compatibility | Capital control-plane, not market alpha |
| P3 | Sui markets and local flash capital | DeepBook/Cetus/NAVI owners and Sui wave dossiers | Current package/object/checkpoint/coin type and PTB receipt semantics; one market/protocol at a time | Sui-local atomic candidate only |
| P4 | One EVM pilot | DV-05 / provider expansion | Choose one chain by actual route gap and deployable exact pool + lender resource evidence | EVM-local atomic only |

## 3. Missing or worth reconsidering now

### M01 — Prop AMM direct-vs-aggregator market coverage
Treat each prop AMM as a protocol-specific venue, not a shared generic layout. Record the exact program/deployment ID, account discovery method, instruction source/bindings revision, license, fee/price impact, CU, required accounts, token extensions, failure/revert semantics and quote parity. Use Jupiter route results as comparison metadata; resolve their underlying physical pool lineage. An opaque route is not an independent market edge. A pmm-sim or third-party instruction SDK is a research harness only until its commit/license, supported versions and deployed behavior are pinned and differential-tested. No unsupported direct submission or hidden-order-flow usage.

### M02 — Market event → post-state dislocation (EXP-01)
Build a public/authorized event-to-state experiment: detect an observed pool update or confirmed swap, fetch coherent after-state, evaluate all venues and amounts, record time-to-first-positive and time-to-last-positive, and compare with a time-shuffled/null control. Do not frame this as mempool sniping. Shred feeds, where lawful, are pre-propagation data and not evidence of a publicly settled pool state; rooted/finalized state still confirms the market.

### M03 — Liquidity cliff and amount-survival surface (EXP-03)
For each exact pool amount grid, report usable input, consumed input, output, fees, depth exhausted, tick/bin crossings, partial fill, remaining state and price impact. Record how long the route stays exact and economically positive. Do not scale from one amount or use TVL as depth.

### M04 — Token-2022 path feasibility (EXP-04)
Model epoch transfer fees, withheld amounts, fee caps/rounding, transfer hooks and extra-account-meta dependencies. Token-2022 is a route-feasibility guard and can block an otherwise attractive route. Do not treat symbol and mint as sufficient asset identity.

### M05 — Flash-mint vs flashloan vs self-funded path (SX-02 / R07)
Compare protocol-native temporary issuance and lenders only where the exact same-transaction burn/repayment postcondition exists. Include caller eligibility, asset, cap, fee, callback and setup cost. A flash-mint is not just a zero-fee lender; it may be a distinct transformation/eligibility model.

### M06 — Shared-resource/capital portfolio control (G12/G13/SX-12)
Before parallel strategy execution, ensure one pool, tick/bin set, CLOB depth, lender reserve, collateral unit, account lock, compute budget or API quota cannot be reserved twice. Compare independent single-strategy baseline with joint opportunity allocation. Reuse existing conflict scheduler, reservations, `split_flow.py` and FlashCapitalGraph; no second scheduler/graph.

### M07 — Opportunity survival/crowding (EXP-07)
Capture full candidate lifecycle: discovery → identity → state completeness → exact quote → exact route → positive net → lender eligible → built offline → simulation → paper terminal. Include first/last profitable observations, quote age, state staleness, crowding, no-fill/rejects, false positives and censoring. This will tell us whether faster feeds or extra relays are economically valuable.

### M08 — Orderbook path (CLOB) as a later distinct market data lane
Do not merge CLOB into AMM math. Subscription sequence, snapshot/delta recovery, price-time priority, lot/tick, VWAP, IOC, partial fill and atomic settlement are separate exactness contracts.

### M09 — Solvency/liquidation as downstream signal
Monitor health distance, debt/collateral, oracle confidence, caps and liquidation competition. Do not promote as flashloan route until collateral can be seized and exactly unwound in the same transaction with repayment covered.

## 4. Deliberately not first-wave atomic strategies

Keep cross-chain/bridge, CEX/DEX settlement, funding-rate carry, Pendle/PT/YT maturity, queued LST exits, issuer redemption queues, vault withdrawal locks, prediction-market resolution and other time-delayed rights as reference, inventory or research hypotheses unless a separate exact same-domain atomic mechanism is proved. Preserve their owners and research rows; do not delete them.

## 5. Prop AMM flow integrity policy

Do not build strategies to disguise toxic flow, impersonate retail flow, randomize transactions to evade venue protections, or target users. Order splitting is allowed only when justified by measured liquidity/price impact, route capacity, risk limits or provider limits, with shared pool resources reserved jointly. Record each split leg and the aggregate result. No sandwich, frontrun, victim targeting or unauthorized private order flow.
