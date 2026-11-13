# Task index — executable assignment prompts

Rule: one scoped assignment per coding-agent run/PR. This index is orchestration, not a replacement for protocol-specific docs.

## Completed / do not repeat
| Work | Evidence | Instruction |
|---|---|---|
| R-01 reconciliation | PR #584 merged | PASS; do not rerun or re-merge historical branches |
| QPR-01 authority/fixes | Reconciled current main; verify owners | Do not rebuild; fix only a demonstrated regression |
| R-02 prerequisite observations | PR #585 merged | BLOCKED, zero qualified edges; use exact negative evidence |
| R-02 offline SDK bundle | PR #586 merged | Use checked-in source/layout pins; do not re-vendor |
| Solana market-data offline master | PR #588 merged | Use its P0-1/P0-2/P0-3 prompts |
| Raydium/Meteora offline source snapshots | PR #589 merged | Verify locally; respect Orca license blocker |

## Track A — market-data qualification
| ID | Assignment | Start text |
|---|---|---|
| P0-1 | Bounded indexed Solana intake, exact identities and Dynamic Universe handoff | docs/roadmap/p0-offline-execution-master-2026-11-13/tasks/P0-1_SOLANA_INTAKE_DYNAMIC_UNIVERSE.md |
| P0-2 | Jupiter Swap V2 + 0x comparable quote capture/replay | docs/roadmap/p0-offline-execution-master-2026-11-13/tasks/P0-2_JUPITER_0X_QUOTES.md |
| P0-3 | Raydium CPMM/CLMM + Meteora exact direct-state; Orca license gate | docs/roadmap/p0-offline-execution-master-2026-11-13/tasks/P0-3_DIRECT_STATE_VERIFICATION.md |
| P1/P2 | Sui intake, further source coverage, CEX/oracle/reference streams, correlations and later strategy work | docs/roadmap/p0-offline-execution-master-2026-11-13/tasks/P1_P2_AFTER_P0.md |

P0-1, P0-2 and P0-3 are distinct. Quote aggregators are not independent liquidity sources. Indexed pool lists are discovery only.

## Track B — flash-capital
| ID | Assignment | Dependency |
|---|---|---|
| R02-CAP-A | Jupiter TokenReserve/vault/limits reader | R-01 done; #585 negative receipt; #586 pinned layout |
| R02-CAP-B | Kamino full Reserve/LendingMarket/fee/cap reader | R-01 done; pinned klend-sdk codegen |
| R02-CAP-C | NAVI deployed package/config/pool shared-object reader | R-01 done; Sui governed gRPC/GraphQL only |
| R02-CAP-D | Project 0 bank-only reader; optional existing public account scan | No wallet needed for bank research; never create account |
| R03-00 | Shared unsigned execution-plan / financing obligation contract | May start offline while R-02 is blocked |
| R03-A..D | Jupiter, Kamino, NAVI, conditional P0 unsigned builders/PTB | Source-pinned SDK conformance; no signer/sender |

Detailed owner and acceptance docs:
- docs/roadmap/r02-capacity-recovery-2026-10-08/R02_UNBLOCK_MATRIX.md
- docs/roadmap/r02-capacity-recovery-2026-10-08/R02_ACCEPTANCE.md
- docs/roadmap/r02-capacity-recovery-2026-10-08/R03_SHADOW_BUILDERS.md
- docs/roadmap/r01-r02-live-capital-readers-2026-10-08/R02_ARCHITECTURE.md
- docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/PROVIDER_SELECTION.md

## Track C — route / simulation / qualification
| ID | Assignment | Entry gate |
|---|---|---|
| R04 | Capital-aware universal route selector | Exact quote inputs + relevant R-02 capacity + R-03 unsigned contracts |
| R05 | Full atomic simulation + economic reconciliation | R04 candidates; current chain state; per-provider conformance |
| R06 | 24-hour paper campaign | Existing QPR/campaign readiness PASS; exact simulation/replay; otherwise BLOCKED |
| R07 | Add providers from broad 27-ID catalog | R06/selection owner stable; one provider per PR; source and deployment proof |

See separate assignment texts under tasks/.

## Global evidence states
Use: IN_MAIN_VERIFIED, IMPLEMENTED_UNQUALIFIED, OPEN_PR_NOT_IN_MAIN, FIXTURE_ONLY, LIVE_READ_PROVEN, RPC_EXACT, PAPER_QUALIFIED, BLOCKED, RETIRED. Distinguish built code, source compatibility, real observations, exact capacity, simulation and qualification. Every PASS identifies commit, config generation, raw evidence hash, slot/checkpoint, source version, tests and replay command.

## Global safety
No private material, account creation, token-account creation, signer loading, transaction sending, real borrow, funds spending or production enablement. No provider is enabled just because it is catalogued or has an adapter class. No merge of implementation PR without human review/approval.
