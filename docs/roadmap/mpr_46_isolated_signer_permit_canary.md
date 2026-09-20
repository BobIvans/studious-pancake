# MPR-46 — Isolated Signer and Permit-Bound One-Transaction Canary

This PR starts the MPR-46 safety boundary from the master production-ready closure pack.

## Objective

Add an offline, reviewable policy gate for a future physically isolated signer and a permit-bound one-transaction canary. This PR does **not** deploy a signer, load keys, sign messages, submit transactions, enable Jito, enable live trading, or mark the product production-ready.

## Implemented in this PR

- `src/mpr46_isolated_signer_canary.py`: sender-free/signature-free policy engine.
- `src/resources/mpr46_permit_canary_policy.json`: default fail-closed policy/evidence document.
- `scripts/verify_mpr46_isolated_signer_canary.py`: CLI verifier that prints deterministic JSON and fails if live/signature capability appears.
- `tests/test_mpr46_isolated_signer_canary.py`: regression tests for canary eligibility, exact-message binding, consumed permits, budget ceilings, dangerous live/signer flags, and single-transaction latch enforcement.
- `.github/workflows/mpr-46-isolated-signer-permit-canary.yml`: focused CI check with pinned actions and read-only permissions.

## Safety boundary

The gate is intentionally fail-closed by default. A fully accepted request means only that an offline policy layer considers exact bytes eligible to be handed to a separate signer implementation in a future promotion step.

The gate never:

- reads private keys;
- opens network sockets;
- builds transactions;
- submits transactions;
- treats Jito as settlement authority;
- returns signature material;
- enables unrestricted live trading.

## Required MPR-46 preconditions

The policy refuses canary eligibility unless all of the following are present as explicit evidence fields:

- `PAPER_QUALIFIED` evidence complete;
- provider/protocol binaries and contracts attested;
- exact transaction and finalized settlement authority operational;
- deployment and supply-chain controls passed;
- backup/restore and incident runbooks approved;
- human release authority signed a canary-eligibility artifact.

## Signer-boundary invariants

The policy requires a separate signer artifact, no arbitrary signer egress, no signer provider/RPC access, authenticated IPC, external key backend, durable single-use permit store, signer-side independent policy checks, signed receipts, independent kill switch, and monotonic anti-rollback state.

## Permit-bound one-transaction latch

The only positive path is `ONE_TX_PERMIT_ELIGIBLE`, and only for one exact serialized message digest that matches final simulation and reservation evidence. Even then, this PR still does not sign or submit anything.

## Local verification

```bash
python -m py_compile \
  src/mpr46_isolated_signer_canary.py \
  scripts/verify_mpr46_isolated_signer_canary.py \
  tests/test_mpr46_isolated_signer_canary.py
python -m pytest -q tests/test_mpr46_isolated_signer_canary.py
python scripts/verify_mpr46_isolated_signer_canary.py --json
```
