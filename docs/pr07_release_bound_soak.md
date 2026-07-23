# PR-07 — release-bound 72-hour sender-free soak

## Purpose

PR-07 turns the existing D2 release/soak descriptor into an executable evidence
boundary. It does **not** claim that a 72-hour run already occurred. A positive
verdict is possible only from a complete cryptographically verified checkpoint
chain produced by one pinned installed wheel and hardened image.

The run identity binds:

- exact source commit and release digest;
- wheel SHA-256 and image digest;
- PolicyBundle SHA-256;
- admitted provider-evidence SHA-256 and cluster genesis;
- environment, start time and run ID;
- the fixed `installed-wheel+hardened-image` runtime surface.

## Signed checkpoints

Every checkpoint contains cumulative provider, paper-cycle, terminal, retry,
duplicate, dead-letter, reservation, reconciliation and data-gap counters. It
also records memory, descriptors, tasks, queue depth and event-loop lag.

The checkpoint payload is signed through the PR-183 evidence trust-anchor
registry under domain `studious-pancake.pr07.soak-checkpoint`. Hash-shaped
references are not accepted as signatures. Each checkpoint binds the previous
checkpoint hash, so deletion, reordering, replacement and cross-run reuse fail
closed.

`SQLiteSoakCheckpointStore` is an append-only evidence store. It is deliberately
not a lifecycle, reservation or capital authority. Exact replay returns the
existing record; changed payload under the same sequence is an immutability
conflict. Reopening the store resumes the same run identity and chain.

## Required interruption and recovery evidence

The final checkpoint must include content-addressed evidence for all of:

1. restart;
2. process kill;
3. cancellation;
4. provider outage;
5. provider quorum loss;
6. RPC drift;
7. stale root;
8. database lock;
9. disk pressure;
10. partial write;
11. alert acknowledgement;
12. backup and restore;
13. rollback.

No boolean alone proves a drill. Each accepted drill is paired with a non-zero
SHA-256 reference, and prior drill evidence cannot disappear or change later in
the checkpoint chain.

## Fail-closed final verdict

`ready-for-review` requires:

- at least 72 hours between the pinned run start and final signed checkpoint;
- every checkpoint signature accepted for `TrustUsage.EVIDENCE`;
- uninterrupted sequence and hash-chain continuity;
- real admitted provider events and completed sender-free paper cycles;
- terminal outcomes present;
- zero reservation leaks, duplicate capital use, unresolved outcomes and data
  gaps;
- zero signer/sender reachability, signatures and submissions;
- zero fixture/synthetic rows;
- all recovery drills and resource-stability evidence;
- live remaining disabled.

The final report includes a D2-compatible soak evidence projection. The existing
D2 bundler must still hash the actual wheel, image, SBOM, provenance, checkpoint
artifacts and other materialized files. PR-05 remains responsible for independent
release qualification and PR-06 for management-plane/external-audit surfacing.

## Command

```bash
python scripts/pr07_soak_verify.py inspect --manifest pr07-manifest.json
python scripts/pr07_soak_verify.py check --manifest pr07-manifest.json
```

`inspect` reports a blocked result with exit code 0. `check` returns exit code 3
unless the complete release-bound soak is ready for independent review. Invalid
input returns exit code 2 with a stable redacted reason code.

## Current integration boundary

Roadmap PR-02, PR-03 and PR-04 must supply the canonical lifecycle authority,
real rooted provider admission and repeated installed paper service. Until those
branches are merged and a protected environment actually runs the pinned
candidate for 72 hours, this PR must remain blocked and cannot authorize PR-08,
live trading, signing or submission.
