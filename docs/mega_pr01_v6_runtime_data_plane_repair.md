# MEGA-PR-01 V6 runtime/data-plane repair gate

This PR implements the V6 MEGA-PR-01 follow-up boundary for:

- `IMPL-85` — Jupiter quota must be durable by API account across processes and restarts.
- `IMPL-86` — Jupiter cache identity must be collision-free, semantic and usable before quota spend.
- `IMPL-94` — management-secret file reads must use a single-open `O_NOFOLLOW`/`fstat` boundary.

## What changed

### Durable Jupiter quota

`src/providers/jupiter/durable_quota.py` adds a transport-free SQLite quota authority:

```text
BEGIN IMMEDIATE
-> prune expired window/cooldown/cache state
-> account-scoped reserve / mark-used / release
-> persisted Retry-After cooldown
-> persisted semantic cache
```

The manager is keyed by `api_account_id`, so two runtime processes sharing the same DB cannot each spend the same account-wide request budget.

### Semantic cache identity

`src/providers/jupiter/quota.py::cache_key` now returns a SHA-256 digest over a strict JSON envelope instead of joining values with `|`. This removes delimiter collisions such as:

```text
("a|b", "c") == ("a", "b|c")
```

The identity can include endpoint schema, API account hash, mints, amount, taker/payer, slippage, DEX policy, purpose and lifecycle stage before a request consumes quota.

### Fail-closed V6 evidence contract

`src/mega_pr01_v6_runtime_data_plane_gate.py` adds an explicit acceptance report for the three V6 MEGA-PR-01 findings. It keeps live/signer/sender surfaces structurally denied.

## Safety boundary

This PR does not enable:

- live trading;
- signer or private-key access;
- RPC/Jito transaction submission;
- Jupiter network calls;
- provider cutover;
- production paper promotion.

The durable quota manager is a local accounting authority only. It does not create HTTP sessions or submit any transaction.

## Focused verification

```bash
python -m py_compile \
  src/providers/jupiter/quota.py \
  src/providers/jupiter/durable_quota.py \
  src/mega_pr01_v6_runtime_data_plane_gate.py \
  tests/test_mega_pr01_v6_runtime_data_plane_repair.py

PYTHONPATH=. python -m pytest -q \
  tests/test_mega_pr01_v6_runtime_data_plane_repair.py
```

## Remaining physical cutover

This slice creates the durable authority and gate. A later wiring commit should make the active Jupiter provider factory instantiate `DurableJupiterQuotaManager` from the approved runtime persistence path and replace the active management secret reader with `read_secure_regular_file` directly.
