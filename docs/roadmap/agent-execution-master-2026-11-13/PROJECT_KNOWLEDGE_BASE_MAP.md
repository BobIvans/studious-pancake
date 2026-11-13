# Project knowledge base map — current-main owner index

Purpose: give coding agents a fast navigation map. It is not a replacement for source inspection. Re-fetch latest main and validate paths/hashes before edits.

## 1. Runtime/product truth

Read first:
- README.md
- config/capabilities.json
- src/resources/runtime_authority.json
- current packaging docs / pyproject.toml
- root AGENTS.md

Current README describes a safe, non-production-ready flashloan arbitrage development baseline:
- flashloan-bot launcher, status/capabilities and disabled/shadow/paper boundaries exist.
- Supported composition is sender-free; live mode is hard-denied.
- Circular arbitrage has a shadow-ready detector; it is not a full planner/simulator/sender path.
- Jupiter router code exists behind gates; live build/execute is not claimed.
- MarginFi/Kamino and liquidation/orderbook features require external evidence and remain blocked/fixture-only where capability manifest says so.
- Legacy transaction builders, sender/router/Jito code and old monolith are quarantined or excluded from the supported package.

Do not use a class or a legacy code path as proof that the installed runtime can call it.

## 2. Governance, source admission and replay

Canonical owners:
- src/qualification_campaign/ — QPR source profiles, identity, rooted RPC, transport and evidence.
- src/provider_governance/ — provider authentication, admission, quota/physical request governance.
- src/market/source_catalog.py, src/resources/market_source_catalog.json, config/qualification/din00-source-status.json — source catalog and statuses; catalog rows are not active connectors.
- src/market/streams.py — recoverable stream journal.
- src/gpr_sui_shadow/ — bounded Sui read-only intake and checkpoint/object evidence.
- src/solana_parallel_radar/ — Solana discovery/quote qualification tools.
- docs/roadmap/din00-admission-2026-10-07/, din01-bounded-solana-2026-10-07/, din02-bounded-sui-2026-10-07/ — bounded source diagnostics and replay.

R-01 verification #584 is complete. R-02 prerequisite capture #585 is negative/blocked. Do not repeat branch reconciliation.

## 3. Identity and universe

Canonical owners:
- src/assets/resolution/ — AssetIdentity, resolver, chain readers and identity evidence.
- src/discovery/dynamic_universe/ — universe lifecycle, ingestors, campaign and promotion gate.
- src/research_economic_graph/ — research graph/registry/queue/transforms/verification.
- src/strategy/relation_generators/ — structural relation generation and bounded cycle topology.
- src/research/correlation_ledger/ — residual and correlation evidence.
- src/strategy/arbitrage_graph.py, src/strategy/multihop_solver.py — universal route topology and bounded multi-hop amount evaluation.

Known historical implementation report:
docs/roadmap/dynamic-universe-master-2026-10-07/IMPLEMENTATION_REPORT.md.
It reports a substantial library-level GPR implementation and TON radar, but also says the new subsystem was not wired into the supported app boot path and current external reads were blocked by the historical proxy. Re-check current status; do not reuse its test totals as current results.

## 4. DEX / venue / quote owners

- src/market/discovery.py — indexed discovery adapters (discovery/reference only).
- src/solana_parallel_radar/probes.py, cli.py — governed quote probe owner; historically Jupiter V1 endpoint is quarantined and P0-2 migrates the canonical owner to V2.
- src/providers/raydium_cpmm_native.py — canonical Raydium CPMM exact-state owner; retain it.
- src/ingest/ and src/execution/senders/ — quarantined legacy code, not supported execution owners.
- docs/integrations/offline/solana-p0/ — Jupiter V2 OpenAPI, 0x request contract, Solana RPC facts, Raydium/Meteora source references and Orca license boundary.

Market-data tasks #588/#589 are already documented and merged. They are not flash-capital qualification.

## 5. Flash-capital and financing owners

