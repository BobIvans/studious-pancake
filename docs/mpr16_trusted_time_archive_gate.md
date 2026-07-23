# MPR-16 trusted time, anti-replay management and immutable archive gate

This slice implements an additive, side-effect-free acceptance gate for V7
**MPR-16 — Trusted time, anti-replay management and immutable archive**.

## Boundary

The gate is intentionally not the full operational cutover. It does not contact
host time services, archive backends, management HTTP planes, RPC providers,
signers, senders, wallets or live deployment tooling. It defines the evidence
contract that later MPR-16 implementation work must satisfy.

A passing report still hard-codes:

```text
transaction_signer_allowed=false
sender_allowed=false
live_execution_allowed=false
```

## Covered findings

The validator maps V7 MPR-16 findings F-350 through F-360 into deterministic
blockers:

- first startup time sample cannot authorize sensitive expiry decisions;
- time status must come from authenticated host-timesync evidence;
- every process incarnation requires a strictly increasing durable generation;
- signed management snapshots must advance durable anti-replay high-water state;
- readiness must be cross-bound to release, runtime generation, policy and
  evidence head;
- archive leases must be renewable, CAS-heartbeated and fence-validated before
  row read, artifact write and commit;
- stale exporters must be rejected before writing orphan artifacts;
- remote archive acknowledgements must be append-only and immutable;
- mandatory WORM archive receipts must satisfy policy quorum;
- local committed state and remotely durable authoritative state must remain
  separate and deterministic.

## Acceptance added by this PR

- `src/mpr16_trusted_time_archive_gate.py` defines the immutable evidence model
  and deterministic report.
- `tests/test_mpr16_trusted_time_archive_gate.py` covers the happy path and
  fail-closed blockers from the audit.

## Non-goals

This PR does not enable live trading, signing, sender submission, provider calls,
archive uploads, management server replacement, deployment changes, dependency
changes or production database migrations. It is a reviewable safety contract for
the later operational cutover.
