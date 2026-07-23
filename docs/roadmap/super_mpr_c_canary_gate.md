# SUPER-MPR-C — Isolated Signer + Permit-Bound One-Transaction Canary Gate

This additive PR starts the SUPER-MPR-C acceptance boundary without enabling live
trading. The consolidated roadmap says SUPER-MPR-C must not be started as an
operational canary until SUPER-MPR-A and SUPER-MPR-B are complete, so this slice
keeps the canary dependency-gated and disabled by default.

## Added boundary

- `src/super_mpr_c_canary_gate.py`
- `tests/test_super_mpr_c_canary_gate.py`
- `.github/workflows/super-mpr-c-canary-gate.yml`

## Invariants covered

- SUPER-MPR-A and SUPER-MPR-B evidence is mandatory before canary availability.
- The signer is modeled as a separate process/service with a separate entrypoint,
  config digest, capability digest, artifact digest, namespace evidence and key
  backend policy.
- The signer must not perform provider discovery, route building, strategy logic
  or arbitrary message signing.
- Human approval is mandatory and binds runtime/config/capability artifacts,
  route/program allowance, expiry, max spend, max tip, max loss and exactly one
  transaction.
- A canary permit is single-use, expiry-bound and bound to final message,
  simulation, route, economic, account-meta, budget and approval digests.
- The permit is durably consumed before signing and remains consumed after a
  restart snapshot.
- The same message proof rejects any mutation after final simulation.
- Duplicate transaction, permit, opportunity and blockhash submission is blocked.
- Jito ACK, landed and bundle IDs remain transport evidence only; they cannot
  become economic settlement proof.
- Finalized transaction lookup plus finalized token/native balance deltas are the
  only settlement authority.
- Emergency kill conditions fail closed before signing.

## Safety boundary

This PR does not:

- enable live trading;
- load private keys;
- create a signer daemon;
- submit through RPC or Jito;
- call providers;
- claim SUPER-MPR-C is operationally complete;
- bypass the roadmap's SUPER-MPR-A/SUPER-MPR-B ordering rule.

## Suggested verification

```bash
python -m py_compile \
  src/super_mpr_c_canary_gate.py \
  tests/test_super_mpr_c_canary_gate.py
PYTHONPATH=. python -m pytest -q tests/test_super_mpr_c_canary_gate.py
```

## Follow-up work

After SUPER-MPR-A and SUPER-MPR-B are complete, a later operational slice should
wire this gate into the isolated signer service, durable permit store, approval
artifact source, canary submission guard and finalized settlement collector.
