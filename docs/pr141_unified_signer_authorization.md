# PR-141 — Unified isolated signer and cryptographic transaction authorization

This PR starts the third-audit PR-141 signer boundary as a low-conflict,
side-effect-free authorization envelope. The roadmap requires the future signer
boundary to derive signer-critical identity from the exact serialized message
and bind that identity to plan, policy, simulation, fee and blockhash evidence
before any key backend is asked to sign.

## Implemented slice

- Adds `src/signer_authorization_pr141.py` as a pure-Python PR-141 gate.
- Introduces `DecodedUnsignedMessage`, the redacted identity that a later
  message parser must derive from bytes.
- Introduces `SignerAuthorizationRequest` and `TransactionAuthorization`.
- Requires v0 message identity.
- Requires payer and signer-set agreement with decoded message evidence.
- Requires all critical authorization hashes to be 64-character SHA-256 hex
  bindings.
- Treats the Solana `1232` byte limit as a full signed transaction ceiling by
  estimating signature vector bytes plus message bytes.
- Rejects decoded program IDs outside the explicit allowlist.
- Rejects ALT usage unless resolved-account evidence hash is already bound.
- Emits a deterministic, domain-separated authorization envelope hash.
- Keeps `live_submission_allowed` false.

## Why this is fail-closed

The gate does not trust a caller-provided program list as proof that the message
is safe. It consumes the decoded signer-critical identity and rejects mismatches,
missing evidence hashes, bad expiry, bad nonce, legacy versions and oversized
full signed wire payloads. It does not sign and does not load key material.

## Safety / non-goals

- No live sender enablement.
- No network process private-key loading.
- No RPC, Jito, MarginFi or Jupiter call.
- No isolated signer service process yet.
- No durable authorization store yet.
- No active signer-policy rewiring in this slice.
- No ALT resolution implementation; the gate requires the resulting evidence
  hash when ALT usage is present.

## Follow-up required for full PR-141

The remaining PR-141 work should wire this envelope to the compiler, actual
message decoding, durable authorization state machine, isolated signer backends,
signed response verification and submission-intent lifecycle. It should also
remove or quarantine incompatible permit families once the unified authorization
envelope is complete.
