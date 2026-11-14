# SX-00 — Strategy assignment reconciliation report (2026-11-14)

Lane: **coordinator, read-only audit + additive docs**. No `src/` changes.
Baseline: current main `5769b074ea2963ae893aecd9aa749dafe6ee91a7` (2026-11-14,
includes #637 strategy-expansion pack and #638 R13-K kernel freeze), clean worktree,
CI green on main (`CI`/linter verify, AGG-14, qualification campaign, release
authority — all success at `5769b074`).

Machine-readable companion: `SX00_RECONCILIATION.json`
(schema `studious-pancake.sx00-reconciliation.v1`).

This report reconciles the Strategy Expansion pack (`STRATEGY_EXPANSION_ASSIGNMENTS_RU.md`,
SX-01…SX-16) against **all** prior strategy assignment systems. It does not copy, rewrite or
re-own the `MASTER FLASHLOAN MARKET INTEGRATION` assignment or P0 market-intake work; it only
records coordination boundaries and consumes their published evidence contracts.

## 1. Baseline and active peer lanes (verified 2026-11-14)

- `main == origin/main == 5769b074`; local worktree clean; PR #565 merged last on main.
- 31 open PRs, all older roadmap/platform branches (PR-127…#578, Jul–Oct 2026). None touches
  `docs/strategy-expansion/**`, `src/strategy/**`, `src/economics/**` strategy contracts or the
  SX lanes below. They are not blockers for additive SX PRs and must not be merged here.
- Active peer worktrees/branches owned by the MASTER market-integration assignment today:
  `agent/r03b-kamino-builder` (src/lending/unsigned_builders), `agent/r14-kamino-wiring`,
  `agent/r13-quote-build-audit`, `agent/evm-sui-dossiers-wave2`, `agent/ton-radar-wave2`,
  `agent/r02-cap-d-project0`, `agent/provider-dossiers-wave1`, `agent/r08-runtime-composition-audit`,
  `agent/clmm-len-verification-receipt`. **SX lanes avoid these paths entirely.**
- Frozen contract to honor (PR #638, `src/execution/quote_build_kernel.py`,
  `QUOTE_BUILD_KERNEL_VERSION="r13.quote-build-kernel.v1"`): per-amount exact re-quote
  (`refuse_amount_extrapolation`), pool-identity dedup (`PoolIdentityDeduplicator` — same pool /
  aggregator lineage / operator group is correlated, never independent liquidity),
  `NormalizedProviderQuote` `None`=UNKNOWN, `BuildHandoff` seam. SX economics models must reuse
  these invariants and must not create another quote plane.
- `PARALLEL_EXECUTION_STATUS.json` records main SHA `c87f5d31` (stale vs `5769b074`); it has **no
  SX lane**. Per repo rules the dashboard is the lead's shared file: this report publishes SX
  status in `SX00_RECONCILIATION.json` and does not edit the dashboard (coordinator-only refresh
  deferred to SX-16 reconciliation).

## 2. Source inventory → verification result

| Source system | Verified content | Verification result |
|---|---|---|
| `04_STRATEGIES_RU.md` S01–S07 | 7 families, WG mapping, owners O01…O28, funding/scaling constraints | Confirmed: adapters declared future work; 5 of their WGs carry narrow implemented slices (PR #562). No per-family implemented/stub field. KEEP as-is. |
| `25_OPPORTUNITY_ATLAS_RU.md` OP-01…OP-28 | 28 mechanism cards, class + flashloan policy + queue P0–P3 | Confirmed: 9 ATOMIC_CONDITIONAL, 5 INVENTORY, 3 MARKET_MAKING, 11 other; queue P0×2 (OP-01/02). "Mechanism types, not working strategies" — no false coverage claims. KEEP. |
| `design-input/data/tasks.json` WG-01…WG-28 | 28 packages, waves A–E, `shadow_only`, dependency graph | Confirmed: 5 `PARTIALLY_IMPLEMENTED_REMAINDER_PLANNED` (WG-02/06/07/10/11, PR #562 slices @ `67d3852c`), 23 `PLANNED_NOT_IMPLEMENTED`. KEEP; SX layers acceptance/economics on top, does not re-implement WGs. |
| `STRATEGY_UNIVERSE_ATLAS.md` groups A–I | 31 concepts, 9 groups, per-group repo owners | Confirmed against code; PR #599 cross-check (R10 replay report §6) found no factual disagreement. KEEP. |
| `STRATEGY_CROSSWALK.json` (23 families, SHA `86be458a`) | statuses in repo vocabulary, owners | Confirmed; only DIRECT-2LEG/VENUE-FRAG/BOUNDED-CYCLE (unqualified) + CLOB-AMM (fixture-gated) are implemented-flavored. EXTEND via SX-16 into refreshed crosswalk; do not fork the schema. |
| `ARCHIVE_RESEARCH_CROSSWALK.md` | V3/V4/V4.1/V5/V6 generations | Confirmed dedup warnings: 34 casefold-collision excess (V3), 3 overlaps removed (V6), never sum per-generation counts. DUPLICATE/RETIRED list in §6. |
| `R10_STRATEGIES_AND_INTELLIGENCE.md` lanes A–I | 9 parallel research lanes + owner map + experiment protocol | Confirmed: lanes already assigned; SX packages EXTEND specific lanes (§4), never re-assign them. |
| `R10_STRATEGY_INVENTORY_2026-11-14.md` + `R10_STRATEGY_REPLAY_EXPERIMENTS_2026-11-14.md` | machine inventory + offline replay receipts | Confirmed: 602-test baseline; shortlist≠profit proven (`NON_POSITIVE_NET`); typed blocker classes; ranked promotion shortlist items 1–3 owned by R04/R06, R02-CAP, R10 follow-up — **not SX**. |

## 3. Code-level truth (read at `5769b074`)

- Runtime registry: 6 registrations; only `circular_arbitrage` has a real (two-leg, shadow-only)
  detector; `lst_depeg`/`lst_unstake` STUB shells; `kamino_liquidation`/`orderbook_amm_arbitrage`
  FIXTURE_ONLY quarantined; `pump_fun_migration` PLANNED boundary-only. Live hard-denied
  (`capabilities.json` `runtime_modes.live.available=false`).
- Implemented+tested research/exec core (paper/shadow only): relation generators (12 kinds),
  heat scheduler, correlation ledger (12 features, 7 residual families, 9 typed exclusions),
  `arbitrage_graph` (3/4-hop shadow cycles), `multihop_solver` (2–5 hop shortlist),
  PR118 `non_monotonic_sizing`, `split_flow`+`cpmm_split_replay`, AGG-05 `conflict_scheduler`,
  CPMM exact capacity, Raydium CLMM/Meteora DLMM native decoders + exact math (not yet bound as
  graph evaluator), decision dataset/ranker (advisory), strategy_evolution EVO-01…09 kernels,
  INST-01 procurement vertical (PR-359).
- Shell/absent: flash_capital_graph (0 qualified edges, CAP-R02 BLOCKED), LLAMMA (admission
  shells + deterministic stubs only), flash-mint (`FlashMintAdapter` bounded offline + stub
  primitives), prediction/complete-sets (enum label only), OEV (absent), LP lifecycle (absent),
  async settlement state machine (absent as executable model).

## 4. R10-A…I disposition (evidence-based)

| Lane | Scope | Disposition | Evidence / rationale | SX linkage |
|---|---|---|---|---|
| R10-A | issuer/PSM/flash-mint caller eligibility, fees, caps, buffers | **EXTEND** | Owners exist (strategy_evolution/primary_market.py, rights_lifecycle.py, flash_capital_graph) but flash-mint has no eligibility/fee/repay contract; no live financing evidence (CAP-R02) | SX-02 (flash-mint + lender-selection economics) |
| R10-B | LST/LRT/BTC exchange rate, queue/instant exit, slashing | **KEEP** | Residual/anchor owners verified; detector bodies are R10 follow-up (shortlist item 3), user of existing owners only | none (SX must not duplicate) |
| R10-C | Curve LLAMMA bands, per-market state, oracle/health | **EXTEND** | Only admission shells (`agg12.qualify_llamma`) + deterministic stubs (`mega8_08/pr287`); no band math, no official-source dossier | SX-03 (LLAMMA dossier + band math, research/shadow) |
| R10-D | Pendle PT/YT/SY maturity, ERC-4626/7540/7575 rights | **KEEP** | rights_lifecycle/incentive_epoch research kernels in main; maturity classified non-atomic already | adjacent-only: SX-07 must not re-own Pendle |
| R10-E | CLOB/AMM exact VWAP, IOC, book freshness, ticks/bins | **KEEP** | Orderbook owners implemented but fixture-gated; detector wiring awaits verified subscriptions (R07 lane) | SX-06 measures/extends economics without wiring detectors |
| R10-F | spot-perp/options/prediction instruments | **EXTEND** | Only an `StrategyFamily.COMPLETE_SET` enum label exists; no complete-set vector model | SX-07 (complete-set vector claims; non-atomic) |
| R10-G | intents/OEV/MEV/JIT/rebates | **EXTEND** | OEV absent; JIT/LVR absent; backrun economics = offline EVO-07 contract only | SX-04 (OEV), SX-05 (JIT/LVR), SX-10 (backrun ordering) |
| R10-H | bridge/rollup/TON/Cosmos finality/queue/inventory | **EXTEND** | TON radar discovery-only; transformations V2.2 non-atomic; no settlement-state machine model | SX-11 (async/settlement state machine; SIGNAL_ONLY/ASYNC) |
| R10-I | relations/ML: REL-01..14, V3/V4 detectors, holdout | **EXTEND** | decision stack implemented (purged split, embargo, calibration) but no per-family null/control/multiple-testing framework | SX-13 (causal evaluation framework, no second store) |

## 5. SX package execution plan (post-SX-00)

Shared-file rule honored: single integrator (coordinator) owns `strategies.py`,
`capabilities.json` (both), graph/scheduler owners, `format_targets.txt`, verify scripts,
`PARALLEL_EXECUTION_STATUS.json`, `STRATEGY_CROSSWALK.json`. SX lanes add **new additive modules
only** and never edit those files. No second graph/solver/registry/ledger/journal/capital-graph/
scheduler/release authority anywhere.

| Package | Wave | New files (additive only) | Depends on | Notes |
|---|---|---|---|---|
| SX-01 typed strategy contract | 1 | `src/strategy/strategy_contract.py`, tests | — | schema only; no runtime registry; SX-16 integrates into crosswalk |
| SX-02 flash-mint/lender economics | 1 | `src/economics/flash_capital_graph/flash_mint_options.py`, tests | — | reuses FlashCapitalEdge vocabulary + `FlashMintAdapter` semantics; offline |
| SX-03 LLAMMA | 1 | `src/strategy_evolution/llamma_band_math.py`, dossier doc, tests | official source pin | typed BLOCKED if primary-source formulas cannot be pinned |
| SX-04 OEV/keeper | 1 | `src/strategy_evolution/oev_auction_replay.py`, dossier doc, tests | official source pin | SIGNAL_ONLY; oracle price never a quote |
| SX-05+06 microstructure | 1 | `src/research/microstructure/` (`lvr.py`, `jit_fill_replay.py`, `maker_queue_ledger.py`), tests | — | research models; no detector wiring; excludes sandwich/frontrun |
| SX-07 complete-set claims | 1 | `src/strategy_evolution/conditional_claims.py`, tests | — | vector conservation; settlement/dispute non-atomic |
| SX-08 lending rates/refinance | 1 | `src/lending_indexer/rate_curves.py`, tests | — | offline curve model; refinance vs carry separation |
| SX-09 LP lifecycle | 1 | `src/research/lp_lifecycle/position_lifecycle.py`, tests | — | reuses CLMM/DLMM math concepts; persistent capital lock |
| SX-10+11 ordering/async | 1 | `src/strategy_evolution/backrun_auction_replay.py`, `src/strategy_evolution/async_settlement.py`, tests | — | permitted backrun only; no Jito enablement; fault injection |
| SX-13 causal eval | 1 | `src/decision/hypothesis_eval.py`, tests | — | null/controls/holdout/multiple-testing on existing owners |
| SX-14 mechanism lab | 1 | `src/research/verifiable_procurement.py`, tests | — | extends INST-01 semantics; no second marketplace |
| SX-12 portfolio scheduler | 2 | `src/strategy/portfolio_optimizer.py` (additive consumer of AGG-05), tests | SX-01, AGG-05 | stacked on SX-01 branch; 1/2/4/8 worker determinism |
| SX-15 observability matrix | 2 | `docs/strategy-expansion/2026-11-14/SX15_...md`+json, tests | all wave-1 receipts | per-family evidence dashboard; no whole-universe claims |
| SX-16 final reconciliation | 2 (coordinator-only) | refreshed crosswalk delta proposal + collision check report | all | no crosswalk overwrite; proposal PR for lead review |

## 6. Duplicates / retired assignments to avoid

1. Do **not** create: second graph/solver (`arbitrage_graph`/`multihop_solver` own topology),
   second sizing owner (PR118), second split-flow, second capital graph, second correlation
   ledger/feature store, second conflict scheduler, second quote plane (R13-K kernel frozen),
   second runtime strategy registry, second paper/shadow composition root.
2. Do **not** re-execute R10 ranked shortlist items 1–3 (CPMM cycle→paper binding = R04/R06;
   MarginFi edge qualification = R02-CAP; LST residual-fed detectors = R10 follow-up) — SX lanes
   neither own nor duplicate them.
3. Do **not** re-implement WG-02/06/07/10/11 partial slices (PR #562) or any of WG-01…28 as SX
   work; SX adds acceptance/economics layers only.
4. Archive duplicates: V3 34-symbol collision excess, V6 3-overlap removals; never sum archive
   generation metrics into coverage claims; direct-venue-audit routes are hypotheses that never
   outrank current main/official docs.
5. Excluded permanently: Robinhood Stock Tokens / tokenized equities (user policy);
   sandwich/frontrun/user-targeting/unauthorized private flow; cross-chain/CEX/TON-async/
   maturity carry as atomic flashloan legs; TVL-as-capacity; RWA equity family.

## 7. Per-family acceptance delta (missing fields → SX package)

For each acceptance-matrix family (`STRATEGY_ACCEPTANCE_MATRIX.json`), the missing proof classes
were re-derived from code truth: every family still lacks at least one of
{exact-state binding, per-amount exact quote beyond CPMM, capacity proof (CAP-R02),
build conformance (R-03), exact simulation (SIM-R05), paper pass (PAPER-R06)} — so **no family
may claim coverage above its evidenced tier**; full per-family mapping lives in the JSON
(`families[].missing_acceptance`, `families[].next`, `families[].dependency`). Headline:

- ARB-CORE/ARB-SPLIT: exact evaluator binding (CLMM/DLMM) + ROUTE-R04 + PAPER-R06 → owned by
  R04/R06 lanes; SX-12 consumes, does not rebuild.
- TRANS-ISSUER: flash-mint contract missing → SX-02.
- CREDIT-LLAMMA: everything missing (no band math, no dossier) → SX-03.
- MICRO-OEV: everything missing → SX-04.
- MICRO-JIT/MICRO-MAKER: measurement models missing → SX-05/SX-06.
- CLAIM-COMPLETE-SET: everything missing (enum only) → SX-07.
- CREDIT-RATE: rate-curve/refinance model missing → SX-08.
- LP-LIFECYCLE: everything missing → SX-09.
- MEV-BACKRUN: auction replay missing → SX-10.
- BASIS-ASYNC: settlement-state machine missing → SX-11.
- PORT-CAPITAL: portfolio allocation missing → SX-12 (wave 2).
- INTEL-LEARN: null/control/multiple-testing framework missing → SX-13.
- DATA-COMPUTE/MECHANISM-LAB: one verifiable task + fixed-workload comparison missing → SX-14.

## 8. SX-00 acceptance self-check

- Every family: one canonical owner ✓ (JSON `families[].owner`), one next task ✓
  (`families[].next`), one dependency ✓ (`families[].dependency`), one status ✓
  (`families[].status`), no duplicate solver/registry ✓ (§6 do-not-create list; lanes additive).
- R10-A…I / WG / OP dispositions: §4 + JSON `r10_lanes[].disposition`, `wg_status`, `op_status`.
- No overlap with active MASTER lanes: §1 avoid-list honored by all wave-1 file paths.
- No merge performed; next gates are wave-1 PRs (evidence receipts + typed blockers each).

## 9. Typed blockers carried forward (unchanged, classed)

- User-gated (cannot be satisfied by any agent): `LIVE_AUTHORIZATION_REQUIRED`,
  `OPERATOR_ACCOUNT_INPUT_REQUIRED`, `ZEROX_LIVE_CAPTURE_PREREQ`, `ORCA_LICENSE_REVIEW`,
  `EULER_BSL_BLOCKED`, live capacity reads / `get_program_accounts` enumeration.
- Evidence-gated (offline progress possible): CLMM/DLMM evaluator binding, ROUTE-R04, PAPER-R06,
  SIM-R05 surfaces, detector bodies, market subscriptions, anchor-proof dossiers
  (`redemption_anchor_unproven`, `nav_per_share_unproven`, `lst_exchange_rate_unproven`,
  `instant_exit_unproven`, `underlying_reference_unproven`, `oracle_slot_misaligned`),
  SX-specific: official-source pins for SX-03/SX-04 dossiers.
