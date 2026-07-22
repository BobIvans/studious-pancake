# PR-144 — Shadow soak evidence gate

This PR adds a deterministic, side-effect-free evidence gate for the shadow soak
that must happen before any live-canary promotion can be reviewed.

## Scope

The readiness roadmap requires a real shadow/paper soak before live canary:
exact paper vertical evidence, CPI call graph, observability, data lineage,
finalized/simulated reconciliation and no sender or live submission side effects.

PR-144 turns that into a small machine-checkable contract. It does not run the
soak and does not wire runtime stages. It only evaluates explicit evidence
records supplied by future soak tooling or operator reports.

## What this patch adds

- `src/shadow_soak_pr144.py`
  - explicit 72-hour default soak window requirement;
  - required shadow evidence streams:
    - candidate identity;
    - exact simulation;
    - CPI call graph;
    - observability events;
    - data lineage;
    - simulated finalized settlement;
    - readiness report;
  - fail-closed checks for missing streams, placeholder hashes, unreviewed
    evidence, incomplete terminal reconciliation, gaps, duplicate identities and
    exceeded error budget;
  - hard rejection of live flags, sender invocations, submission attempts and
    observed on-chain transaction signatures;
  - deterministic report hash;
  - release-gate payload that never grants live canary by itself.

- `tests/test_pr144_shadow_soak_gate.py`
  - positive review-ready 72h fixture;
  - negative checks for short duration, missing CPI stream, unreconciled terminal
    event, sender/submission side effects, signature observation, live flag,
    placeholder hash, gaps/duplicates and error budget;
  - deterministic report hash fixture.

## Non-goals

- No live trading.
- No paper/live execution enablement.
- No signer or sender path.
- No RPC, Jito, Helius, MarginFi, Jupiter or provider network call.
- No active runtime wiring.
- No claim that the repository already ran a real 72-hour soak.

## Why additive

Parallel PRs are moving `main`. This patch avoids shared hot files such as
`scripts/verify_repo.py`, `config/format_targets.txt`, workflow files and active
runtime modules. It is intentionally reviewable while other PRs continue to land.
