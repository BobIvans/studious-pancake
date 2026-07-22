# PR-142 — Structured runtime orchestration and bounded resource lifecycle

This PR starts the third-audit **PR-142** scope as an additive review/evidence
gate.  The full roadmap target is a long-running paper/shadow runtime that is
continuous, bounded, cancellation-safe and recoverable.

## Why this slice is intentionally narrow

Parallel PRs are still moving `main`, including prior paper-readiness,
shadow-soak and evidence-bundle gates.  This patch therefore avoids editing the
active runner, task supervisor, queue, tracker, lifecycle store or workflows.
It adds a deterministic contract that later runtime integration can feed with
real implementation evidence.

## Boundary added

`src/runtime_orchestration_pr142.py` defines:

- stage budgets for discovery, exact quote, capital, planning, compile,
  simulation, reconciliation and journal/export;
- supervised component contracts for discovery loop, candidate processor,
  provider clients, lifecycle writer, observability exporter and readiness
  server;
- finite resource limits for tasks, provider calls, candidate queues, evidence
  blobs, exception history, logs, caches, outbox, DB connections and file
  descriptors;
- queue/tracker cleanup evidence requiring expired queue items to release
  tracker `PENDING` and terminal states to have bounded retention;
- SQLite/process leadership evidence requiring a dedicated writer actor,
  bounded command queue and second-writer fencing;
- shutdown evidence requiring ordered drain, checkpoint, client close and
  readiness-false-before-exit;
- fault-injection coverage for stage hangs, child task crash, cancellation,
  queue full, tracker expiration, SIGTERM, second process, DB locked, event
  loop lag and swallowed cancellation.

## Safety properties

- This slice does **not** start the active runtime.
- It does **not** enable paper/live execution.
- It does **not** import a sender or signer.
- It performs no RPC/Jito/Helius/MarginFi/Jupiter network calls.
- `paper_runtime_claim_allowed` and `live_claim_allowed` remain `false` even
  when the review evidence is complete.

## Regression coverage

`tests/test_pr142_runtime_orchestration.py` verifies that the gate blocks:

- missing per-stage deadlines;
- one-shot `run_until_stopped()` semantics;
- critical task death that does not affect readiness;
- expired queue items that do not release tracker pending state;
- a DB model that permits a second writer process;
- shutdown without no-orphan-task and `CancelledError` propagation proof;
- missing chaos coverage for stage hang, queue full and DB locked;
- dead `stop_on_first_blocked_candidate` semantics;
- malformed hashes and duplicate stage evidence.

## Suggested verification

```bash
python -m pytest tests/test_pr142_runtime_orchestration.py -q
python scripts/verify_repo.py --skip-dependency-audit
```

## Follow-up integration

Later PR-142 implementation work can wire this contract into:

- `src/paper_shadow/runner.py`;
- `src/strategy/runtime.py`;
- `src/strategy/queue.py`;
- `src/strategy/tracker.py`;
- `src/runtime_discovery_coordinator.py`;
- `src/durability/lifecycle.py`;
- `src/execution/journal.py`;
- `src/container_runtime.py`.

That follow-up should replace the offline evidence fixture with real supervisor
state, deadline enforcement, queue/tracker cleanup, DB actor ownership,
structured cancellation and chaos-run reports.
