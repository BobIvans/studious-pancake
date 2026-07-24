# MPR-40 start — Deterministic Runtime Integrity, Trusted Time and Secure Inputs

This branch starts the MPR-40 review thread from the master production-ready audit.

## Scope

MPR-40 is focused on making active runtime state transitions deterministic, finite, bounded, supervised, and derived from one trusted time/file/config authority.

This start slice is intentionally documentation-only. It creates the isolated branch and review surface for the implementation work without claiming that the full runtime integrity cutover is complete.

## Target implementation areas

1. Queue expiry and identity release
   - Expired queue entries must atomically leave the queue and release or terminalize pending identity.
   - Synchronous mutation paths must not bypass async condition ownership.
   - Pending and terminal identity state must be bounded by TTL/capacity/compaction policy.

2. Duplicate identity semantics
   - Distinguish provider delivery, opportunity observation, deterministic route, execution attempt, and settlement transaction.
   - Do not use one identifier for every lifecycle meaning.

3. Structured supervision
   - Detector, consumer, database writer and other critical background tasks must be owned by named supervisors.
   - Unexpected task death must persist a fault event, close readiness and either restart within policy or fail the process.

4. Shutdown and restart determinism
   - Stop intake first.
   - Drain or explicitly abandon bounded work.
   - Flush durable state, outbox, logs and metrics.
   - Release reservations safely.
   - Persist runtime generation termination.

5. Strict economic/runtime numerics
   - Reject fractional atomic values.
   - Reject NaN, Infinity and out-of-range numerics.
   - Require valid nonnegative integer slots/heights.

6. Trusted time authority
   - Business decisions must use injected trusted time: monotonic elapsed time, trusted wall time, generation epoch, skew policy and test-controlled clock.
   - Direct wall-clock decisions must be removed from active expiry, authorization and settlement paths.

7. Freshness and rooted context
   - Route freshness must use actual trusted now, not the newest timestamp inside a stale batch.
   - Executable quotes must have finite validity policy and rooted/min-context slot agreement.

8. Secure input/file/config authority
   - Recording, config activation, YAML/manifests and evidence files must use single-open no-follow secure reads.
   - File identity must include owner, mode, inode/device consistency, size cap, regular-file type and digest from the same opened descriptor.
   - Production config activation must require external operator authorization material, monotonic generation, expiry bounds, rollback prevention and durable activation receipt.

9. Dynamic invariant probes
   - Replace declaration-only booleans with tests that instantiate the real queue, tracker, runtime, trusted clock, loaders and config activation paths.

## Safety boundary

This PR must not:

- enable live trading;
- enable private-key loading;
- enable signer IPC;
- enable transaction submission;
- enable Jito submission;
- claim paper-ready, shadow-qualified, live-ready or production-ready status.

## Expected acceptance direction

The full implementation should satisfy these outcomes:

- expired queue entries never remain permanently pending;
- dedupe stores remain bounded under long-running fuzz/property tests;
- detector/consumer failure immediately closes readiness;
- economic/runtime models reject floats, NaN, Infinity and negative slots;
- stale quote batches cannot self-certify freshness;
- security-sensitive file reads use one opened descriptor;
- production config activation requires external authorization;
- shutdown/restart creates one consistent runtime generation boundary.

## Suggested verification commands

```bash
python -m compileall -q src scripts tests isolated_signer_service/src
pytest -q tests -k "queue or tracker or lifecycle or supervision or trusted_time or finite or secure_file or config_generation"
pytest -q tests/property tests/fuzz
```

## Parallel-work hygiene

- Branch is created directly from `main`.
- This is an isolated start thread for MPR-40.
- It should remain reviewable independently from MPR-39 and later MPR-41..46 work.
