# Roadmap PR-08 — Isolated signer and durable submission foundation

## Status

This is a **draft, fail-closed foundation**, not active submission. Numeric roadmap
PR-08 may not be activated until PR-01 through PR-07 are independently accepted.
The compile-time submission constant remains `False` and the package contains no
private-key loader or concrete RPC/Jito transport implementation.

## Package boundary

The isolated package lives under `isolated_signer_service/` and is built with its
own `pyproject.toml`. The root paper/runtime wheel discovers only `src*`, so it does
not package this signer distribution. Production source code under `src/` must not
import `flashloan_isolated_signer`.

## Implemented foundation

- exact release, PolicyBundle, attempt generation and message digest binding;
- all PR-01 through PR-07 approval evidence required with two reviewers;
- explicit payer, signer, program, writable-account, instruction, wire-size, spend,
  fee, priority-fee and same-message Jito-tip limits;
- one-time permit verifier port intended to consume the merged PR-201 replay authority;
- kill-switch and signer-revocation checks before durable intent creation;
- SQLite intent identity with exact idempotent retry and conflicting replay rejection;
- `prepared -> dispatched -> acknowledged|indeterminate` fenced transitions;
- no transition from an unknown outcome back to a resendable state;
- acknowledgement is only a transport receipt, never landing or economic success;
- status-only process entrypoint with no environment activation.

## Deliberately absent

- private key, seed phrase, keypair file, KMS/HSM or remote signer client;
- actual signature production or verification adapter;
- concrete RPC/Jito request implementation;
- blockhash/ALT network revalidation adapter;
- PR-09 finalized settlement and PnL classification;
- any live or canary activation.

A later reviewed PR must supply those adapters only after the roadmap prerequisites,
release qualification and real sender-free soak evidence are accepted.

## Verification

```bash
PYTHONPATH=isolated_signer_service/src \
  python -m pytest tests/test_roadmap_pr08_isolated_signer_foundation.py -q
python -m py_compile \
  isolated_signer_service/src/flashloan_isolated_signer/__init__.py \
  isolated_signer_service/src/flashloan_isolated_signer/models.py \
  isolated_signer_service/src/flashloan_isolated_signer/store.py \
  isolated_signer_service/src/flashloan_isolated_signer/boundary.py \
  isolated_signer_service/src/flashloan_isolated_signer/service.py \
  tests/test_roadmap_pr08_isolated_signer_foundation.py
python scripts/verify_repo.py
```

The isolated package sources and regression test are registered in the repository
Black manifest, so aggregate verification checks their exact formatter output.
