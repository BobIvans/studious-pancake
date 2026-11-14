# R13-K — Quote/build kernel contract freeze + pool-identity dedup

**Lane:** R13-K (additive kernel contract + tests + this note; no owner edits)
**Date:** 2026-11-14
**Branch:** `agent/r13-kernel-freeze`
**Base SHA:** `c87f5d31b151c7f61de198ea286de52aff1f8215` (origin/main at lane start)
**Mandate:** R13_QUOTE_BUILD_RACE_AUDIT_2026-11-14.md (PR #629) typed blockers
`R13_GAP_NO_KERNEL` + `R13_GAP_NO_POOL_DEDUP` and its §7 recommendation:
"gate the R13 implementation wave behind kernel freeze + pool dedup as one
coherent pair".

---

## 1. What is frozen

ONE shared, typed, dependency-light kernel contract:
`src/execution/quote_build_kernel.py` (new module, additive only). It freezes:

| Kernel owner | Role | Mapping |
|---|---|---|
| `NormalizedProviderQuote` | One normalized provider quote: provider id/generation, chain, raw + normalized in/out amounts (exact ints), minimum output (`None` = UNKNOWN, never 0), fee components + compute-unit estimate, route venue list, correlation (operator group + aggregator lineage + underlying pool ids), freshness (provider generation time, received-at, slot/checkpoint ONLY when supplied, expiry), taker mode, raw response hash + request fingerprint. `execution_authority` is a literal-`False` constructor invariant. | UXE-00 `NormalizedQuote`; maps governed `QuotePreview` and routing `CanonicalQuoteV2` (the routing `NormalizedQuote` alias) onto it — neither is imported or duplicated |
| `QuoteRaceRequest` / `QuoteRaceResult` / `RankedQuoteEntry` | Deterministic race: hard comparability identity (chain, representation pair, direction, exact bound amount, taker parity — mismatch refuses with `QuoteComparabilityError`), hard freshness bounds (`max_age_ns` in (0, 45_000_000_000], `max_slot_gap` in [0, 32] — wider bounds refused), ALL providers preserved (winners, losers with typed `QuoteLossReason`, stale quotes never dropped and never winning), failed reads preserved as typed `ProviderReadFailure`, stable race fingerprint. | UXE-00 correlation-aware ranking; maps routing `NonSelectionReason`/`ProviderFailureReason` semantics |
| `PoolIdentityDeduplicator` | Explicit typed rule set closing `R13_GAP_NO_POOL_DEDUP`: quotes sharing ANY underlying pool identity (exact `amm_key`/`pool_address`/Sui `pool_object_id` with canonical `0x`-hex normalization), ANY aggregator lineage member (e.g. OpenOcean-over-Jupiter vs direct Jupiter), or the SAME operator correlation group are CORRELATED observations, never independent liquidity. INDEPENDENT requires positive disjoint-pool evidence on both sides + disjoint lineage + different groups; anything less is `UNKNOWN` (unknown is never independent). Venue-level labels/program ids never establish correlation nor independence. Provides `correlation_verdict`, `shared_pool_ids`, `shared_lineage`, `group_quotes` (union-find clusters) and `independence_set` (best-first greedy) — all deterministically ordered; identical inputs in any order produce identical output. | UXE-00 `ProviderCorrelation`; model for future adapters is the Sui `CheckpointProviderBinding` correlation governance (`SUI_CORRELATED_PROVIDERS_BLOCKED`) |
| `BuildHandoff` + `R03UnsignedPlan` | The explicit seam from a won quote to an R-03 `UnsignedBorrowPlan`-family build: typed REFERENCE to an existing plan object (`UnsignedBorrowPlan` / `UnsignedRepayPlan` / `PtBuildResult` / `FinalizedUnsignedSolanaPlan`, all IMPORTED from `src/lending/unsigned_builders/contract.py` — zero duplication), fail-closed integrity parity (handoff must reference the race winner; plan provider == builder provider; recorded `BuildStatus` == plan's actual status — no fake PASS; chain parity when the plan carries one). No construction logic: the kernel never builds instructions/PTBs. | UXE-00 `TransactionBuilder`/`UnsignedExecutionPlan` seam; R-03 contract enums/types reused by import (`BuildStatus` identity asserted by test) |
| `refuse_amount_extrapolation` (+ `BuildHandoff.require_sizing_amount`) | The no-extrapolation rule as a typed invariant: every sizing point requires a fresh quote at the EXACT amount. Any other amount — including amount-neighborhood perturbations (+/-1 raw unit, ±0.1% rescales) — is refused with `QuoteExtrapolationError` (`R13_KERNEL_QUOTE_EXTRAPOLATION_REFUSED`). | Governing rule from R13 task: "Never scale a quote to a different amount; re-quote every amount used by the nonlinear sizing owner" |

Typed error surface: `KernelContractError` base + `QuoteComparabilityError`,
`QuoteRaceStateError`, `QuoteExtrapolationError`, `BuildHandoffError`, all
carrying `KernelErrorCode` codes. Frozen version constant:
`QUOTE_BUILD_KERNEL_VERSION = "r13.quote-build-kernel.v1"`.

**Package placement:** `src/execution/` is the existing execution-domain
package and already hosts supported, mypy-governed owners
(`src/execution/exact_simulation.py`, per
`docs/roadmap/agent-execution-master-2026-11-13/PROJECT_KNOWLEDGE_BASE_MAP.md`
section 6; only `src/execution/senders/` is quarantined). The kernel is the
seam BETWEEN the quote planes and the R-03 builder plane and ends where exact
simulation begins, so the execution package is the correct existing home.
Rejected: `src/routing/` (one specific plane's owner) and
`src/lending/unsigned_builders/` (the frozen R-03 contract package). The
module is consumed directly as `src.execution.quote_build_kernel` with NO
`__init__.py` change — the same direct-import pattern as
`src.lending.unsigned_builders.kamino_builder`.

## 2. Existing owners: untouched

No existing file is edited. Verified read-only during this lane:

- `src/solana_parallel_radar/probes.py`, `funnel.py`, `cli.py` (P0-2 governed quote owner)
- `src/routing/` models/registry/adapters/clients (production discovery plane)
- `src/lending/unsigned_builders/contract.py` (frozen R-03 contract) and `kamino_builder.py`
- `src/gpr_sui_shadow/` (Sui state providers + correlation governance)
- `src/planning/rent_sponsor_planner.py` (sponsor/payer tiers, INACTIVE)
- `src/execution/__init__.py` (kernel is imported as a submodule; no registration)

Changed paths (complete list): `src/execution/quote_build_kernel.py` (new),
`tests/test_r13_kernel_contract.py` (new), this report (new).

## 3. Wiring path: DEFERRED

No boot-path edits in this lane. Wiring a won quote through `BuildHandoff`
into a supported runtime (and converting routing `RawInstructionArtifact`s
into R-03 plans, audit blocker 7) is deferred to a follow-up lane. The kernel
has no registry, no provider enablement, no env reads, no network, no
sign/send/live claims, and no simulation/qualification authority. Adapter
lanes (Sui x7, Titan/Rango) should now build ON this contract instead of
extending one plane — per the R13 task rule "Extend the current
QuoteProvider/TransactionBuilder owner only after code audit and one frozen
interface contract"; the frozen interface now exists.

## 4. Offline test evidence (exact counts)

`tests/test_r13_kernel_contract.py` — **33 passed** in ~1.9s
(`python -m pytest tests/test_r13_kernel_contract.py -q --disable-socket
--allow-unix-socket`), pytest-socket applied, `pytest.mark.unit`, inline
offline fixtures only, deterministic (fingerprint-stability and
ordering-stability tests included). Coverage groups: kernel identity/reuse of
R-03 types; quote construction invariants (execution authority refusal,
unknown-minimum preservation, exact-int amounts, route venue bounds); dedup
verdicts (shared pool id, disjoint-pool independence, unknown-evidence
UNKNOWN, same-group correlation, aggregator lineage overlap, Sui object-id
canonicalization, deterministic clusters, independence set); race behavior
(loser preservation with typed reasons, ranking stability, stale/slot-gap
handling, typed failure preservation, comparability refusals, no-winner
state); no-extrapolation refusals (neighborhood, non-integer, ExactOut
binding); build handoff integrity (real R-03 plan reference, non-winner
refusal, status forgery refusal, provider mismatch, truthfully blocked plan,
chain parity, non-R03 status rejection).

`python -m mypy src/execution/quote_build_kernel.py` — **0 errors**
(`Success: no issues found in 1 source file`; the pre-existing 3 yaml-stub
errors elsewhere are known local noise). `black` clean on both new files.

## 5. Blockers closed vs remaining

Closed by this freeze (the audit's §7 "one coherent pair"):

- `R13_GAP_NO_KERNEL` — one canonical quote/race/dedup/handoff contract now
  exists with documented mappings for the governed, routing and (future) Sui
  planes; adapter lanes extend it instead of creating a fourth plane.
- `R13_GAP_NO_POOL_DEDUP` — pool-ID + aggregator-lineage intersection dedup
  with typed independent/correlated/unknown verdicts is now executable and
  tested; aggregator-vs-aggregator comparisons can no longer be consumed as
  independent liquidity.

Remaining (unchanged, per audit §7):

- `R13_GAP_NO_ADAPTER` (Sui x7; Titan, Rango on Solana) — adapters are now to
  be built one per PR against this frozen contract.
- `R13_GAP_UNWIRED` (OKX promotion, OpenOcean enablement, Odos admission) —
  each still requires its pinned evidence gate; do not promote by config.
- `R13_GAP_PARTIAL_WIRING` (0x governed capture) — operational: public taker
  + `ZEROX_API_KEY` under bounded opt-in.
- `R13_GAP_NO_BUILD_PLAN_CONVERSION` — quote->plan bridge
  (`RawInstructionArtifact` -> R-03 plan) remains its own frozen-interface PR;
  `BuildHandoff` is the typed seam it will fill. Build outputs stay inert
  evidence until then (correct safety posture).

## 6. Recommendation

Merge this freeze before any R13 adapter lane. Then: (1) first adapter slice
= ONE Sui provider (Aftermath or 7K) or Titan on Solana, built on
`NormalizedProviderQuote`/`PoolIdentityDeduplicator` with per-provider PRs;
(2) a separate follow-up lane wires `BuildHandoff` and the
`RawInstructionArtifact`->R-03 conversion; (3) every sizing point keeps using
`refuse_amount_extrapolation` — the kernel makes scaling impossible by
construction; keep it that way.
