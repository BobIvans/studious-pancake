# AGG-05 — Parallel strategies and joint route search

Branch: `codex/agg-20260920-05`

Base at implementation start: `main@0c4f216a62d62b20f6fb4ec4bbd0548cea58df65`.

## Scope

This change implements the code slice for AGG-05 work packages:

- RUNTIME-01: NF-239, NF-241, NF-242
- SOLVER-01: NF-125, NF-129, NF-130, NF-135
- SOLVER-02: NF-128, NF-136

The code remains sender-free. It does not load a signer, submit transactions, enable
live mode, create a second lifecycle store, or create a second capital/quota ledger.

## Ownership

RUNTIME-01 consumes canonical ownership rather than replacing it:

- route conflicts derive from the existing routing resource footprint;
- capital/quota admission is delegated through a composition-owned reservation port;
- worker ownership is represented by lifecycle-issued fencing evidence;
- a stale worker cannot complete another fencing generation;
- shared pools, writable accounts, fee payer, nonce/object identities and explicit
  lender resources such as the Slumlord PDA conflict deterministically.

The existing `OpportunityQueue`, durable lifecycle store and
`DurableCapitalCoordinator` remain canonical owners.

## Search semantics

SOLVER-01 adds deterministic bounded 2-5 hop cycle search. Marginal rates are only a
shortlist signal. An exact evaluator must bind amount, state generation, compute,
message bytes, writable accounts, rent, fees and conservative net before ranking.

Search/evaluation exhaustion returns an explicit `budget_exhausted` result and is
not evidence that no opportunity exists. Fee/tip selection is hard-cap bounded and
does not use an unlabelled landing probability.

## Split-flow semantics

SOLVER-02 enumerates a bounded discrete allocation grid and explicit path orderings.
Every branch runs against one immutable shared state generation. Shared capacity is
consumed between branches, residual debt rejects the allocation, resource limits are
checked after joint replay, and the solver never claims a global optimum when its
evaluation budget is exhausted.

A split is promoted only when the selected result is genuinely multi-path and beats
the best evaluated single-path baseline.

## Dependency truth

The master plan names AGG-02 and AGG-04 as package dependencies. At branch creation:

- `codex/agg-20260920-02` exists but is identical to `main`;
- no AGG-04 branch/PR was observed.

Therefore this PR may establish merge-safe, default-off AGG-05 code contracts, but
it does not claim external qualification of AGG-02/04 data/state/campaign evidence.
Operational status remains UNQUALIFIED until those prerequisites and downstream
qualification evidence exist.

## Verification

The dedicated AGG-05 workflow installs the hash-locked Python 3.13 environment,
checks installed imports outside the checkout, compiles and Black-checks the changed
surfaces, runs the AGG-05 regressions plus existing durable-capital,
non-monotonic-sizing and durable-completion regressions.

Local isolated preparation before publication of the branch:

```text
21 passed
```

This local run exercised only the newly added pure modules/tests; GitHub Actions is
authoritative for repository integration and merge readiness.
