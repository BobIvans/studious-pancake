# PR-198 V3 — Continuous sender-free paper/shadow qualification gate

This document describes the revised V3 roadmap meaning of **PR-198**.

The V3 audit supersedes the earlier implementation grouping.  In this grouping,
PR-198 is not a live/signer package.  It is the installed-artifact sender-free
qualification layer that must run continuously after PR-195, PR-196 and PR-197
contracts are accepted.

## Scope

This slice adds an offline, deterministic evidence gate for:

- installed wheel and container cutover to one sender-free service;
- explicit use of PR-195 lifecycle durability, PR-196 provider/protocol contracts
  and PR-197 economic proof closure;
- continuous soak evidence instead of one-cycle or safe-idle readiness;
- durable input before ACK, bounded queues, deterministic drop policy and one
  terminal outcome per acknowledged input;
- deterministic replay of attempt IDs, decisions and reconciliation hashes;
- chaos qualification for queue pressure, provider outage, clock jump, DB lock,
  restart replay and SIGTERM drain;
- SLO envelope validation for event-loop lag, queue age, shutdown, memory, FDs
  and reconciliation latency;
- hard absence of live, signer and sender surfaces.

## Non-goals

This PR does **not** enable or implement:

- live trading;
- signer/private-key loading;
- RPC/Jito submission;
- provider calls;
- transaction construction;
- production DB migration;
- real 72-hour soak capture.

It only provides the typed acceptance contract that future real evidence must
satisfy.

## Why this is separate from older PR-198/PR-200 slices

There is an older open PR-198 branch for runtime supervision and an older open
PR-200 branch for continuous paper/shadow harness.  The V3 audit explicitly
re-groups the roadmap into eight packages and moves continuous sender-free
qualification into revised PR-198.

This branch is therefore additive and avoids shared files so it can be reviewed
without rewriting those older parallel branches.

## Verification

```bash
python -m py_compile \
  src/pr198_sender_free_qualification_v3.py \
  tests/test_pr198_sender_free_qualification_v3.py
python -m pytest -q tests/test_pr198_sender_free_qualification_v3.py
```

## Safety invariant

A clean `PR198V3QualificationReport` still returns:

```text
live_execution_allowed = false
signer_allowed = false
sender_import_allowed = false
```

Paper readiness is not claimed by source-tree tests or one-cycle runs.  It is
claimed only by accepted installed-artifact evidence that passes this gate and
then is reviewed with the exact merge commit, wheel, image, config and policy
hashes.
