# MPR-30 — Cryptographic signer, one-shot permit, submission FSM and rooted settlement

## Status

This branch starts **MPR-30** from the V11 production-readiness roadmap as a safe
additive slice. It does **not** enable signer access, sender I/O, Jito/RPC
submission or live execution. The implementation is an offline acceptance
contract that defines what must be proven before a later MPR-30 cutover can wire
real signer/submission runtime paths.

## Why this slice exists

The roadmap assigns MPR-30 to the default-off live boundary between:

- exact byte-derived transaction identity;
- cryptographic reviewed permits;
- one-shot permit consume + immutable submission intent;
- Jito bundle identity and reviewed membership;
- monotonic submission FSM and staged transport evidence;
- independent absence/rebuild proof;
- rooted finalized settlement.

Current repository history already contains partial signer/finality proof layers,
but they do not by themselves establish the full MPR-30 default-off boundary.
This slice makes those requirements explicit and testable without introducing any
side effect.

## Added files

- `src/mpr30_signer_submission_settlement_gate.py`
- `tests/test_mpr30_signer_submission_settlement_gate.py`
- `docs/mpr30_cryptographic_signer_submission_settlement.md`
- `.github/workflows/mpr30-cryptographic-signer.yml`

## What the gate requires

The evaluator blocks unless evidence proves all of the following:

1. **Byte identity is signer-owned**
   - signer derives programs/accounts/signers/ALTs from exact bytes;
   - caller metadata is not trusted.

2. **Permit is cryptographic**
   - canonical signed envelope;
   - exact message binding;
   - release/config/policy generation binding;
   - reviewer identity and risk-limit binding;
   - nonce, revocation and TTL enforcement.

3. **Intent is one-shot**
   - permit issue/consume and immutable intent are one atomic boundary;
   - sender receives only opaque committed intent ID;
   - exact signed bytes stay attached to intent identity.

4. **Bundle and transport are causal**
   - Jito bundle identity covers every ordered member;
   - every member is reviewed;
   - transport materializes staged evidence;
   - ambiguous retry is allowed only after body-write evidence.

5. **FSM and settlement are rooted**
   - FSM is monotonic and terminal states are immutable;
   - stale/lower-finality observations are advisory only;
   - settlement requires rooted finalized evidence;
   - caller booleans or hashes cannot finalize economic truth.

6. **Live remains default-off**
   - signer, sender and live execution remain disabled by default.

## Safety boundary

A passing report still returns:

```text
signer_allowed=false
sender_allowed=false
live_execution_allowed=false
```

So this branch is a foundation slice, not an activation slice.

## Focused verification

```bash
python -m py_compile \
  src/mpr30_signer_submission_settlement_gate.py \
  tests/test_mpr30_signer_submission_settlement_gate.py
python -m pytest -q tests/test_mpr30_signer_submission_settlement_gate.py
```

## Not included yet

This slice intentionally does not:

- load or export private keys;
- start a signer process;
- open signer IPC in the runtime path;
- call RPC or Jito;
- sign or submit transactions;
- reconcile real finalized settlement;
- enable any live capability.
