# PR-166 — Progressive release controller and rollback/downgrade safety

This PR adds a side-effect-free release-controller primitive for the
production-readiness PR-166 scope.

## Why this exists

The audit separates release evidence from release control. A release gate can
say that a manifest looks valid, but it does not prove which image, config,
PolicyBundle, database schema, signer generation and deployment profile are
actually running, and it does not restore a complete previous known-good state.

## Files

- `src/release_controller_pr166.py`
- `tests/test_pr166_release_controller.py`
- `docs/pr166_release_controller.md`

## What the module models

`ProductionRelease` is an immutable desired release object that binds:

- release ID and rank;
- code commit;
- image digest;
- wheel hashes;
- PolicyBundle hash;
- config, DB, event and evidence schema versions;
- program/asset/provider pins;
- signer version;
- deployment manifest hash;
- sandbox and egress profiles;
- previous known-good release ID;
- compatibility window;
- expiry, revocation and anti-rollback floor.

`DesiredObservedState` verifies desired vs observed image/config/policy/DB and
signer generations.

`StagePlan` describes executable progressive stages:

```text
artifact verified
→ deployed with zero traffic / shadow
→ paper readiness
→ bounded canary
→ limited-live
→ complete or rollback
```

`RollbackBundle` requires a complete rollback target. Switching to shadow mode
alone is not accepted as deployment rollback.

`evaluate_release_controller(...)` returns a deterministic
`ReleaseControllerReport` and durable `RolloutEvent`.

## Safety posture

This PR does not deploy anything and does not enable trading. It contains no
network calls, signing, Keypair loading, RPC, Kubernetes/systemd mutation or
live/canary activation.

`ReleaseControllerReport.live_allowed` is deliberately always `False` in this
slice. PR-157 release/canary evidence must still pass before any live path can
be armed.

## Focused test coverage

The tests verify that:

- release evidence alone cannot imply live activation;
- desired/observed mismatches freeze new submissions;
- complete previous known-good rollback evidence is required;
- revoked/vulnerable releases cannot promote;
- rollback targets cannot be below the anti-rollback security floor;
- DB compatibility is checked across the rollback window;
- at most one submission-capable generation is allowed;
- old workload presence blocks completion;
- observation duration and human approvals are enforced;
- health triggers request rollback/freeze;
- rollout history is durable and hash-chain reconstructable;
- static architecture scan flags obvious deploy/sign/send bypass tokens.

## Parallel PR compatibility

The slice is intentionally additive and avoids high-conflict files:

- no `scripts/verify_repo.py` edit;
- no `config/format_targets.txt` edit;
- no workflow edit;
- no active runtime/provider/signer/sender edit.

Later PR-166 integration can wire this primitive into the real deployment
mechanism once PR-152…165 stabilize their contracts.
