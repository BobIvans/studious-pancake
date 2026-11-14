# Codex trigger — broaden and wire the arbitrage strategy/data-source map

Repository: BobIvans/studious-pancake

Read, in order:
1. AGENTS.md and root CODEX_START_HERE.md.
2. MASTER_FLASHLOAN_MARKET_INTEGRATION_AND_BUILD_BIGGER_UNIVERSE_RU.md and BUILD_BIGGER_UNIVERSE_GRAPH_ARCHIVE_RECONCILIATION_RU.md.
3. ARBITRAGE_MAP_STRATEGY_AND_DATA_SOURCE_ATLAS_RU.md.
4. ARBITRAGE_DATA_SOURCE_CATALOG_V1.json.
5. ARBITRAGE_MAP_DATA_SOURCE_ASSIGNMENTS_RU.md.
6. Existing P0, GPR, DV, R02/R03/R04/R05/R06, R13, R10, SX, EXP, W6, PAIR-00 and #654 detector taxonomy assignments.

You are the lead research/integration coordinator for the widest evidence-backed arbitrage map. Do not create another graph, market universe, quote router, source registry, capital graph, strategy registry, scheduler, journal or execution kernel. First audit latest main, all open/merged PRs, actual code owners, official external docs and archive rows. Do not treat closed PRs as failed or superseded without reading their discussion; work may be transferred to another agent/session.

Preserve all archived strategy families and source hypotheses. Expand the data-source map across Solana, Sui, EVM, TON and other research domains, but classify atomic, conditional-rights, signal-only and hedged/non-atomic strategies correctly. The strategy atlas is the inventory; your actual job is to wire each relevant strategy to existing:
- source/intake and provenance;
- AssetResolver/DynamicUniverse and canonical identities;
- direct pool/book state;
- amount-specific quote providers;
- FlashCapitalGraph/R02 reader/R03 builder when financing is needed;
- PR118 exact/nonlinear sizing and full cost ledger;
- existing unsigned builder and ExactSimulationFinalizer;
- AGG-05 conflict/resource admission and SX-12 portfolio selection;
- current sender-free shadow/paper consumer and deterministic replay.

Launch independent source-research and adapter tasks in isolated worktrees when they do not share canonical owners. Freeze shared contracts and serialize edits to P0 quote schema, AssetResolver, DynamicUniverse, graph, FlashCapitalGraph, PR118, AGG-05, capability manifests and status dashboards. Keep all source versions, URLs, commit/blob hashes, licenses, quotas, pricing, timestamps, exact schemas and parser fixtures in the offline knowledge base. Verify live service entitlement; do not assume a public/free endpoint remains free.

Priority:
1. DS-00 current inventory, source pins, licenses and quota audit.
2. DS-01/02 raw chain intake + exact canonical identity.
3. DS-03 direct pool/book state and exact venue math.
4. DS-04 quote/build providers: P0-2, frozen R13-K, Titan and additional independent providers.
5. DS-05/06 CEX/perps + oracle/reference signals.
6. DS-07 flash-capital, liquidation and redemption readers.
7. DS-08/09 cross-chain flows, launch/migration and event radar.
8. DS-10 historical indexers/analytics and replay.
9. DS-11 per-strategy end-to-end coverage matrix and actual supported-runtime reachability.

Do not count an indexer row as an exact market, aggregator outputs as independent liquidity, bridge movement as atomic capital, TVL as flash capacity, an SDK method as deployed compatibility, or a test fixture as live evidence. Generic Balancer pools are withdrawals-only after BIP-928 unless an explicit V3 partner pool exception is verified. DefiLlama free yield pools/chart endpoints were shut down on 2026-11-13; GeckoTerminal higher-rate on-chain API now requires Pro. Sui mainnet JSON-RPC is disabled; use gRPC/GraphQL/checkpoints.

Create small task-specific PRs with source pins, owner reuse matrix, tests, replay and truthful blockers. A research adapter may merge with execution_permission=NONE. No account creation, token account creation, signer loading, signing, sending, borrowing, spending, deployments or production promotion. Keep all unqualified paths disabled.

Definition of done is a traceable strategy->source->identity->state->quote->capital->builder->simulation->paper/replay map and a truthful matrix of wired/unwired/blocked strategies. Do not claim the strategy pack is completely implemented just because every row has an assignment.