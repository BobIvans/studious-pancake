# PR-150 structured durable paper runtime

This change adds a sender-free structured runtime wrapper around the existing
paper/shadow `run_once()` contract. It is intentionally a first durable slice of
PR-150 and does not claim live trading readiness.

## What this adds

- A single controller for bounded repeated paper cycles.
- A SQLite lifecycle store for durable transition evidence.
- A deterministic transition ID, attempt ID and outbox ID per cycle.
- A fail-closed timeout transition when the per-cycle deadline expires.
- A durable failed transition when the wrapped paper runtime raises.
- A small outbox table that can be connected to later dedup/delivery work.

## Safety boundaries

The runtime is sender-free by construction:

- `live_enabled` and `sender_enabled` default to `False`.
- Enabling either flag raises `StructuredPaperRuntimeError`.
- Lifecycle details reject keypair, private key, signature, signed transaction
  and txid fields.
- Runtime exceptions record only the exception type, not raw exception text.

## Non-goals

This PR does not submit transactions, import a sender, create a signer backend,
open RPC/Jito submission paths or claim a completed 72-hour soak. It also does
not claim that PR-147, PR-148 or PR-149 contracts are already integrated.

## Local checks

```bash
python -m pytest tests/test_pr150_structured_durable_runtime.py -q
python -m black --check src/paper_shadow/structured_runtime.py tests/test_pr150_structured_durable_runtime.py
python scripts/verify_repo.py
```
