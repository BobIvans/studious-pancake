# PR-224 — Deployed-State Operations and Cutover Evidence Gate

This is a continuation of the roadmap PR-224 production platform, operations and verifiable cutover boundary.

The already-merged PR-224 gate created a first side-effect-free production platform contract. This slice adds a stricter target-host deployed-state evidence contract that can be consumed by later cutover tooling without enabling live execution.

## Scope

`src/pr224_deployed_state_operations_gate.py` validates materialized evidence for:

- exact runtime/signer release identity and validator binary digest;
- separate runtime and signer images/users;
- deny-by-default network policy, egress gateway enforcement and signer egress denial;
- DNS/private-IP/redirect escape denial bound to the provider generation;
- measured seccomp/AppArmor traces over SQLite WAL and archive operations;
- read-only rootfs, minimal capabilities and no-new-privileges;
- authenticated management API and signed readiness snapshots;
- anti-false-green readiness for empty, blocked, dead-worker, stale-provider, signer-unavailable and recovery-blocked states;
- materialized SLO, shutdown, backup/restore and rollback reports;
- RPO/RTO budget enforcement and split-brain prevention;
- exact upstream acceptance of PR-219 through PR-223 before PR-224 cutover review;
- tiny-canary autostop, finalized-settlement requirement and rollback reconciliation continuity.

## Safety boundary

This module is intentionally offline and side-effect-free. It does not:

- build or publish OCI images;
- start containers;
- inspect the target host;
- open sockets;
- read secrets or private keys;
- call RPC, Jito, Jupiter, MarginFi or other providers;
- sign transactions;
- submit transactions;
- enable signer, sender or live execution.

A passing report still returns:

```text
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
```

The only positive state is:

```text
ready-for-target-host-cutover-review
```

That state means the uploaded evidence bundle is internally coherent enough for human and automated PR-224 cutover review. It is not permission to deploy, trade, sign or submit.

## Roadmap mapping

This slice maps to roadmap PR-224, which owns production platform, operations and verifiable cutover. The roadmap assigns PR-224 the final infrastructure boundary after PR-219 through PR-223 and covers F-038…F-039, F-137…F-142, F-199…F-208, F-256…F-260, F-303…F-306, F-308 and F-409.

## Focused verification

```bash
python -m compileall -q \
  src/pr224_deployed_state_operations_gate.py \
  tests/test_pr224_deployed_state_operations_gate.py

PYTHONPATH=. python -m pytest -q \
  tests/test_pr224_deployed_state_operations_gate.py
```

The focused suite covers:

1. a passing deployed-state evidence bundle;
2. missing finding coverage;
3. collapsed runtime/signer release identity;
4. incomplete network/egress denial;
5. incomplete sandbox and `/tmp` writable evidence;
6. false-green readiness regressions;
7. RPO/RTO and materialized drill failures;
8. incomplete upstream gates;
9. unrestricted live/signer/sender requests;
10. placeholder digest rejection.

## Remaining physical PR-224 cutover work

This is an evidence contract, not the physical infrastructure cutover. Remaining work still includes:

- generating these reports from the actual target host;
- wiring release-set identity to signed image/SBOM/provenance outputs;
- executing real seccomp/AppArmor/WAL/archive traces;
- proving deny-by-default egress with the actual gateway;
- running SLO, shutdown, backup/restore and rollback drills on target infrastructure;
- connecting readiness to the authenticated management API;
- consuming accepted PR-219…PR-223 evidence bundles;
- allowing at most one tiny canary only after finalized-settlement governance is satisfied.
