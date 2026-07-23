# Roadmap PR-196 — Durable runtime kernel

## Status

This PR installs the first sender-free PR-196 runtime kernel slice. It does not
sign, send, submit, import Jito/RPC senders, or enable live trading.

## Scope

The kernel adds one SQLite authority for deterministic attempt identity,
lease/fencing ownership, terminal outcome, outbox redrive, recovery scanning,
backup/restore, and a bounded continuous supervisor.

Implemented foundations:

- stable attempt key from `opportunity_identity + evidence_generation + plan_hash + attempt_generation`;
- SQLite `WAL`, `busy_timeout`, `synchronous=FULL`, `foreign_keys=ON`, `trusted_schema=OFF`, and integrity checks;
- atomic attempt admission, lease acquire/steal, terminal outcome and terminal outbox event;
- stale fenced writer rejection;
- idempotent terminal replay and changed replay rejection;
- pending outbox claim/publish with owner checks;
- deterministic recovery scan for stale leases, resumable active attempts and undelivered outbox;
- online backup, manifest digest and restore validation;
- continuous supervisor that fails readiness when a mandatory worker dies.

## Deliberately absent

- no active paper/shadow composition cutover;
- no live, signer, RPC sender, Jito sender, or transaction compiler integration;
- no provider, MarginFi, Jupiter, Helius or finalized-settlement behavior;
- no mutation of existing PR-02/A3 compatibility tables.

A later PR-196 slice can wire this kernel behind the installed paper/shadow
composition once the surrounding PR-197/PR-199 provider and execution authorities
are merged.

## Verification

Focused local verification before pushing:

```bash
python -m pytest tests/test_pr196_durable_runtime_kernel.py -q
python -m py_compile \
  src/durability/runtime_kernel_pr196.py \
  tests/test_pr196_durable_runtime_kernel.py
```

The regression file is also registered in `config/format_targets.txt`, and the
runtime kernel is part of the repository mypy target list.
