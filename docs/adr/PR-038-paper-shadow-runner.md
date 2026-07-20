# PR-038 — Production-grade paper/shadow runner boundary

## Context

Roadmap PR-038 is supposed to replace the legacy `scripts/paper_trader.py` with the same kernel that later feeds live execution:

`discovery → detector → sizing → planner → compiler → final simulation → reconciliation → journal`

At the time this branch is created directly from `main`, several required upstream stages are still being developed in parallel PRs. A full end-to-end claim would therefore be misleading.

## Decision

This PR introduces a sender-free `src.paper_shadow` runner that records durable lifecycle evidence and fails closed when a required upstream stage is missing.

The old `scripts/paper_trader.py` is reduced to a thin wrapper around:

```bash
flashloan-bot paper-shadow
```

This preserves the operator entrypoint while preventing the previous legacy Jupiter quote-loop from bypassing the supported runtime.

## Safety invariants

- No live sender is imported or enabled.
- No synthetic fills are allowed.
- No transaction signatures, signed transaction bytes, txids or landed/submitted flags may appear in journal events.
- Missing sizing/planning/compilation/simulation/reconciliation stages produce explicit `blocked_missing_stage_*` terminal evidence.
- An idle run is healthy only when no candidates are present; it is not a production-readiness claim.
- The journal is append-only JSONL and continues sequence numbers across restart.

## Parallel PR compatibility

This PR intentionally does not import open PR-032/033/034/035/036/037 branch code. Those PRs can later attach concrete stage callables to the runner without changing the runner's safety contract.

## Non-goals

- No MarginFi/Jupiter instruction planning.
- No V0 compilation.
- No exact RPC simulation.
- No SPL/native reconciliation.
- No sender, signer, Jito or RPC submission.
- No live-canary enablement.

## Follow-up integration

After PR-033..PR-037 are merged, the composition root should pass the real detector candidates and canonical stage implementations into `PaperShadowRunner`. At that point `blocked_missing_stage_*` should disappear from ordinary paper/shadow runs and be replaced by exact simulated/reconciled paper outcomes.
