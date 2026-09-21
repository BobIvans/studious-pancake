# SUPER-03 — venues, circular qualification and bounded parallel solvers

Base at branch creation: `main@27875850a88edf102c904e31955e0df8b78b13b4`.

SUPER-03 executes the residual closure for **W2-06 + W2-07 + W2-08**. It is
deliberately an integration/qualification closure over current owners rather than a
second implementation of runtime, qualification, solver, capital, signer or sender
authority.

## Reused canonical owners

- W2-06 direct venue identity/capability: `src/direct_venue/mpr2617.py`.
- W2-07 campaign/episode/variant/survival/holdout evidence:
  `src/production_qualification.py` from merged AGG-04.
- W2-08 worker conflicts: `src/strategy/conflict_scheduler.py`.
- W2-08 bounded 2–5 hop search: `src/strategy/multihop_solver.py`.
- W2-08 split-flow: `src/economics/split_flow.py`.
- Integer decoded CLMM/DLMM traversal: `src/strategies/stable_peg/math.py`.

## Residual code implemented

### W2-06 / PR-098..101

`src/direct_venue/super03.py` adds a fail-closed admission layer for the venue
families that MPR-2617 intentionally left reserved:

- Raydium CPMM: integer exact-input constant-product vector with explicit trade fee
  and input/output transfer-fee evidence;
- Raydium CLMM: already-decoded tick-band traversal plus independent reference
  output/fee and exact instruction parity;
- Meteora DLMM: already-decoded bin traversal plus dynamic-fee, complete-bin and
  full consumed-input proof;
- exact source commit, symbol, reuse mode and license decision;
- verified program/pool/mint/deployment identity and complete account dependency
  closure;
- exact instruction data/account vector parity;
- only `OFFLINE_VERIFIED` capability materialization.

The module does **not** decode an unqualified deployed account, invent missing
tick/bin state, copy GPL/non-permissive/unknown-license source, or infer an
instruction from a documentation example. Missing current deployment, license,
dependency or differential evidence returns `BLOCKED_EXTERNAL`.

Orca remains owned by MPR-2617. SUPER-03 does not create a second Whirlpool adapter
or claim that any concrete pool is operationally qualified.

### W2-07 / PR-102..104

AGG-04 already owns frozen campaign policy, episode identity, immutable amount /
lender / route / frame / cost / message variants, horizon probes, censoring,
temporal holdout, class verdict, dashboard evidence and demotion.

SUPER-03 closes two repository-internal residuals without replacing that owner:

- **NF-131**: generation/adapter/policy/route/amount-bound cache identity. Negative
  entries require a bounded TTL; state generation can be invalidated explicitly.
- **NF-132**: deterministic fixed-workload benchmark evidence. Baseline and
  challenger must use the exact same case IDs and state generations; provider calls,
  work units, feasibility and positive-net counts are recorded rather than turning
  “more candidates” into an automatic win.

Protocol-specific shared-state evolution replay, actual campaign measurements and a
full multi-family paper pass remain residual evidence, not synthetic PASS results.

### W2-08 / PR-105..107

Merged AGG-05 already implements this scope:

- conflict-aware worker scheduling, fencing, shared reservations and backpressure;
- bounded 2–5 hop search with explicit budget exhaustion and full-resource exact
  evaluator boundary;
- joint discrete split allocation with one shared state, capacity conservation,
  residual-debt/resource checks and comparison against the best evaluated single
  path.

SUPER-03 tests import and exercise these owners instead of creating replacements.

## Operational truth

This PR is safe to merge as default-off code/evidence when current-head checks pass.
It does not make SUPER-03 operationally complete. Current external/integration
blockers are recorded in `config/super03_coverage.json`, including current
Raydium/Meteora deployed differential vectors, concrete Orca pool/license evidence,
protocol-specific mutable-state replay and a measured multi-family campaign.

Hard invariants:

- `live_enabled=false`;
- no signer or private key;
- no RPC/Jito transaction submission;
- no funding or remote mutation;
- no production-ready or profitability claim;
- blocked venue evidence cannot become an executable capability.

## Rollback

Disable use of `src.direct_venue.super03` admission outputs and clear request-local
solver caches. Existing MPR-2617, AGG-04 and AGG-05 owners remain unchanged. Evidence
and coverage history should be retained.
