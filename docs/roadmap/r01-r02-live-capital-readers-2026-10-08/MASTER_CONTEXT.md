# MASTER CONTEXT — R-01/R-02

## Repository state checked against GitHub on 2026-10-08
- Repo: https://github.com/BobIvans/studious-pancake
- main HEAD: 103c13795f1d2ac1fa88cf02bba1e9bb2e2477cf
- #579 RCN-00 -> main (merged 2026-10-08T00:51:55Z): real QPR/GPR reconciliation, not only documentation.
- #580 DIN-00 -> main, shared operator quota and credential admission.
- #581 DIN-02 -> main, bounded Sui diagnostics and replay evidence.
- #582 DIN-01 -> main, bounded Solana discovery and replay evidence.
- #578 (RCN-00 R&D, docs only) remains open; some of its historical statements are outdated.

At this HEAD the folders src/qualification_campaign/, src/solana_parallel_radar/, src/gpr_sui_shadow/ and src/economics/flash_capital_graph/ exist in main, with RECONCILIATION_RECEIPT.json. The receipt records the state **at receipt creation** and its merged=false is historical, not the current GitHub PR status.

## As-of GitHub comparisons, main...branch
- codex/qpr-03-campaign-source-intake: ahead 1, behind 90, diverged; investigate unique commit and content explicitly.
- rnd/gpr-parallel-radar-2026-10-06: ahead 0, behind 53; ancestor of main, do not re-merge.
- rnd/universal-source-execution-slumlord-2026-10-07: ahead 0, behind 71; ancestor of main, do not re-merge.
Counts may change: refetch before acting.

## Existing owners to REUSE
- src/qualification_campaign/{cli,identity,profiles,rpc,sources,transport,evidence}.py — QPR intake, source admission, rooted evidence, generation.
- src/solana_parallel_radar/din_discovery.py and src/gpr_sui_shadow/ — existing bounded source diagnostic readers. **Not** lender-capital readers.
- src/assets/resolution/resolver.py, src/discovery/dynamic_universe/, src/strategy/relation_generators/, src/research_economic_graph/ — identity/discovery/graph.
- src/economics/flash_capital_graph/graph.py — FlashCapitalEdge, LiveCapitalProvider, Project0CapitalProvider, KaminoCapitalProvider, NaviCapitalProvider, DeepBookCapitalProvider, ScallopCapitalProvider and navi_sdk_snapshot.
- src/lending/jupiter_lend.py — pinned Jupiter FlashloanAdmin decoder and borrow/payback instruction contracts.
- src/lending/agg03_financing_ports.py — JupiterLendFinancingSnapshot and unsigned financing port.
- src/lending/kamino.py, kamino_real_conformance.py — registry/shadow/conformance; not proof of live flashloan capacity.
- src/providers/marginfi/ and src/lending/protocol_registry.py — source-pinned P0/marginfi rules and genesis admission.
- src/execution/exact_simulation.py and src/economics/non_monotonic_sizing.py — do not fork.

## Concrete code gap discovered
FlashCapitalEdge presently allows providers project0, marginfi, kamino, navi, deepbook, scallop. It **does not currently accept jupiter_lend**, although Jupiter's separate financing decoder and port are already implemented. R-02 must add a narrowly reviewed Jupiter capital adapter/mapping; do NOT bypass the allowlist or mint/program evidence gates. Existing capital provider constructors accept an injected read-only callable returning (payload, Evidence), not an initialized live SDK session.

## Verification boundaries
Real source discovery (DIN) does not equal real flash-capital state. SDK metadata is not enough to admit borrowing. A snapshot must be attested to a specific genesis, program/package, resource, on-chain slot/checkpoint and independently reviewed token/coin identity. Flash fee 0 in docs ≠ on-chain state 0; reserve liquidity ≠ free flash borrow capacity unless every applicable limit is checked.

## Repo policy and user objective
- Preserve broad Dynamic Universe (Solana, Sui, TON, EVM, wrappers and LSTs). Do not scope research universe to the selected lender assets.
- Low-upfront-capital preference: do not create P0/marginfi accounts merely to enable R-02. Existing account permitted READ-ONLY after review.
- Do not use Slumlord SOL-rent borrowing as a substitute for a persistent P0 account. A separate approved repayment and closure proof would be needed.
- Strict: sign_enabled=false, send_enabled=false, no wallet secrets, no withdrawals, no money spent and no automated source changes.
- No claim of live chain observation, profit, 24h qualification or production readiness from this R&D alone.
