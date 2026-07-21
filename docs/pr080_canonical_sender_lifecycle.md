# PR-080 — canonical permit-bound sender lifecycle integration

## Purpose

PR-080 is the final admission boundary between the durable lifecycle and the one
canonical permit-bound sender. It is intentionally offline and fail-closed in
this patch: the code validates the exact `sender.submit(permit, signed_payload,
message_hash)` invocation that a later runner may use, but it does not call the
sender, sign transactions, submit to RPC, submit to Jito, poll the network, or
open live mode.

The roadmap requirement is to integrate one canonical RPC/Jito sender with the
lifecycle/outbox while preserving these invariants:

- one sender protocol;
- RPC and Jito transports selected explicitly;
- default no-auth plus optional Jito UUID mode remains owned by the existing
  canonical sender settings;
- permit, signed payload, exact simulation hash and message hash must match;
- Jito submission requires bound exactly-one-tip evidence;
- transport ACK is not landing proof;
- status polling is the only source that may prove landing;
- unknown/ambiguous/restart states reconcile without same-payload resend;
- live submission remains closed unless both compile-time and config gates are
  explicitly enabled.

## What this patch adds

`src/submission/lifecycle_integration.py` adds:

- `CanonicalSenderLifecycleGate` — admission-only validator;
- `CanonicalSenderInvocation` — exact, typed, redacted invocation envelope;
- `CanonicalSenderAdmissionResult` — machine-readable status for CI/release
  gates;
- `classify_ack(...)` — blocks any fake ACK-as-landed transition;
- `classify_observation(...)` — lets status observations prove landing without
  enabling resubmission;
- `classify_restart(...)` — maps durable startup recovery to
  reconcile/no-resubmit for may-have-submitted attempts.

## Safety boundary

The module is side-effect free. It only consumes already-constructed objects:

- `DurableAttempt`;
- `CanonicalSenderSettings`;
- `CanonicalSubmissionStack`;
- `SubmissionPermit`;
- `SignedPayload`;
- `SubmissionAck` / `SubmissionObservation` / `RecoveryDecision`.

It does not import provider clients, Solana RPC clients, Jito clients, wallet
loaders, signing adapters or environment variables.

`PR080_LIVE_SENDER_COMPILE_TIME_ENABLED` is deliberately `False`. The test suite
uses an explicit opt-in constructor argument only to prove that the invocation
envelope contains exactly the existing sender, permit, signed payload and message
hash. The repository default remains live-closed.

## Failure policy

The gate returns `RECONCILE_NO_RESUBMIT` when a durable attempt may already have
submitted:

- `submission_intent_recorded`;
- `submission_uncertain`;
- `accepted`;
- `pending`;
- `landed`;
- `reconciling`;
- legacy `submitted`.

The gate refuses to build a sender invocation when:

- lifecycle state is not exactly `signed`;
- expected revision differs;
- permit attempt id differs from durable attempt id;
- exact simulation hash, message hash, permit hash or payload hash differ;
- selected transport differs across settings, stack and permit;
- endpoint fingerprint differs;
- duplicate submission or transport fallback is allowed;
- Jito transport lacks bound exactly-one-tip evidence;
- compile-time/config live gate is closed.

## Relationship to previous PRs

This patch builds on the existing PR-045/063 submission modules and the PR-041
durable lifecycle store. It does not duplicate sender classes and does not remove
legacy compatibility exports. PR-071 already added canonical execution-domain
ownership evidence; PR-080 adds the final admission envelope for using that
canonical sender from a lifecycle-aware runner.

## Suggested validation

```bash
python -m pytest tests/test_pr080_canonical_sender_lifecycle.py -q
python -m pytest tests/test_pr045_sender_workflow.py tests/test_pr063_status_consolidation.py -q
python -m black --check src/submission/lifecycle_integration.py tests/test_pr080_canonical_sender_lifecycle.py
python scripts/verify_repo.py --skip-dependency-audit
```

## Non-goals

- No live sending.
- No RPC/Jito network calls.
- No wallet/signing access.
- No automatic resend under ambiguity.
- No dependency on PR-079 artifacts being already reviewed.
- No broad namespace rewrite while parallel PRs are landing.
