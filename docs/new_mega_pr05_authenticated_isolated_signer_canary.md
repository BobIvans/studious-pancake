# NEW-MEGA-PR-05 — Authenticated Isolated Signer, Finalized Reconciliation and Bounded Live Canary

This slice starts the fifth residual mega-PR as an additive fail-closed boundary. It does not enable unrestricted live trading, does not load a private key in the runtime and does not submit transactions.

## Scope

The new boundary covers:

- authenticated two-person permits with issuer/reviewer signatures, key IDs and revocation checks;
- immutable permit identity for nonce, attempt, generation, wallet, market, asset, exact message hash, selected transport, tip, session, policy and evidence bundle;
- isolated signer semantics where the signer independently checks the exact final-simulated message bytes before producing signed-wire evidence;
- current blockheight consumption checks against `lastValidBlockHeight` with a safety margin;
- durable one-per-attempt-generation issue/consume semantics through SQLite uniqueness and CAS update rowcount;
- wire-derived tip evidence and immutable selected transport matching across permit, signed wire, intent and settlement;
- finalized settlement reconciliation that treats Jito ACK/bundle ID as transport evidence only;
- hard canary latches for count, notional, tip, daily loss, total loss, valid time window and second reviewer presence.

## Non-goals

This PR deliberately does not:

- expose a live runtime mode;
- integrate a real KMS/HSM or key file;
- submit through RPC or Jito;
- treat ACK, bundle ID, landed or unknown status as realized PnL;
- authorize blind resend when an outcome is missing or unknown;
- allow unrestricted live after canary.

## Verification

```bash
python -m compileall -q src scripts tests
python scripts/verify_new_mega_pr05_live_canary_boundary.py --strict --json
python -m pytest -q tests/test_new_mega_pr05_live_canary_boundary.py
```

## Follow-up integration

Later implementation slices can replace the deterministic HMAC stand-in with a real isolated signer/KMS/HSM backend and wire parser, then connect the durable permit authority to the canonical lifecycle/outbox store. The safety contract here is intentionally stricter than a live sender: every mismatch yields blocked/manual-review state and unrestricted live remains a separate governance decision.
