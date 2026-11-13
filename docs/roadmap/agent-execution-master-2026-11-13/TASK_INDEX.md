# Whole-project task index — parallel workstream assignments

This is the orchestration index, not a replacement for protocol-specific technical dossiers. The lead launches independent workstreams concurrently; each worker owns one narrow task/PR/worktree. Shared-owner edits are serialized behind interface freeze.

## Completed / do not repeat
| Work | Evidence | Instruction |
|---|---|---|
| R-01 reconciliation | #584 merged | COMPLETE; do not rerun or remerge legacy branches |
| QPR-01 authority/fixes | reconciled mainline | verify owners; no duplicate implementation |
| R-02 prerequisite observations | #585 merged | BLOCKED; zero qualified capital edges; preserve negative evidence |
| R-02 offline SDK pack | #586 merged | use local pins; do not re-vendor |
| Solana P0 offline master | #588 merged | three market-data tasks already written |
| Raydium/Meteora references | #589 merged | verify local blobs; Orca license blocker remains |
| Whole-project agent handoff | #591/#592 merged | current orchestration base; use this parallelized successor |

## Track A — Solana market-data (parallel after shared identity/evidence contract)
| ID | Assignment |
|---|---|
| P0-1 | docs/roadmap/p0-offline-execution-master-2026-11-13/tasks/P0-1_SOLANA_INTAKE_DYNAMIC_UNIVERSE.md |
| P0-2 | docs/roadmap/p0-offline-execution-master-2026-11-13/tasks/P0-2_JUPITER_0X_QUOTES.md |
| P0-3 | docs/roadmap/p0-offline-execution-master-2026-11-13/tasks/P0-3_DIRECT_STATE_VERIFICATION.md |
| P1/P2 source expansion | docs/roadmap/p0-offline-execution-master-2026-11-13/tasks/P1_P2_AFTER_P0.md |

## Track B — flash-capital R-02 (four independent read-only readers)
| ID | Assignment |
|---|---|
| R02-CAP-A Jupiter Lend | tasks/R02_CAPITAL_READERS.md |
| R02-CAP-B Kamino | tasks/R02_CAPITAL_READERS.md |
| R02-CAP-C NAVI | tasks/R02_CAPITAL_READERS.md |
| R02-CAP-D Project 0 bank-only | tasks/R02_CAPITAL_READERS.md |

Detailed source baseline: docs/roadmap/r02-capacity-recovery-2026-10-08/ and docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/.

## Track C — R-03 unsigned builders
| ID | Assignment |
|---|---|
| R03-00 common contract | tasks/R03_UNSIGNED_BUILDERS.md |
| R03-A Jupiter | tasks/R03_UNSIGNED_BUILDERS.md |
| R03-B Kamino | tasks/R03_UNSIGNED_BUILDERS.md |
| R03-C NAVI | tasks/R03_UNSIGNED_BUILDERS.md |
| R03-D Project 0 | tasks/R03_UNSIGNED_BUILDERS.md |

R03 contract-only and offline fixtures can run while R02 is blocked. No live-capital-backed promotion until the matching R02 proof passes.

## Track D — route / simulation / paper / providers
| ID | Assignment | Dependency |
|---|---|---|
| R04 | tasks/R04_CAPITAL_AWARE_ROUTE_SELECTOR.md | exact quotes + relevant R02 capacity + R03 builder |
| R05 | tasks/R05_EXACT_ATOMIC_SIMULATION.md | R04 candidate and full current state |
| R06 | tasks/R06_PAPER_QUALIFICATION.md | existing QPR/campaign readiness PASS + R05 |
| R07 | tasks/R07_PROVIDER_EXPANSION.md | one provider per PR; source/deployment/reader/builder/simulation proof |

R07 source research can run throughout; provider activation is individually gated.

## Track E — whole-project additional assignments
| ID | Assignment | Parallel scope |
|---|---|---|
| R08 | tasks/R08_RUNTIME_COMPOSITION_INTEGRATION.md | audit current app composition and missing owner injections; code only after contract/gates |
| R09 | tasks/R09_MULTICHAIN_AND_DATA_FEEDS.md | Sui, TON, EVM, CEX, oracle and reference data |
| R10 | tasks/R10_STRATEGIES_AND_INTELLIGENCE.md | strategy coverage, graph, correlations, ML and replay experiments |
| R11 | tasks/R11_PLATFORM_CI_AND_REPRODUCIBILITY.md | Windows/WSL, CI, packaging, offline verifiers and test reliability |

## Parallel execution policy
Start independent tracks A, B, C-00, E and source research concurrently in isolated worktrees. Workers may begin read-only audits, technical source verification, offline fixtures and contract proposals while dependencies are pending. The lead freezes shared interfaces before multiple workers edit a common owner. E1/R04 and later integration stages may prepare design/tests but cannot claim readiness until their evidence dependencies pass.

## Global evidence states
Use IN_MAIN_VERIFIED, IMPLEMENTED_UNQUALIFIED, IMPLEMENTED_UNBOUND, OPEN_PR_NOT_IN_MAIN, FIXTURE_ONLY, STUB, PLANNED, LIVE_READ_PROVEN, RPC_EXACT, BUILT_OFFLINE_UNQUALIFIED, SIMULATION_PASS, PAPER_QUALIFIED, BLOCKED and RETIRED. Each PASS identifies commit, config/source generation, evidence hashes, slot/checkpoint, tests and replay command.

## Global safety
No private material, account creation, token-account creation, signer loading, sending, borrowing, spending, production promotion or env-flag bypass. No provider is enabled because it appears in the catalog or has an adapter class. No mass merge. 


## Whole-project orchestration references
- Multi-agent launch matrix and collision/dependency rules: docs/roadmap/agent-execution-master-2026-11-13/MULTI_AGENT_EXECUTION_PLAN.md
- Current-main knowledge/owner map: docs/roadmap/agent-execution-master-2026-11-13/PROJECT_KNOWLEDGE_BASE_MAP.md
- Machine-readable initial workstream status: docs/roadmap/agent-execution-master-2026-11-13/PROJECT_STATUS.json (refresh before implementation)
- Full orchestrator prompt: docs/roadmap/agent-execution-master-2026-11-13/PARALLEL_AGENT_LAUNCH_PROMPT.md
- GLM-5.3-Flash operating guide: docs/roadmap/agent-execution-master-2026-11-13/GLM_AGENT_OPERATING_GUIDE.md
