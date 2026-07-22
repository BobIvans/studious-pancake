# PR-156 — Structured durable paper runtime gate

This slice adds a low-conflict, side-effect-free contract for the renamed roadmap
PR-156: structured durable sender-free paper runtime and real operational
evidence.

## Scope

The gate models the evidence a later integration must provide before claiming
that standard paper/shadow execution is production-grade:

- one `RuntimeTruth` binding for policy, provider admission, market kernel and
  transaction proof;
- one authoritative SQLite lifecycle/outbox store;
- JSONL not authoritative;
- repeated structured cycles under a `RuntimeSupervisor`;
- per-stage monotonic deadlines and cancellation propagation;
- critical task failure changing readiness;
- no orphan tasks after shutdown;
- hardened transport limits and typed retry taxonomy;
- Helius-style webhook auth, fast ACK, durable enqueue, persistent dedup and gap
  backfill;
- multi-RPC independence/finality evidence;
- deterministic observability replay evidence;
- sender-free shadow harness with required fault injection coverage.

## Safety

This PR does not start a runtime, call providers/RPC/webhooks, modify durable
state, sign, submit, or enable live. It is a review/evidence gate only.

`live_claim_allowed` and `sender_submission_allowed` are always `False`.

## Added files

- `src/durable_paper_runtime_pr156.py`
- `tests/test_pr156_durable_paper_runtime.py`
- `docs/pr156_durable_paper_runtime.md`

## Local focused checks

```bash
python -m py_compile src/durable_paper_runtime_pr156.py tests/test_pr156_durable_paper_runtime.py
PYTHONPATH=/mnt/data/pr156 python -m pytest -q tests/test_pr156_durable_paper_runtime.py
```

## Follow-up integration

Later PR-156 implementation can wire this contract into the actual composition
root, runtime supervisor, durable lifecycle store, paper journal migration,
webhook intake, multi-RPC policy, observability exporter and sender-free soak
harness after PR-152/153/154/155 contracts stabilize.