- src/economics/flash_capital_graph/graph.py — FlashCapitalEdge, LiveCapitalProvider and existing Project0/Kamino/NAVI/DeepBook/Scallop reader contracts.
- src/lending/jupiter_lend.py and src/lending/agg03_financing_ports.py — Jupiter admin/borrow/payback and financing snapshot/port.
- src/lending/kamino.py, src/lending/kamino_real_conformance.py — Kamino source/conformance and shadow owners.
- src/providers/marginfi/ — Project 0/MarginFi flash builder and conformance.
- src/lending/slumlord.py — rent-only financing helper, not trading-capital provider.
- src/lending/financing.py, financing_planner_adapter.py — financing evidence/port integration.
- src/multichain/sui.py — Sui PTB/flash obligation models.
- src/multichain/evm_financing.py — offline financing semantics for Aave/Morpho/DODO/flash-mint models.
- src/economics/non_monotonic_sizing.py and existing PR118 economics owners — amount search/cost math.

R-02 offline reference bundle #586 is merged at docs/roadmap/r02-capacity-recovery-2026-10-08/. Broad 27-candidate offline provider research was restored by #591 under docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/.

## 6. Planner, simulation, paper and authority

- src/planning/atomic_marginfi_jupiter.py — current atomic planner owner.
- src/planning/instruction_firewall.py — program/instruction restrictions.
- src/execution/exact_simulation.py — exact sender-free Solana simulation/report binding.
- src/paper_shadow/atomic_vertical.py — financing/planner/simulation/reconciliation vertical.
- src/paper_shadow/ — durable paper service, attempt orchestration and lifecycle.
- src/runtime/core_v1_composition.py, core_v1_dependency_resolver.py — one runtime composition/financing dependency authority.
- src/durability/unified_authority_pr02.py, src/economics/durable_reservations.py — lifecycle/capital authority.

Do not create a second signer, sender, lifecycle or capital reservation authority.

## 7. Source catalogs and research scope

- src/resources/market_source_catalog.json currently has 37 catalog source candidates with varied families (DEX discovery, quote routers, lending tools, AMM, RPC, CEX streams, oracle/reference, analytics and infrastructure). All governed sources were recorded disabled in the P0 baseline.
- docs/roadmap/r01-r02-live-capital-readers-2026-10-08/PROVIDER_CATALOG.json contains 27 financing/resource candidates, not 27 independent qualified lenders.
- docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/SOURCE_LEDGER.json, CONTRACT_FACTS.json, protocol dossiers and provider economics explain provider contracts and gaps.
- src/discovery/dynamic_universe/ton_radar.py is read-only TON radar; TON discovery is not proof of atomic flashloan execution.

Preserve broad asset and chain research even when capital coverage is narrower. A settlement hub can fund a route through non-borrowable target assets.

## 8. Master handoffs

| Topic | Canonical docs |
|---|---|
| Whole project | docs/roadmap/agent-execution-master-2026-11-13/ |
| Market P0 | docs/roadmap/p0-offline-execution-master-2026-11-13/ |
| Solana offline DEX/API docs | docs/integrations/offline/solana-p0/ |
| R-02/R-03 focused SDK pack | docs/roadmap/r02-capacity-recovery-2026-10-08/ |
| 27-provider flash-capital dossier | docs/roadmap/r01-r02-live-capital-readers-2026-10-08/ |
| GPR/Dynamic Universe | docs/roadmap/dynamic-universe-master-2026-10-07/ |
| DIN source intake | docs/roadmap/din00-admission-2026-10-07/, din01..., din02... |

## 9. Evidence discipline

An implementation can be in main and offline-tested, implemented but unqualified, fixture-only, source-compatible but not bound to runtime, live-read proven, exact state proven, builder-conformant, simulation-passed, paper-qualified or blocked.

Never collapse those into one "implemented" badge. A README, report, merged docs PR, unit test, SDK source pin, account presence or model-generated report is not a mainnet qualification receipt.
