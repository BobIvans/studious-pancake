# ONE CORE CLOSURE — MarginFi + Jupiter v1

## Fixed release scope

This PR closes code architecture only for:

`circular_arbitrage + MarginFi + Jupiter + Solana mainnet-beta`

The selected release class is `production-ready-default-off`. The profile keeps
`live_enabled=false`, `unrestricted_live_allowed=false` and
automatic scale-up disabled. A successful code-closure verifier is not a release
or production promotion.

## Accepted owners consumed

| Concern | Existing owner reused by core-v1 |
| --- | --- |
| installed runtime dispatch | `src.runtime.runtime_entrypoint` |
| durable lifecycle / attempt / reservation / outbox | `UnifiedLifecycleAuthority` |
| capital | `DurableCapitalCoordinator` |
| MarginFi flashloan construction | `MarginfiFlashLoanProvider` |
| atomic MarginFi/Jupiter plan | `AtomicMarginfiJupiterPlanner` |
| instruction firewall | existing planner/firewall authority |
| canonical v0 compile + exact simulation | `ExactSimulationFinalizer` |
| raw simulation reconciliation | `AtomicPlannerSimulationReconciliationVertical` |
| exact attempt | `ExactPaperAttemptOrchestrator` |
| durable paper completion/replay | `DurableCompletedExactAttemptRuntime` |
| independent paper terminal verification | `VerifiedTerminalInstalledPaperService` |
| finalized economic classification | MPR-2610 `FinalizedEconomicLedger` |
| final release promotion | MPR-2612; unchanged |
| guarded post-release operations | MPR-2613; unchanged |
| continuous conformance | MPR-2614; unchanged |
| HA/DR | MPR-2616; not required by the single-host core profile |
| credential/trust rotation | MPR-2618; unchanged |

No second runtime authority, lifecycle database, capital authority, signer,
canary authority, finalized PnL database or release gate is added.

## Physical installed path

The installed paper command now reaches:

`runtime_entrypoint._run_paper`
→ `build_core_v1_composition`
→ one `UnifiedLifecycleAuthority`
→ one `DurableCapitalCoordinator`
→ `CoreV1MaterializedBatchSource`
→ `ExactAttemptRuntimeItem`
→ `ExactPaperAttemptOrchestrator`
→ `AtomicMarginfiJupiterPlanner`
→ `ExactSimulationFinalizer`
→ `AtomicPlannerSimulationReconciliationVertical`
→ `DurableCompletedExactAttemptRuntime`
→ `VerifiedTerminalInstalledPaperService`.

When real deployment/provider evidence is absent the same composition is built,
but its batch source returns `CORE_V1_BLOCKED_EXTERNAL` before RPC simulation or
financial attempt work. The old blank A3 constructor is no longer the installed
paper path.

A healthy admitted source with zero materialized opportunities returns an empty,
ready exact-attempt batch; the existing A2 runtime maps that to `NO_TRADE`.

## Typed materialization boundary

`CoreV1AttemptMaterializer` is the only new provider/discovery-to-financial-attempt
bridge. It outputs `ExactAttemptRuntimeItem`, binds profile/release/policy,
provider evidence, rooted slot, wallet/genesis, capital candidate, candidate
factory, attempt generation and deterministic idempotency identities.

`VerifiedProviderWorkItem` is not accepted as an exact financial attempt and is
not imported by this materializer.

The current branch provides the canonical typed seam. Materializing real drafts
from deployed MarginFi/Jupiter/rooted discovery remains external qualification
and adapter work; missing evidence is not converted into a synthetic opportunity.

## Finalized economics

`CoreV1FinalizedSettlementProducer` hashes raw immutable finalized input before
decoding, requires an identified decoder, derives MarginFi repayment and economics
completeness from decoded fields, and feeds the existing MPR-2610
`classify_finalized_economics()` consumer.

It does not accept caller `economics_complete` or `marginfi_repayment_proven`
booleans. Non-finalized or incomplete evidence returns an MPR-2610 unknown outcome
and commands capital quarantine. Persistence remains an adapter to the accepted
durable owner; this PR intentionally does not create another economic database.

## Profile-scoped debt truth

The historical `evaluate_production_debt()` remains unchanged and globally
conservative.

`evaluate_core_v1_profile_debt()` projects that report onto the immutable
`config/release_profiles/core-marginfi-jupiter-v1.json` scope.

For the RPC-only core profile it does not treat these as mandatory release debt:

- Kamino / Save / direct venues / liquidation / LST / stable-peg expansions;
- OKX / OpenOcean / Odos optional discovery;
- Jito-specific submission evidence;
- Helius webhook evidence when Helius is not a required producer;
- global unrestricted live availability;
- signer/canary evidence required only for later live/canary classes.

Required MarginFi, Jupiter, Solana RPC/rooted state, real shadow, provider drift,
finalized economics and installed release provenance remain explicit external or
review blockers.

The profile report can say `core_v1_code_complete=true`; it cannot set
`production_ready`, `release_claim_allowed`, `live_enabled` or automatic scale-up
true. Those remain downstream governed decisions.

## Scope explicitly not added

No new Kamino/Save integration, direct Orca/Raydium/Meteora, orderbook,
liquidation, LST, stable-peg/CLMM-DLMM, cross-chain, ML or UI feature is added.

## Verification

Dedicated workflow: `.github/workflows/core-v1-closure.yml`.

It uses Python 3.13 and the repository hash-locked dev dependency environment,
compiles/formats the closure surfaces, runs the focused core-v1 regressions plus
MPR-2602 durable completion, MPR-2610 finalized ledger and MPR-2613 guarded
operations compatibility, then runs `scripts/verify_core_v1_closure.py --json`.

Normal repository CI and Release authority remain authoritative for merge
readiness.

## Remaining work after code closure

The intended next steps are qualification campaigns, not another core feature PR:

1. materialize current deployed MarginFi/Jupiter/rooted provider evidence;
2. qualify an installed exact release generation and provider drift evidence;
3. run non-synthetic sender-free shadow soak for the exact release;
4. materialize finalized economics and security/deployment evidence required by
   the selected policy;
5. rerun MPR-2611 for the exact core-v1 release bundle;
6. perform the MPR-2612 durable release ceremony.

No real key is loaded, no transaction is signed/submitted, no funds move and no
live/canary activation is performed by this PR.
