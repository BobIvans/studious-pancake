# PR-033 — real snapshots, universe and first detector boundary

## Purpose

PR-033 introduces the first shadow-safe detector boundary that can create reproducible opportunity candidates from already-fetched market snapshots. It is not an execution PR.

## What changed

- `src.market.snapshots` defines immutable `MarketQuoteSnapshot`, `SnapshotSet`, `MarketSnapshotSource`, and `RecordedSnapshotSource`.
- `src.strategy.detectors` defines `DetectorPair` and `CircularArbitrageDetector`.
- `CircularArbitrageStrategy` can read a `StrategyContext.market_state` snapshot source and emit detector-only `Opportunity` objects.
- The application composition root accepts `market_state`, `protocol_state`, and `capital_precheck` service hooks for later PR-030/031/032/038 wiring.
- `CapitalAwareShadowOpportunityHandler` applies a conservative config-only edge precheck before recording a shadow result.
- `config/capabilities.json` promotes only `circular_arbitrage` to `shadow-ready`; LST, Pump, Kamino, orderbook, MarginFi, paper and live remain disabled or quarantined.

## Invariants

1. A detector receives snapshots; it never calls RPC, quote APIs, builders, compilers, signers, Jito, or senders.
2. Amounts are integer token atoms. Projection uses integer floor math.
3. A candidate requires both route legs to be fresh and within configured slot skew.
4. A candidate is an `Opportunity`, not a transaction plan.
5. Live mode remains hard-denied.
6. Weak edge is a normal `NO_TRADE` result, not an exception.
7. The current config-only capital check is deliberately not a replacement for PR-032's full capital/reservation engine.

## Non-goals

- No MarginFi borrow/repay planning.
- No Jupiter `/build` integration.
- No unified four-provider transport.
- No transaction compilation, exact simulation, reconciliation, sender, Jito, or live enablement.
- No LST oracle/redemption model.

## Review notes for parallel PRs

This branch is based on current `main` after the PR-027 and PR-029 merges. It intentionally avoids importing open PR-028, PR-031 or PR-032 branch code so it can be reviewed independently. After those PRs merge, the intended integration points are:

- PR-030/031 provider plane populates `MarketSnapshotSource`;
- PR-032 replaces or wraps `ConfiguredCapitalPrecheck`;
- PR-034+ consumes accepted `Opportunity` objects in the atomic planner;
- PR-038 makes the shadow runner durable.

Until then, this PR remains a detector-only shadow slice.
