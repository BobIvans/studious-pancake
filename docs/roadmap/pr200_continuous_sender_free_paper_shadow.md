# Roadmap PR-200 — Continuous sender-free paper/shadow harness

This slice implements the first additive PR-200 boundary from the consolidated production-readiness roadmap: a deterministic, sender-free paper/shadow replay and soak evidence harness.

## Scope

- Continuous bounded paper/shadow loop over recorded or synthetic candidate events.
- One deterministic candidate-to-attempt replay identity.
- Immutable JSONL event, outcome and report datasets with schema version and hashes.
- Sender-free process guard that fails closed if signer/sender packages were imported.
- Typed rejection counters rather than silent exceptions.
- Chaos hook for kill/restart style evidence without live side effects.
- Daily/soak report payload binding release, config, code and data hashes.

## Safety boundary

This PR does not enable live trading, wallet loading, signing, RPC/Jito submission, private-key handling or finalized/live PnL booking. All terminal outcomes emitted by the new harness are `simulated` paper/shadow outcomes.

## Remaining full PR-200 work

The full roadmap still requires active cutover through merged PR-196/197/198/199 verticals, real 72-hour soak artifacts, provider partitions, DB-full/lock fault injection, replay of recorded mainnet data and production report retention policy.
