# PR-195 — Canonical Control Plane and Durable Lifecycle

This slice implements the first sender-free cutover foundation for the new
consolidated roadmap PR-195. It does not replace every legacy store yet and it
does not enable live trading. It creates an independently testable control-plane
authority that later commits can wire into the composition root.

## Why this exists

The audit identifies PR-195 as the durable lifecycle cutover: schema migrations,
trusted time, legal state transitions, config generation binding, permits,
latches, reservations, outbox and recovery must become one transactionally
consistent source of truth.

The existing repository already contains several good review-era components, but
they are not one active authority. This PR adds a canonical PR-195 kernel with
hard safety boundaries before any signer or sender path exists.

## Implemented in this slice

`src/canonical_control_plane_pr195.py` adds:

- forward-only SQLite migrations with a PR-195 target version;
- startup refusal when the database advertises a future unsupported version;
- backup-before-migrate manifest for non-empty on-disk databases;
- schema fingerprint evidence over the actual SQLite objects;
- active config-generation binding before attempts can be created;
- boot/process-generation fences for transition ownership;
- append-only attempt events with unique idempotency keys and unique revisions;
- exact-revision state transitions protected by `BEGIN IMMEDIATE`;
- state-machine enforcement that blocks direct jumps to submission intent;
- event-chain reconstruction checks for current-row consistency;
- exact latch identity/approval clearing rather than broad latch clearing;
- fatal unknown `FLASHLOAN_*` key detection in production mode;
- explicit `live_capability_allowed() == False`.

## Deliberate non-goals

- No signer process.
- No key material or private-key access.
- No transaction build, signing, simulation or submission.
- No automatic live/canary activation.
- No migration of existing production operator databases in this slice.
- No dynamic monkeypatching of legacy modules.

## Focused verification

```bash
python -m pytest \
  tests/test_pr195_canonical_control_plane.py \
  -q --disable-socket --allow-unix-socket
```

The tests cover:

- backup-before-migrate and schema fingerprinting;
- unknown future schema refusal;
- stale revision conflict without event insertion;
- idempotent transition replay;
- state-machine bypass rejection;
- current-row reconstruction from event history;
- boot-domain fence invalidation;
- unknown environment key fatality in production;
- exact latch clear with approval evidence.

## Cutover path after this slice

A later PR-195 commit can wire this kernel behind the active composition root,
then migrate or adapt the older `lifecycle`, `trusted_time_store`,
`execution.journal`, `live_control`, paper-shadow and PR-191/PR-193 surfaces
through one public API. Until that happens, this module is an explicit PR-195
authority candidate and regression boundary, not a hidden dual-writer.
