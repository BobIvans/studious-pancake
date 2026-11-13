# Codex task — P0-1: Safe Solana indexed intake → Dynamic Universe

**Priority:** P0  
**Mode:** offline implementation and deterministic replay first; bounded live capture is a separate opt-in qualification command.  
**Canonical sources:** read `docs/integrations/offline/solana-p0/README.md` and all linked source notes before editing.

## Assignment

Finish the safe indexed Solana intake and connect it to the existing Dynamic Universe using canonical identities. The output is a continuously refreshable, deduplicated, evidence-backed research pool universe — not executable market truth.

## Before changing code

- Verify current main SHA, worktree, active PRs and CI.
- Read DIN-00/01/02 reports; GPR/QPR handoffs; Dynamic Universe CODEX_START_HERE and implementation report.
- Inspect `src/solana_parallel_radar/`, `src/qualification_campaign/`, `src/discovery/dynamic_universe/`, `src/assets/resolution/`, `src/research_economic_graph/` and all existing adapters/tests.
- Treat the current DIN-01 evidence as partial: historical capture had three successful HTTP 200 requests, empty DEX Screener result and 11 unique candidate pool IDs from Raydium/Meteora. This was a small diagnostic sample, not current coverage or verified liquidity.
- Reuse canonical source governance, quotas, evidence journal, registry/resolver, graph, verification queue and replay. Do not introduce a parallel data plane.

## Required source lanes

Reconcile current reviewed contracts, not just the old catalog descriptions:
- DEX Screener: pair/token discovery, bounded pagination/search.
- Raydium: API/pool metadata for discovery; on-chain state remains a separate P0-3 step.
- Meteora: DLMM discovery metadata; indexed liquidity is not execution depth.
- Manifest: orderbook/market discovery where exact source contract is reviewed.
- Sanctum: LST registry and representation references; every mint still requires RPC identity proof.
- GeckoTerminal: keep blocked until its currently served docs/schema and access behavior are pinned. Never invent an adapter from an inaccessible or changed endpoint.

Record any source not actually reachable under `BLOCKED` with its exact cause; no placeholder adapters counted as integrated.

## Implementation requirements

1. Every source observation has provider/source generation, observed/available timestamps, request parameters, pagination cursor, response hash, status, row rejection reasons and immutable capture ID.
2. Implement bounded polling cadence, quota admission, timeouts, backoff, 429 handling, response-byte bounds and negative evidence.
3. Handle complete vs partial snapshots. Never tombstone/retire a pool because of one missing/empty/truncated/failed page.
4. Normalize pools with exact chain + program ID + pool address + token mint identities + venue family. Maintain alias/shared-liquidity groups; de-duplicate the same pool across sources without deleting provenance.
5. Verify every mint with on-chain owner, decimals and token standard; decode Token-2022 extensions. No ticker-only, symbol-only or name-only identity.
6. Hand off only identity-verified candidates to existing Dynamic Universe/ResearchEconomicGraph owners. Keep indexed candidates in `DISCOVERY_ONLY`; do not create executable edges, direct liquidity or price estimates from indexed metadata.
7. Add reproducible fixture replay and schema-drift/negative fixtures. Offline replay must make zero sockets/network calls.
8. Define a configurable hot-pair target. 120–160 may remain a research target only if source coverage and physical request budgets support it; do not fabricate rows or force a count.
9. Emit campaign receipts and a source coverage report: accepted/rejected/duplicate/stale rows, identity verification state, snapshot completeness, provider independence/correlation and exact blockers.

## Acceptance

- Offline tests prove normalization, dedup, lifecycle, partial-snapshot safety, identity ambiguity and Token-2022 handling.
- Replaying retained capture produces byte-stable evidence and no network access.
- A bounded live capture can produce real data only when explicitly invoked with approved source settings; every actual request/result is recorded.
- The Dynamic Universe handoff is demonstrated by a deterministic integration test using the existing canonical owner.
- No indexed row is marked executable or promoted directly into the route solver.
- Existing capability/quarantine gates remain unchanged; no signer/sender/trading changes.

## Deliverables

- One review-only code PR targeting current `main`.
- `P0_1_REPORT.md`, machine-readable coverage/status receipt, fixture manifest and exact offline replay command.
- Clear `IN_MAIN_VERIFIED` / `IMPLEMENTED_UNQUALIFIED` / `BLOCKED` classification per source.
- A next-agent handoff limited to the missing P0-2 or P0-3 dependency.

## Stop conditions

Stop a source if its current official schema, auth, rate limit, identity fields or pagination semantics are not pinned. Stop the full handoff if canonical mint/program/decimal proof is not available. Do not claim "real pair pool" from a symbol list or indexed TVL.
