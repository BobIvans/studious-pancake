# PR-045 — Permit-bound RPC/Jito submission and reconciliation

## Boundary

PR-045 introduces the first canonical submission transport boundary, but it does
not enable live trading. `LiveSubmissionPolicy` is compile-time and
configuration default-deny. A caller must explicitly construct an enabled
policy and obtain a one-use `SubmissionPermit`; no environment variable silently
opens the gate.

The public sender contract is:

```python
await sender.submit(permit, signed_payload, message_hash)
```

The permit binds one durable attempt to the exact PR-036 final-simulation hash,
all canonical message hashes, actual wire-transaction digests, deterministic
transaction signatures, transport, expiry, block-height validity, minimum
context slot, policy fingerprint and Jito tip evidence where applicable.

## Lifecycle invariants

1. Signed wire transactions are parsed and signature-verified with Solders.
2. Permit, final simulation, message bytes, transaction signatures and payload
   digest must describe the same payload.
3. PR-041 records submission intent before any transport call.
4. A successful `sendTransaction` or `sendBundle` response is only an
   `accepted` acknowledgement; it is never treated as landed or profitable.
5. Landing requires later signature or bundle-status evidence.
6. Timeout, malformed response, mismatched signature, unknown bundle state or
   conflicting status becomes ambiguous and forbids automatic resend.
7. A consumed permit cannot be reused. A failed/expired attempt requires a new
   permit and an explicit lifecycle decision.
8. RPC and Jito have fixed independent paths; there is no fallback from one
   sender to the other and no double-submit path.

## RPC policy

The RPC sender uses base64 `sendTransaction` with explicit
`skipPreflight`, `preflightCommitment`, `maxRetries` and `minContextSlot`.
Returned signatures must match the deterministic signature already present in
the signed wire transaction. `getSignatureStatuses` is used for later bounded
status observation.

## Jito policy

- single transaction: `/api/v1/transactions`, optionally with
  `bundleOnly=true`;
- bundle: `/api/v1/bundles`, one to five signed transactions;
- authentication: issued UUID in `x-jito-auth`, never printed in diagnostics;
- status: `getInflightBundleStatuses`, `getBundleStatuses`, plus Solana
  signature reconciliation;
- tip accounts: current `getTipAccounts` evidence only.

Exactly one approved System Program tip transfer must exist across the entire
payload. Two tips in one transaction or one tip in each of two bundle
transactions both fail before durable intent or network submission.

## State classification

The transport/reconciliation surface exposes `accepted`, `landed`, `failed`,
`expired` and `unknown`.

- `accepted`: acknowledgement/pending evidence only;
- `landed`: confirmed/finalized signature or landed Jito evidence;
- `failed`: deterministic on-chain signature error;
- `expired`: no signature and block height exceeded;
- `unknown`: missing, contradictory, malformed or transport-ambiguous evidence.

Jito `Failed`/`Invalid` alone remains `unknown` until signature reconciliation;
it does not authorize a resend.

## Parallel integration

This PR is isolated under `src/submission`. It does not modify the legacy
`src/execution/live_gate.py` or `src/execution/lifecycle.py`, nor does it copy
open PR-038, PR-040, PR-042 or PR-043 files. The durable adapter consumes the
already-merged PR-041 API and the permit binds the already-merged PR-036 exact
simulation hash.

PR-046 remains responsible for operator enablement, canary exposure caps,
safety latches and actual controlled live admission. Until that work and the
remaining PR-045 dependencies are reviewed, the supported runtime remains
non-live.

## Official contracts used

- Solana `sendTransaction`:
  https://solana.com/docs/rpc/http/sendtransaction
- Solana `getSignatureStatuses`:
  https://solana.com/docs/rpc/http/getsignaturestatuses
- Jito low-latency transaction send, bundles, UUID authentication, tip accounts
  and bundle status APIs:
  https://docs.jito.wtf/lowlatencytxnsend/

Sanitized endpoint/shape metadata is pinned in
`tests/fixtures/pr045/official_transport_shapes.json`.

## Verification

```bash
python -m pytest tests/test_pr045_permit_bound_submission.py -q --disable-socket
python -m black --check src/submission tests/test_pr045_permit_bound_submission.py
python -m mypy --config-file mypy.ini src/submission
python -m compileall -q src/submission tests/test_pr045_permit_bound_submission.py
python scripts/verify_repo.py
```
