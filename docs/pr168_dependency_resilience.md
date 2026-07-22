# PR-168 — External dependency resilience gate

This PR adds a side-effect-free review/evidence contract for external
dependency resilience. It is intentionally additive while the runtime, signer,
release and infrastructure PRs are moving in parallel.

## Implemented slice

- `src/dependency_resilience_pr168.py`
- `tests/test_pr168_dependency_resilience.py`
- This document

The gate models the evidence required before production-style provider soak:

- dependency catalog entries by provider, purpose, quota, timeout, retry policy,
  circuit policy, fallback and consistency contract;
- independent bulkheads for discovery, finalization, RPC reads, simulation,
  settlement polling, Jito, webhook/backfill and telemetry/backup;
- one shared absolute deadline and retry budget per operation;
- persisted rolling circuit breaker evidence with differentiated failure kinds;
- fatal auth/schema/evidence failures that cannot auto-recover by cooldown alone;
- fallback equivalence proofs that preserve atomic, security and economic
  guarantees;
- graceful-degradation states that preserve settlement/reconciliation capacity;
- dependency outage drills with stable memory/FD/queue usage;
- readiness and alerting reflection of the dependency matrix.

## Safety / non-goals

This PR does not call any external dependency and does not change active runtime
wiring.

- No live trading.
- No sender or signer path.
- No RPC/Jito/Jupiter/OKX/OpenOcean/Helius calls.
- No HTTP transport changes.
- No Docker, workflow, dependency lock or deployment changes.
- `live_claim_allowed` and `sender_submission_allowed` stay false.

## Why fail closed

A dependency outage must never weaken transaction safety. The evaluator blocks
when a fallback drops composable-instruction capability, when required dependency
loss does not stop trading, when nested retry layers do not share one budget, or
when circuit state can be erased by restart.

## Local focused check

```bash
python -m py_compile src/dependency_resilience_pr168.py tests/test_pr168_dependency_resilience.py
PYTHONPATH=. python -m pytest -q tests/test_pr168_dependency_resilience.py
```

## Follow-up integration

Later integration can feed this contract from real provider clients, quota
managers, HTTP transports, persistent circuit state, readiness, alerting and
outage-drill reports once PR-153/154/156/160 contracts stabilize.
