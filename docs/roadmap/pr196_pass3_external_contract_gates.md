# PR-196 pass-3 external contract gates

This follow-up slice keeps PR-196 sender-free and adds fail-closed evidence gates for the pass-3 audit findings around external protocol conformance, rooted data and provider safety.

## Scope

- DNS/redirect evidence is validated before connect using materialized public-IP pins.
- Provider freshness uses trusted receive time and rejects future-dated provider timestamps.
- Provider request reservations are checked against one shared cycle budget instead of a process-local limiter snapshot.
- Retry policy is typed by operation class: safe reads and idempotent build calls require bounded retry semantics with full jitter, while send-like operations are non-retryable.
- SPL mint evidence defaults to fail-closed for Token-2022 owners or extensions until explicit semantic and economic support exists.

## Safety boundary

This module does not open sockets, resolve DNS, call providers, use wallets, sign, submit, or enable live trading. It validates already-materialized evidence so later PR-198 runtime wiring can prove the active path without giving this PR a sender surface.

## Focused verification

```bash
python -m pytest -q tests/test_pr196_external_contract_gates.py
python -m py_compile src/external_contract_gates_pr196.py tests/test_pr196_external_contract_gates.py
```

## Remaining PR-196 work

This is not a full credentialed conformance completion claim. The next slices still need signed provider-registry generation, real protected read-only probes, on-chain ALT/programdata validation, durable Helius inbox integration with the PR-195 lifecycle authority and credentialed drift artifacts.
