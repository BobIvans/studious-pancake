# R10-1 WIP handoff — 2026-11-15 (implementation landed, finalization open)

**Branch:** `codex/pre-api-market-route-qualification-2026-11-15`
**Base at start of session:** origin/main `73191514` (PR #658 docs contract merged)
**Status:** WORK IN PROGRESS — code + tests committed; deliverable docs, mypy cleanup,
replay-report artifact, R10-1/MASTER00 status update and Russian final report still open.

## What is done and verified

1. **Preflight complete.** Remote fetched; main `73191514`; open PRs #649/#655/#657 audited
   (no overlap); no branch protection on main (404); worktree `sp-worktrees/r10-cpmm-binding`
   still at base `a82a512b` with NO implementation — no duplicate owner exists.
   `src/strategy/cpmm_cycle_binding.py` did not exist anywhere before this session.
2. **Implementation:**
   - `src/strategy/cpmm_cycle_binding.py` (NEW, canonical owners reused only):
     `CpmmBindingRejection` typed enum (incl. `NO_QUALIFIED_LENDER_EDGE`,
     `BUILDER_UNQUALIFIED`, `SIMULATION_SOURCE_BLOCKED`, `QPR_NOT_READY`),
     `VenueKind`/`RouteSupport`/`RouteQualificationStatus`, `PoolLineage`,
     `BlockedVenueCandidate`, `PaperGateInputs` + `evaluate_paper_gate`
     (fail-closed: offline replay can NEVER emit PAPER_COMPLETE),
     `evaluate_exact_two_leg_route` (sequential conservative-output propagation,
     no quote scaling), `classify_route_support` (CPMM 2/3/4 exact; 5-hop
     shortlist-only; CLMM/DLMM/orderbook blocked),
     R13-K `PoolIdentityDeduplicator` dedup at pool level (shared physical pool
     id across aggregators → all aliased views rejected) AND pairwise per-route
     independence (UNKNOWN blocks), AGG-05 `search_bounded_cycles` shortlist
     binding with exact-promotion only for 2/3/4-hop CPMM, PR118 per-size fresh
     exact re-evaluation via `evaluate_pr118_non_monotonic_sizing`,
     mixed-generation partition, `run_pre_api_route_qualification_replay`
     producing `PreApiRouteQualificationReport` with all required stage metrics,
     separate ratios, fixture/replay provenance, deterministic sha256 digest,
     sign/send/live hardcoded False.
   - `src/strategy/exact_cpmm_capacity.py` (additive edit): `CapacityEconomics.
     ledger_for_legs(...)` generalizes the PR118 all-in ledger to 2-leg
     sequences; `ledger_for` now delegates to it (existing tests untouched and
     green).
   - `tests/test_sxr1_cpmm_cycle_binding.py` (NEW): 25 unit tests, all passing:
     positive two-leg / 3-pool triangle (non-monotonic optimum 20 selected) /
     4-pool cycle; sequential amount propagation; gross-positive/net-negative;
     marginal shortlist rejected by exact evaluator; amount-local zero point
     pass-through; unknown cost denomination blocks; stale state; mixed
     generation; slot skew; identity (wrong program / wrong decimals);
     non-closed path; repeated venue; same-pool alias across aggregators;
     unknown lineage; route support matrix; blocked CLMM/DLMM/orderbook;
     5-hop never exact-promoted; paper gate typed progression; determinism;
     digest sensitivity; fixture scope / no execution authority; ratio keys.
3. **Verification done:**
   - `.venv/Scripts/python.exe -m pytest tests/test_sxr1_cpmm_cycle_binding.py
     tests/test_exact_cpmm_capacity.py tests/test_pr118_non_monotonic_sizing.py
     tests/test_r13_kernel_contract.py -q` → **92 passed** (25 new + 67 regression).
   - `black` applied (2 files reformatted); `flake8` clean on all 3 changed files.
4. **Known open defect:** `mypy --config-file mypy.ini src/strategy/cpmm_cycle_binding.py`
   → **36 errors** (mostly attr-defined inside the long `run_pre_api_route_qualification_replay`;
   first: `BlockedVenueCandidate.hop_count` at ~line 1382 where a blocked-venue
   loop shadows `candidate`). NOT yet fixed.

## What remains to complete the PR (next task)

1. **Fix 36 mypy errors** in `src/strategy/cpmm_cycle_binding.py` (rename shadowed
   loop vars, add type annotations for the closure factories, remove dead
   `evaluation_id`/`legs` leftovers if any). Re-run:
   `mypy src/strategy/cpmm_cycle_binding.py src/strategy/exact_cpmm_capacity.py --config-file mypy.ini`.
2. **Regressions after black reformat:** rerun the 4-file pytest suite (was green
   pre-format; binding file alone re-verified 25/25 post-format).
3. **Replay report artifact:** small script or test-embedded dump writing
   `docs/roadmap/pre-api-market-route-qualification-2026-11-15/replay_report.json`
   (+ digest) from `run_pre_api_route_qualification_replay` over the fixture set
   (two-leg + triangle + 4-pool + alias + blocked-venue cases), clearly marked
   `fixture-replay`.
4. **Docs deliverables (same PR):**
   - R10-1/MASTER00 status update: `MASTER00_IMPLEMENTATION_MATRIX.json` R10-1 row
     PLANNED → IMPLEMENTED_UNQUALIFIED (offline replay), and
     `PARALLEL_EXECUTION_STATUS.json` entry.
   - Before/after owner-map note, changed-file list.
   - Supported-vs-blocked route matrix (already encoded in `classify_route_support`;
     document it).
   - API preflight checklist (§6 of CODEX_START_HERE_RU.md — prepare only).
   - Russian final report (ИТОГОВЫЙ ОТЧЁТ): current SHA, changed files, metrics,
     remaining R02/R03/R04/R05/R06 blockers.
5. **config/format_targets.txt:** append the 3 new/changed file paths at EOF
   (CI black-checks them).
6. **CI-grade checks before push/merge:** run repo verification per house rules
   (`python scripts/verify_repo.py` from the worktree if feasible), then push,
   open/update PR (PR #658 is already MERGED as docs-only, so a NEW PR is needed
   from this branch targeting current main), wait for checks, request review.
   NO merge without explicit human approval (AGENTS.md rule 11).
7. **Hard-stop review before PR:** confirm no signer/sender/wallet/borrow/submit/
   provider-activation code paths were introduced; sender/sign/live all False.

## Facts the next session must not re-derive

- PR #658 (docs contract) is MERGED; the implementation must go through a NEW PR
  on this same branch.
- No required checks/branch protection exist on main; merge gate is manual +
  AGENTS.md rules.
- `evaluate_sampled_cpmm_capacity` already existed (back half); the new binding is
  the front half (discovery→topology→dedup→plan→two-leg exact→paper seam).
- Both directed cycles of a triangle are enumerated (topology counts 2); the
  reverse direction typically fails the exact grid — tests assert this.
- Route pre-check evaluates at `grid[0]`; amount-local failures (zero output,
  capacity, negative gross) pass through to the full PR118 grid.
- PR118 `evaluate_pr118_non_monotonic_sizing` itself catches
  `PR118SizingPointRejected` from the factory — negative-gross points become
  `rejected_points`, and a route with no admissible point gets `NET_NEGATIVE`.
