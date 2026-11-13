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



## 10. Additional market-scale / shadow research owners (PR #559–#564)

The project has a substantial shadow market-scale foundation beyond the original GPR modules. Audit these owners before designing another graph, stream journal, scheduler or market database:

- src/strategy/arbitrage_graph.py and src/strategy/multihop_solver.py — bounded universal graph and multi-hop route candidate evaluation; PR #559 added bounded 3/4-hop shadow candidates. This is candidate topology, not an executable transaction.
- src/strategy/market_graph_ingest.py, src/market/observations.py, src/market/streams.py, src/agg02/ — provenance-bearing market observations, stream/gap/replay and raw-journal owners.
- src/market_data_evolution/ — source/episode/retention/replay/graph review contracts; reuse its point-in-time data and evidence lineage.
- src/strategy/exact_cpmm_capacity.py, src/direct_venue/cpmm_math.py, src/providers/raydium_cpmm_native.py — exact CPMM math/state owners; PR #562 adds the existing exact-capacity bridge.
- src/market/native_cpmm_capture.py and src/paper_shadow/native_cpmm_qualification.py — PR #564 read-only native capture and sender-free qualification. Historical live attempt returned transport error and zero native snapshots; do not treat the code path as currently live-qualified.
- src/economics/split_flow.py, src/strategy/conflict_scheduler.py, src/strategy/shadow_workers.py, src/strategy/shadow_portfolio.py, src/research/pr356_allocation.py — existing split allocation, conflict scheduling, replay worker and joint portfolio owners. Read their current limitations before extension.
- src/mechanism_discovery/ — claims, intent, research quality and causal/replay helpers. Statistical correlations and synthetic twins do not prove executable arbitrage.

Reference: docs/web3-market-scale/IMPLEMENTATION_RU.md and docs/web3-market-scale/execution_matrix.json. The archive retains 170 design-input files and 189 acceptance cases. The implementation report explicitly says the entire archive is NOT complete/qualified; consult the current execution matrix and do not equate unit-test count with closure of all 189 cases.

## 11. Multi-provider quote/build and rent planning knowledge

- Existing design contracts: docs/roadmap/universal-source-execution-rnd-2026-10-07/EXECUTION_BUILDER_CONTRACT.md and IMPLEMENTATION_ROADMAP.md. These describe desired QuoteProvider, TransactionBuilder, ProviderCorrelation and UnsignedExecutionPlan behavior. Verify real code implementations and supported runtime reachability before marking them implemented.
- Solana quote owner: src/solana_parallel_radar/probes.py and cli.py; P0-2 owns migration to current Jupiter V2 and 0x comparison. Add Titan/OpenOcean/OKX/Rango only as separate pinned providers after base pair is correct.
- Sui provider/market owners: src/gpr_sui_shadow/, src/multichain/sui.py and exact venue owners; add Aftermath/Cetus/7K/FlowX/OKX/Rango/DeepBook one contract at a time with object/checkpoint provenance.
- Slumlord instruction adapter: src/lending/slumlord.py implements sender-free Borrow/Repay/CheckRepaid preparation and order validation. It is rent-only support, not swap capital.
- RentSponsorPlanner is currently documented in docs/roadmap/universal-source-execution-rnd-2026-10-07/RENT_SPONSOR_PLANNER.md. Do not infer a production planner class exists; implement through R-14 only after inspecting code/callsites and freezing R-03/R-13 unsigned-plan contracts.
- Provider sponsor/payer (0x, Titan) and local persistent rent are separate modes with payer/co-sign/close-authority and refund semantics. Unknown account cost remains UNKNOWN.

## 12. Current PR/CI notes at main audit 86be458a87ed3f499cc32ff56426b2866c90422a

- PR #595 is merged and introduced the whole-project parallel plan, machine-readable 17-workstream status, owner map, GLM operating guide and R08–R12 task assignments.
- PR #593 remains an open, unmerged P0-1 implementation branch based on the older 176f413 main; compare reported 4 commits ahead / 64 behind current main. Its CI Repository verification failed strict pip-audit with 68 findings across nine locked packages; inspect current branch checks and rebase before any merge.
- PR #594 is stale/superseded by #595 plus the R-13/R-14 specialist tasks; do not merge its divergent branch.
- PR #590 is closed unmerged; its refreshed P0 inventory/parallel plan were included by #595.
- Current CI finding from #595 / #593: pip-audit fails on aiohttp, brotli, certifi, setuptools, black, msgpack, filelock, pillow and uv. R-12 owns remediation. Do not weaken audit.
- Mainline status is not a live RPC or full local verifier run. Recheck current PRs, evidence, source pins and tests before every implementation branch.
