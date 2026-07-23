# PR-226 — Deterministic Opportunity Runtime, Dataset and Shadow Qualification

This is the first safe PR-226 acceptance-contract slice for audit Pass 8/9.

## Scope

PR-226 owns the final sender-free runtime/ML qualification boundary for findings
F-355 through F-386 and F-404 through F-409. It covers deterministic opportunity
identity, temporal queue correctness, durable terminal protocol, structured
supervision, dataset label provenance, atomic dataset publication, leakage-safe
splits, model gates and runtime namespace/config safety.

The uploaded roadmap marks PR-226 as dependent on PR-225 and PR-227. This slice
therefore remains fail-closed until accepted provider/discovery evidence and
exact-money/atomic evidence are installed and reachable.

## Safety boundary

This module is offline and side-effect free. It does not:

- contact providers, RPC, Jupiter, Jito, Helius or MarginFi;
- read secrets or private keys;
- construct, sign or submit transactions;
- enable live execution;
- claim real shadow qualification without PR-225 + PR-227 evidence.

A passing report can only express sender-free shadow qualification for a
materialized evidence bundle. It always returns:

```text
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
private_key_allowed=false
```

## Evidence contract

The gate requires proof that:

- all PR-226 findings are covered exactly once;
- PR-225 and PR-227 are accepted, reachable from the installed artifact and have
  non-placeholder evidence hashes;
- opportunity creation rejects NaN, Infinity, bool-as-int, fractional base units,
  negative slots and shallow mutable metadata;
- queue/ranker logic re-checks expiry after awaits and before enqueue/claim;
- durable sink commit is required before terminal success;
- task death blocks readiness and shutdown/stop errors are materialized;
- labels only use terminal events before cutoff and include exact provenance;
- dataset rows, manifest, schema and split are one immutable generation;
- group-temporal split, embargo, sample-size, real metrics and OOD gates block ML
  promotion when unsafe;
- runtime config is finite, owner/state paths are generation-bound and shared
  `/tmp` secret namespaces are rejected;
- shadow evidence is materialized from the installed wheel and replayable.

## Verification

Focused local verification used before opening:

```bash
PYTHONPATH=. python -m py_compile \
  src/pr226_deterministic_runtime_dataset_shadow_gate.py \
  tests/test_pr226_deterministic_runtime_dataset_shadow_gate.py

PYTHONPATH=. python -m pytest -q \
  tests/test_pr226_deterministic_runtime_dataset_shadow_gate.py
# 14 passed
```

## Remaining full PR-226 work

This is not the full physical runtime cutover. Later PR-226 commits must wire the
same contract into the installed sender-free paper/shadow supervisor, durable
terminal sink, dataset generation CLI, split/model gate and readiness surface
once PR-225 and PR-227 are stable. Old one-shot evaluator and hardcoded replay
booleans must be retired rather than kept as parallel authority.
