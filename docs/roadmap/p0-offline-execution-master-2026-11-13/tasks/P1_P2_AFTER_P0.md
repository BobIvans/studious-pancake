# Codex task backlog — P1 and P2 after P0 exit

These tasks are deliberately **not authorized to start until P0-1, P0-2 and P0-3 exit gates are reviewed**. P0 blockers must remain explicit; P1 does not relabel blocked P0 providers as complete.

## P1 — Expand the verified data universe and shadow intelligence

### P1-1 — Sui indexed intake and Dynamic Universe handoff
- Reconcile current Sui GraphQL/gRPC/Core contracts, checkpoint and object-version semantics.
- Complete bounded discovery for DeepBook V3, Cetus, Aftermath and Scallop only for their specific data roles.
- Distinguish swap market/pool state, orderbook depth, lending rates/capital and oracle/reference data.
- Resolve complete Move coin types, package IDs, shared object IDs, version/digest and checkpoint provenance.
- No Sui executable edge until exact object/package/venue verification and sender-free replay passes.

### P1-2 — Expand Solana discovery coverage
- Add/qualify any missing source such as GeckoTerminal only after a fresh official schema/API snapshot, quotas and access review.
- Add venue source overlap/correlation groups and canonical pool alias resolution.
- Improve event-driven updates/stream recovery while preserving bounded polling and full-snapshot retirement.
- Expand the supported venue universe only where identity and exact state paths exist.

### P1-3 — Reference/oracle and CEX lead-lag feeds
- Add Pyth Hermes or other approved oracle reference prices with pinned current API and authentication.
- Add public CEX WebSocket order-book/trade feeds with sequence numbers, snapshots, checksums, reconnect and gap recovery.
- Keep oracle prices and CEX liquidity in `REFERENCE_ONLY` / `SIGNAL_ONLY` classes; they cannot be substituted for an atomic on-chain quote or flash-loan liquidity.
- Add latency, source independence and stale-data monitoring.

### P1-4 — Research Economic Graph and Correlation Ledger
- Reuse canonical relation and correlation owners. Generate direct-market, venue-fragmentation, NAV/LST and bounded-cycle candidates only from verified identities.
- Persist residual observations, source generation, venue overlap and slot/checkpoint data for deterministic replay.
- Avoid N² polling and correlated-provider double counting.
- Produce evidence-backed rankings only; no automatic production promotion.

### P1 exit
A source counts only with pinned docs/schema, an adapter, positive and negative fixtures, bounded live receipts, replay, source independence/correlation policy and an exact statement of what its data can prove. P1 does not turn CEX/oracle signals into executable edges.

## P2 — Broader research and execution-readiness engineering

### P2-1 — Additional protocol/venue families
- Expand Sui routers and DEX families (for example 7K, FlowX, Bluefin or other currently supported providers) only after official contracts and package pins.
- Evaluate additional lending/capital sources separately from swap routers.
- Consider EVM venue families only with chain-specific exact pool math, deployment/version proof and atomicity/callback semantics.
- Do not assume a cross-chain path can settle atomically within a local flashloan.

### P2-2 — ML/strategy ranking and learning
- Use only replayable, provenance-rich outcomes and residual features.
- Separate signal generation, execution feasibility and economic after-cost ranking.
- Enforce dataset versioning, leakage controls, time splits, provider/venue correlation groups and explainable predictions.
- Keep learned scores advisory until compared against deterministic baselines and paper results.

### P2-3 — Operational hardening and gated execution research
- Stress-test RPC/provider failures, rate limits, schema drift, stale states and queue backpressure.
- Model slot consistency, transaction compute/size constraints, fees, rent/ATA setup and all financing costs in sender-free simulation.
- Any signing/sending/live capital capability remains a separate security review and explicit human authorization; this backlog grants none.

## Start instruction after P0

Read `docs/roadmap/p0-offline-execution-master-2026-11-13/CODEX_START_HERE.md`, verify P0 exit evidence and current branch state, then select exactly one P1 task. Do not start the entire backlog in one run.
