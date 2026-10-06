# MASTER CONTEXT — GPR Parallel Radar / Research Economic Graph

Date: 2026-10-06  
Repository: `BobIvans/studious-pancake`  
Planning base: QPR-03 head `7132f7341661368917bcc3cf1618a93de96327f8` / PR #570.

## Why this package exists

QPR-03 was intentionally only the **campaign-start slice**. It implemented the generic Solana `SourceDossier` / `ProviderProfile` / `DiscoveryAdapter` / `SourceIntakePlane` boundary and proved it with DEX Screener, GeckoTerminal and Raydium. It did not implement the broad source inventory, research economic graph, dynamic watch universe, multi-chain research plane or live execution.

This package defines the next evidence-driven wave and must reuse QPR-01/02/03 owners.

## Current compatibility constraints

- `SourceDossier.catalog_entry()` and QPR-03 `Candidate` are currently Solana-specific.
- Indexed/router observations remain research/discovery evidence, not executable truth.
- Existing `ShadowMarketGraphIngest` must continue to require exact `MarketObservationV2`.
- Existing `UniversalArbitrageGraph`, bounded multihop solver, PR118 amount sizing, split-flow and `RouteGraph` remain canonical owners.
- Signer/sender/submission/live capital remain unreachable.

## Review prerequisites

At package creation, PR #569/#570 still had unresolved findings that Codex must re-check:
- configurable baseline/main ref instead of unconditional `origin/main`;
- interprocess-safe evidence cursor allocation;
- persist discovery attempts in campaign evidence;
- readiness PASS must require accepted schema/quality, not merely HTTP 200;
- redact adapter-derived context before persistence;
- replay must fail closed when evidence DB is missing.

Do not assume a finding is still present; inspect current heads first.

## Architecture decision

Build one **chain-neutral ResearchEconomicGraph**.

- Solana: primary exact qualification domain.
- Sui: parallel read-only/shadow research domain from the beginning; exact promotion only after governed gRPC/GraphQL state verification exists.
- TON/ST​ON: high-throughput research laboratory in this wave, not a second live flash-execution domain.

## Parallel quote-preview lanes

Do build parallel **read-only quote/execution-preview** lanes; do not build two live executors.

Solana:
- Lane A: Jupiter final/reference quote.
- Lane B: 0x higher-throughput quote validator.
- Lane C optional: OpenOcean, correlation-tagged because it can share underlying routing.
- Specialized: Sanctum for LST economic/exit relationships.
- Exact truth: independent RPC profiles + direct state decoder/local integer quote.

Sui:
- Lane A: Aftermath router.
- Lane B: direct venue/state path (Cetus / DeepBook where qualified).
- Exact truth: governed Sui gRPC/GraphQL provider profiles + object/checkpoint state.
- Do not introduce a new JSON-RPC dependency.

## Scale target

The full ZIP contains 330 symbolic pair relationships:
- 257 Solana;
- 53 Sui;
- 20 TON;
plus 10 route generators.

Every asset identity is a placeholder and runtime-disabled. The research graph may derive thousands of evidence-backed route comparisons without creating thousands of polling loops.

## Non-negotiable rules

- Never guess a mint/coin-type/jetton address.
- Symbol-only identity never enters exact graph.
- Router/discovery quote never equals executable truth.
- Preserve provider/operator/correlation identity.
- Timeout/429/empty/schema-drift are evidence.
- Replay/campaign identity remain mandatory.
- No Sui JSON-RPC dependency for new work.
- No signing/sending/submission/live trading in this package.
