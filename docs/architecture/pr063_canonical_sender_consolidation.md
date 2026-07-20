# PR-063 — Canonical Jito/RPC sender consolidation

## Purpose

PR-063 completes the PR-045 sender work by making the sender selection itself a
single canonical composition boundary. The goal is not to enable live trading;
it is to prevent later composition roots from accidentally wiring duplicate
RPC/Jito APIs, fallback senders, or automatic replay of an ambiguous submitted
payload.

The remediation roadmap asks PR-063 to cover permit-bound sender usage, Jito
optional/default versus UUID credential modes, current endpoints, status polling,
exactly-one tip policy, durable ambiguity state and no automatic duplicate
submission.

## What this slice adds

`src.submission.canonical_sender` adds:

- one `CanonicalSenderSettings` object for exactly one selected transport;
- default-deny `LiveSubmissionPolicy` construction with one allowed transport;
- explicit Jito credential modes:
  - `no_auth`, the default public Block Engine mode;
  - `uuid`, which requires a UUID value and exposes only a redacted fingerprint;
- one `build_canonical_submission_stack()` factory that returns:
  - one permit-bound `Sender`;
  - its matching `LivePermitIssuer`;
  - one `SubmissionStatusClient`;
- route constants for the current reviewed Jito/Solana JSON-RPC status surface;
- durable follow-up decisions that never allow resubmitting the same payload.

## Endpoint and status contract

The reviewed canonical route set is:

| Purpose | Path or method |
| --- | --- |
| Solana signature reconciliation | `getSignatureStatuses` |
| Jito single transaction submission | `/api/v1/transactions` |
| Jito bundle submission | `/api/v1/bundles` |
| Jito inflight bundle status | `/api/v1/getInflightBundleStatuses` |
| Jito durable bundle status | `/api/v1/getBundleStatuses` |
| Jito tip accounts | `/api/v1/getTipAccounts` |

Jito routes use `https://mainnet.block-engine.jito.wtf` by default. UUID auth is
represented by `x-jito-auth` only inside the lower-level PR-045 sender; PR-063
stores a redacted UUID fingerprint in the manifest, never the UUID value.

## No duplicate submission rule

PR-063 intentionally does not add retry loops. After a submitted payload enters
accepted, landed or unknown/ambiguous state, the canonical follow-up action is
reconciliation without resend. A proven failed or expired observation can only
produce `reviewed_rebuild_new_permit`: a new message, new permit and operator
review path, not automatic reuse of the prior signed payload.

## Parallel-work compatibility

This patch is isolated from the currently open earlier roadmap PRs. It does not
modify active planner, capital, discovery, registry, MarginFi, paper-runner,
signer, canary or release-gate code. It layers on top of the existing PR-045
`src.submission` boundary and keeps live submission default-disabled.

## Verification

Focused checks:

```bash
python -m pytest tests/test_pr063_canonical_sender_consolidation.py -q
python -m compileall -q src/submission/canonical_sender.py tests/test_pr063_canonical_sender_consolidation.py
```

Full repository gate remains:

```bash
python scripts/verify_repo.py
```
