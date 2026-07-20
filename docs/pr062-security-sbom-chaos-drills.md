# PR-062 — Security, SBOM, load/chaos and operational drills

This PR adds a fail-closed, evidence-only release gate for the remediation queue
item **PR-062**.  It does not enable live trading, signing, Jito/RPC submission,
provider calls, or runtime execution.

## Problem

The repository already has useful PR-043 and PR-047 primitives, but the 2026-07-21
audit identifies a missing cross-cutting PR-044/062 suite: the project needs one
place that proves security gates, SBOM/image provenance, provider/RPC/Jito
failure injection, journal corruption handling, bounded queues/retries/tasks,
rollback RTO, and kill-switch/rollback rehearsals before any limited-live
promotion.

A normal green CI run is not enough.  PR-062 evidence must prove that known
failure modes land in safe states, not in ambiguous submission or automatic
resubmission.

## Added boundary

`src/release_gate/operational_drills.py` defines:

- `SecurityOperationalEvidence`
- `FailureInjectionScenario`
- `OperationalDrillSuite`
- `OperationalReadinessGate`
- `OperationalReadinessResult`
- `OperationalFailureArea`

The gate is intentionally offline and deterministic. It consumes recorded
evidence and returns `ready-for-limited-live` only when every required condition
is proven.

## Required failure areas

The default required suite covers:

- isolated signer policy;
- SBOM/image provenance;
- secret scanning;
- dependency audit;
- provider rate limits;
- provider schema drift;
- RPC fork/gap behavior;
- ambiguous Jito submission;
- journal corruption;
- queue saturation;
- memory/task leak cleanup;
- rollback RTO.

## Hard blockers

The gate blocks promotion when any of these are missing or unsafe:

- secret scan did not pass;
- plaintext key findings exist;
- dependency audit policy blocks the release;
- SBOM digest or image digest is missing/placeholder/invalid;
- signer policy is not enforced;
- signer reference is not structural (`env:`, `file:/`, or `keychain:`);
- required failure scenario is absent;
- failure scenario did not prove a safe terminal state;
- observed retries, queue depth, or RTO exceed configured bounds;
- automatic resubmission happened during an ambiguous/failure drill;
- residual tasks remain after the drill;
- rollback or kill switch was not rehearsed;
- any live submission happened during the PR-062 drill suite.

## Verification

Focused checks:

```bash
python -m pytest tests/test_pr062_security_chaos_drills.py -q
python -m compileall -q src/release_gate tests/test_pr062_security_chaos_drills.py
```

Recommended broader gate:

```bash
python scripts/verify_repo.py --skip-dependency-audit
```

## Non-scope

This PR does not complete PR-064 canary enablement. It also does not claim that a
real 72-hour shadow soak, real SBOM artifact, production image digest, or
credentialed provider chaos suite has already been run. It creates the strict
acceptance contract that those artifacts must satisfy.
