# PR-092 actual shadow soak evidence boundary

PR-092 is a fail-closed release-review gate for a real 72-hour-or-longer
sender-free shadow/mainnet-read-only soak. It intentionally does not start a
soak, discover opportunities, simulate trades, sign transactions, submit
transactions, or enable live/canary mode.

## Scope

The PR-092 evidence bundle is eligible for manual release review only when it
contains materialized artifact files with matching SHA-256 digests and when the
upstream prerequisites are human-reviewed and passing:

- PR-089 active sender-free paper composition root;
- PR-090 unified runtime truth and readiness;
- PR-091 security, SBOM, provenance and chaos artifacts.

Until those prerequisites are real and reviewed, the evaluator reports a blocked
state.

## Required materialized artifacts

The manifest requires all of the following artifact kinds:

- raw events;
- replay corpus;
- metrics report;
- operator review;
- deterministic replay report;
- runtime readiness;
- security provenance;
- immutable bundle;
- bundle signature.

Each artifact must be a normalized non-fixture relative path under the provided
artifact root, must exist on disk, must have the expected byte size, and must
hash to the pinned SHA-256 digest. Remote URIs can remain in external release
records, but this gate does not mark evidence ready unless the bytes are
materialized and re-hashed locally or in the repository artifact tree.

## Safety contract

The evaluator always returns `live_allowed = false`. Readiness means only
`ready-for-manual-release-review`, never automatic sender/canary/live enablement.
The gate blocks if it observes sender imports, enabled sender endpoints, live
submissions, recorded fixtures, missing prerequisites, missing artifacts, digest
mismatches, insufficient duration, replay failures, reconciliation mismatches, or
stale unsafe PR-060 evidence.

## Suggested verification

```bash
python -m pytest tests/test_pr092_actual_shadow_soak.py -q
python -m pytest tests/test_pr079_real_shadow_soak.py tests/test_pr092_actual_shadow_soak.py -q
python scripts/verify_repo.py --skip-dependency-audit
```

## Remaining operational work

This patch is not the real 72-hour soak itself. After PR-089, PR-090 and PR-091
land, an operator still needs to run the actual sender-free shadow soak, commit
or attach the immutable bundle, review it, and point the PR-092 manifest at the
real materialized files.
