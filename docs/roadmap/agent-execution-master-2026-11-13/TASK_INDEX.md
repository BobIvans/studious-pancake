# Whole-project task index — current residual workstreams (2026-11-14)

This is the orchestration index, not a replacement for technical dossiers. Refresh main, open PRs, CI and `PARALLEL_EXECUTION_STATUS.json` before every dispatch. One worktree/owner/PR per bounded task.

## Completed baselines — do not repeat
| Work | Main PR | Truth |
|---|---:|---|
| R-01 reconciliation | #584 | COMPLETE; no legacy re-merge |
| P0-1 indexed intake → Dynamic Universe | #593 | IN MAIN; live identity/source qualification remains |
| P0-2 Jupiter V2 + 0x quote owner | #604 | IN MAIN; 0x live capture unbound/authorization-gated |
| P0-3 Raydium CLMM + Meteora DLMM offline math | #613 | IN MAIN; live state/quotes remain; Orca license-gated |
| R-02 CAP-A Jupiter Lend | #602 | PARTIAL_DECODED; effective capacity UNKNOWN |
| R-02 CAP-B Kamino | #612 | PARTIAL_DECODED; effective capacity UNKNOWN |
| R-02 CAP-C NAVI | #609 | PARTIAL_DECODED; effective capacity UNKNOWN |
| R-03 unsigned contract/builders | #606 | Jupiter/NAVI offline only; Kamino ABI and P0 path blocked |
| H relation/correlation | #614 | 7 residual families + timestamp-aligned lead/lag; not strategy promotion |
| R11/R12 baseline | #611/#605 | Windows/mypy and strict pip-audit 0 findings |
| parallel dashboard | #615 | canonical status owner; refresh snapshot |

## Track A — P0 residual qualification, not rebuild
- P0-1-R: verify pagination/cadence/gap recovery, partial-vs-complete snapshots, canonical identity and source freshness.
- P0-2-R: governed Jupiter V2/0x same-size live quote capture/replay; needs user authorization, public taker context and configured credential names (never commit secrets).
- P0-3-R: rooted exact pool/tick/bin state and quote parity for Raydium CLMM/Meteora DLMM, Token-2022 and complete dependency closure; Orca only after license review.

## Track B — R-02 CAP-D + shared live evidence
- CAP-A/B/C code is present but no effective flash capacity is qualified. User authorization is required for rooted Solana and governed Sui reads with independent quorum.
- CAP-D: wallet-free Project0 bank discovery; optionally validate an existing account from public authority/account addresses only. Never create Marginfi accounts.
- Shared live gate: QPR/DIN governed read-only sources, physical quotas, independent operator quorum, immutable slot/checkpoint state and replay. Until authorized, keep negative receipts and effective capacity UNKNOWN.
- Do not infer cap from API max, TVL, token vault balance, program existence or admin fee alone.

## Track C — R-03 residual builders
- R03-Kamino: pin generated flash borrow/repay modules and IDL; exact instruction-index remapping and reserve fee/rounding; never guess ABI.
- R03-P0: existing-account-only plan; public address check is optional; no init or signer.
- Jupiter/NAVI builds remain offline unsigned, not routes. `build_status` never substitutes for capacity evidence.

## Track D — gated integration chain
| ID | Scope | Entry gate |
|---|---|---|
| R04 | amount/capital-aware route selector using existing graph/solver/sizer | same-generation exact per-size venue quotes + qualified relevant capital + builder |
| R05 | complete unsigned Solana message/Sui PTB/EVM transaction simulation | R04 candidate + same-state dependencies + borrow/repay/callback/object closure + all costs |
| R06 | durable paper qualification including negatives/no-trade | R05 evidence + QPR readiness + replay/holdout |
| R07 | one provider/venue per focused PR | license/deployment/identity/state/fee/cap/builder/simulation and incremental utility |
| R08 | runtime composition / boot-path audit | canonical contracts only; no second authority |

## Track E — remaining whole-project lanes
- R09: Sui GPR-03 transport/checkpoint remediation, TON radar, one-chain EVM pilot, CEX/oracle/reference feed governance.
- R10: expanded strategy crosswalk + falsifiable research (see `tasks/R10_STRATEGIES_AND_INTELLIGENCE.md` and the master strategy overlay).
- R13: multiprovider quote/build research (Titan/OKX/OpenOcean/Rango; Sui Aftermath/Cetus/7K/FlowX) while preserving P0-2 as sole Jupiter V2/0x owner.
- R14: four-tier rent sponsorship/Slumlord economics tied to unsigned builders; rent sponsorship is not trading-capital or network-fee sponsorship.
- R11: base Windows/mypy fix is in main; triage the remaining ~60 previously documented Windows failures in bounded groups.
- R12: strict pip-audit 0 findings is in main; only repeat on lockfile/advisory change.

## Global evidence vocabulary
`IN_MAIN_VERIFIED`, `IMPLEMENTED_UNQUALIFIED`, `IMPLEMENTED_UNBOUND`, `PARTIAL_DECODED`, `FIXTURE_ONLY`, `BUILT_OFFLINE_UNQUALIFIED`, `LIVE_READ_PROVEN`, `RPC_EXACT`, `SIMULATION_PASS`, `PAPER_QUALIFIED`, `BLOCKED`, `RETIRED`, `RESEARCH_ONLY`, `SIGNAL_ONLY`. A PASS names main SHA, source/config generation, immutable hash, rooted slot/checkpoint/block, exact resource and tests/replay. Unknown is never zero.

## Parallel dispatch
One coordinator and ~4–8 independent workers is a practical starting point, not a hard target. Isolate worktrees. Freeze interfaces before parallel writes. Never let agents collide in AssetResolver, Dynamic Universe/source catalog, QPR/DIN, quote normalizers, FlashCapitalGraph, unsigned-plan, exact simulation or runtime authority.

## Safety
No private material, account/ATA/obligation creation, signer, send, borrowing, spending, deployments, provider activation, production promotion or env-flag bypass. No mass merge.
