# PR-148 — Market, MarginFi state and exact economic decision kernel

This PR adds a side-effect-free kernel for the snapshot-9 roadmap item
**PR-148 — Market, MarginFi state and exact economic decision kernel**.

## Scope

The kernel evaluates explicit evidence and returns exactly one of:

```text
EXACT_CANDIDATE
NO_TRADE
BLOCKED
```

It is intentionally not a compiler, simulator, signer, sender, RPC client, or
provider client. The module is a reusable admission contract for later runtime
integration.

## What this patch adds

- `src/market_economics_pr148.py`
  - exact two-leg route evidence;
  - deterministic logical opportunity ID;
  - provider request/response/expiry hashes;
  - route program identities;
  - coherent reviewed MarginFi evidence requirements;
  - asset/mint/Token-2022/LST policy checks;
  - integer-only exact cost ledger;
  - flash fee counted exactly once;
  - no float monetary values;
  - ATA/wSOL/rent and own-SOL reservation checks;
  - duplicate/cooldown admission guard;
  - domain-separated evidence/report hashes.

- `tests/test_pr148_market_economics_kernel.py`
  - exact candidate happy path;
  - second-leg exact amount binding;
  - linear projection rejection;
  - route-program identity requirement;
  - expiry and mixed-slot rejection;
  - MarginFi review/capability checks;
  - Token-2022, LST and mint attestation checks;
  - flash fee and wallet/rent reservation checks;
  - no-trade low-profit classification;
  - deterministic logical ID checks;
  - duplicate/cooldown rejection;
  - binary float evidence rejection.

## Safety boundary

- No live trading.
- No transaction compilation.
- No signing.
- No transaction submission.
- No RPC, Jito, Helius, MarginFi, Jupiter, OKX, Odos or OpenOcean network call.
- No private key loading.
- No active runtime rewiring in this slice.

## Follow-up integration

Later PR-148 work can connect this kernel to real provider quote evidence,
complete MarginFi IDL/SDK/RPC artifacts, durable dedup/cooldown storage, active
capital reservations and exact runtime candidate lifecycle.
