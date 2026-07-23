# MPR-22 provider, routing and quote integrity gate

This slice starts **MPR-22 — Authenticated rooted provider, routing and quote
integrity plane** with a narrow, additive review gate.

It does not implement network transport or live provider execution. Instead it
defines the fail-closed evidence contract that later MPR-22 cutover work must
satisfy before provider input may be treated as executable truth.

## Scope

- require all MPR-22 findings F-304…F-313 and F-420…F-429 to be explicitly
  closed;
- require one admitted provider transport with bounded responses and hardened
  JSON parsing;
- require absolute end-to-end deadline enforcement instead of per-retry timeout
  drift;
- require DNS rebinding protection, TLS peer pinning, private-IP denial and
  redirect revalidation;
- require request-bound quote provenance, explicit quote expiry and preserved
  request policy;
- require cross-process quota/circuit authority with request-bound reservation
  and exactly-once usage accounting;
- keep live, signer and sender surfaces disabled.

## Non-goals

This PR does **not**:

- call Jupiter, RPC, Helius or any external network;
- mutate live provider registries or credential stores;
- introduce sender, signer or submission capability;
- replace the active routing stack.

## Verification

```bash
python -m py_compile \
  src/mpr22_provider_quote_integrity_gate.py \
  tests/test_mpr22_provider_quote_integrity_gate.py
python -m pytest -q tests/test_mpr22_provider_quote_integrity_gate.py
```

A passing report still returns:

```text
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
```
