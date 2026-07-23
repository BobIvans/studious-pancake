# PR-208 — Rooted Protocol and Provider Attestation

This slice starts the Pass 6 corrective package **PR-208**.

Pass 6 found that the previous protocol/account conformance surface can still be
self-attested: callers can provide booleans, paths and hashes without forcing the
verifier to bind those claims to rooted Solana account/program bytes, provider
identity, request/response bytes and the execution asset set.

This PR adds an offline, sender-free evidence gate that rejects that shape. It is
not a production RPC fetcher yet; it defines the typed contract that a real
fetcher must produce before protocol conformance can count as release evidence.

## What this gate requires

- A canonical execution asset set: required protocol accounts, programs, mints,
  Token-2022 mints, ATA accounts and the canonical wSOL mint.
- Rooted account/program evidence for every required asset.
- Materialized evidence refs with normalized paths, non-placeholder SHA-256,
  positive size, producer identity, slot and retention window.
- Same genesis, commitment and minContextSlot across account evidence and
  provider responses.
- Token-2022 mint evidence owned by the Token-2022 program and carrying
  materialized extension information.
- wSOL identity bound to the canonical SPL Token owner.
- Provider evidence that includes endpoint ID, credential scope, request hash,
  response hash, TLS peer fingerprint, response kind and bound addresses.
- No exported complete-claim helper, no caller-supplied boolean claims and no
  live/sender/signer capability.

## What this slice does not do

This PR does not fetch Solana RPC, call providers, construct transactions,
simulate, sign, send or make the bot paper/live-ready. The gate is an offline
contract and focused test suite only.

## Verification

```bash
python -m py_compile \
  src/pr208_rooted_protocol_provider_attestation.py \
  tests/test_pr208_rooted_protocol_provider_attestation.py
python -m pytest -q tests/test_pr208_rooted_protocol_provider_attestation.py
```

## Follow-up

The next PR-208 slice should replace hand-built evidence objects with a real
fetcher that materializes raw account/program/provider response bytes, re-hashes
files on disk, signs or attests the bundle, and wires the resulting artifact into
PR-209 exact atomic message semantics.
