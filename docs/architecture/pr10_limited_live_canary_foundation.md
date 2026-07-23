# Roadmap PR-10 — Limited-live canary foundation

## Purpose

PR-10 is the final numeric-roadmap boundary. It may be reviewed only after
PR-01 through PR-09 produce one release-bound evidence set for the exact code
commit, PolicyBundle and release digest.

This slice is deliberately not an activation change. It adds a fail-closed
admission contract that can prove whether the prerequisites are coherent while
keeping compile-time canary support, runtime live mode and submission disabled.

## Required prerequisite evidence

The evaluator requires exactly one immutable, non-synthetic, human-reviewed
evidence item for every roadmap task from PR-01 through PR-09. Every item must:

- pass its own gate;
- bind the exact candidate code commit;
- bind the exact release digest and PolicyBundle;
- remain unexpired;
- identify a human reviewer;
- contribute to reviewer diversity.

An open pull request, branch name, CI success, hash-shaped placeholder or
self-asserted readiness flag is not sufficient evidence.

## Canary scope

The foundation permits review of exactly one scope at a time:

- one reviewed pair/provider/program allowlist;
- RPC or Jito single-transaction transport only;
- at most 5,000,000 lamports of exposure;
- exactly one outstanding submission;
- reviewed network, priority-fee and optional Jito-tip caps;
- a protected wallet reserve that is no lower than the request-wide reserve.

The module contains no sender, signer, private-key, RPC, Jito or HTTP client.

## Mandatory safety conditions

All of the following must be true before the result can become
`ready-for-independent-activation-review`:

- separate requester, release approver, risk approver and operator;
- manual kill switch and all loss/failure/freshness/divergence/reconciliation,
  settlement and reserve latches armed;
- rollback to shadow without a code change;
- post-trade reconciliation required;
- no unresolved settlement or active exposure;
- isolated signer boundary reviewed;
- finalized settlement boundary reviewed;
- protected deployment reviewed;
- default live disabled;
- environment-only activation forbidden;
- AI authority forbidden.

## Compile-time deny

```python
COMPILE_TIME_CANARY_ENABLED = False
```

Even a complete evidence bundle cannot submit a transaction or enable live
mode. A later independent change must be reviewed after PR-01 through PR-09 are
merged and their real release artifacts are accepted.

## Verification

```bash
python -m pytest tests/test_pr10_limited_live_canary.py -q
python -m black --check \
  src/live_canary/roadmap_pr10.py \
  tests/test_pr10_limited_live_canary.py
python -m mypy --config-file mypy.ini src/live_canary/roadmap_pr10.py
```

The existing PR-046 canary workflow also runs because this slice changes
`src/live_canary/**`, preserving compatibility with the earlier canary controls.
