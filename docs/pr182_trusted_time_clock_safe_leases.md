# PR-182 — Trusted time authority, boot identity and clock-safe leases

## Mission

Remove wall-clock correctness from active durable ownership and create one
runtime-owned time boundary for audit UTC, same-boot monotonic deadlines,
persisted expiry, signer permits and future readiness/live-control integration.

The reproduced defect was that `DurableLifecycleStore` compared a persisted
lease expiry with `time.time_ns()`. Moving wall time backwards therefore made an
existing lease appear live for longer. This PR changes the public
`src.durability.DurableLifecycleStore` used by capital/exact-attempt code to a
clock-safe subclass of the existing PR-041 lifecycle store.

## Active integration

### `src/time_authority.py`

Adds:

- `TimeSnapshot` with UTC, monotonic time, boot ID, process generation, source
  status, uncertainty and optional chain slot/root;
- explicit `MonotonicDeadline` and `PersistedExpiry` domains;
- `SystemTimeAuthority` with UTC rollback, forward-step and monotonic rollback
  detection;
- conservative process-scoped boot-domain fallback when the OS does not expose
  a stable boot UUID;
- fail-closed sensitive-operation checks for unsynchronized or anomalous time.

### `src/durability/trusted_time_store.py`

Keeps the existing PR-041 SQLite lifecycle/state machine as the only lifecycle
truth, but changes ownership correctness:

- lease acquisition and verification use boot-bound monotonic expiry;
- fencing tokens advance on every ownership generation;
- old-boot monotonic leases are invalidated and recorded as incidents;
- legacy leases without boot identity cannot be taken by a different owner;
- outbox claim expiry uses a boot-bound monotonic side table;
- legacy UTC expiry columns remain audit/compatibility upper bounds only;
- time anomalies create durable incident rows;
- live permit issuance remains false unless time is synchronized and there are
  no recorded incidents.

`src.durability.DurableLifecycleStore` now points to this clock-safe subclass.
`LegacyDurableLifecycleStore` remains explicitly named for migration/testing and
must not become a second runtime authority.

### `src/security/signer_policy.py`

Signer policy can now receive the same `TimeAuthority` and issue permits bound
to:

- boot ID;
- process generation;
- monotonic issue/expiry;
- durable UTC expiry.

A permit created without a `TimeAuthority` is marked `clock_safe=false` and
cannot pass `assert_permit_current()` for a trusted signer path. No signing or
key access is added.

## Safety invariants

```text
live_enabled = false
wall_clock_controls_lease_liveness = false
cross_boot_monotonic_comparison = forbidden
legacy_signer_permit_live_eligible = false
sender_or_submission_added = false
```

## Tests

`tests/test_pr182_trusted_time.py` covers:

- reproduced wall-clock rollback;
- excessive forward wall-clock step;
- boot-ID change and fencing-token advance;
- cross-boot lease rejection;
- outbox claim expiry with frozen UTC and advancing monotonic time;
- persisted permit invalidation after reboot;
- cross-boot deadline comparison rejection;
- unsynchronized clock blocking signer permit issuance;
- monotonic signer-permit expiry;
- legacy signer permit remaining non-promotable.

Suggested verification:

```bash
python -m pytest tests/test_pr182_trusted_time.py -q
python -m compileall -q src tests
python scripts/verify_repo.py --skip-dependency-audit
```

## Non-goals and remaining PR-182 work

- No live enablement.
- No sender, Jito or RPC submission.
- No NTP daemon management from Python.
- No automatic cross-host ownership transfer; the SQLite topology remains
  single-node.
- Existing `src/execution/live_control.py` wall-time confirmation/permit tables
  remain blocked for live use until a later integration consumes
  `PersistedExpiry` and boot identity.
- Release/evidence expiry and management-plane readiness still need the same
  TimeAuthority wired as active consumers.

This PR closes the active durable-lease defect and establishes the single time
contract those remaining consumers must use; it does not claim all PR-182
acceptance items are complete.
