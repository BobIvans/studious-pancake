# PR-064 — Canary and release readiness

PR-064 is the final offline readiness aggregator for the first human-controlled
canary release. It does **not** enable live mode, arm the PR-046 controller,
sign a transaction, submit to RPC/Jito, fund a wallet, clear latches or promote
any venue.

## Dependency boundary

The 2026-07-21 remediation roadmap places PR-064 after PR-060 through PR-063.
The new `CanaryReleaseReadinessGate` therefore blocks unless every upstream
record is present, passed and human-reviewed:

- PR-060 real shadow soak and promotion evidence;
- PR-061 data-plane, lifecycle and observability integration;
- PR-062 security, SBOM, load/chaos and operational drills;
- PR-063 canonical Jito/RPC sender consolidation.

The gate also requires a PR-046 canary report that is limited-live, armed, idle,
free of active latches, free of outstanding submissions and explicitly has
`ai_authority=false`. It then carries forward the PR-047 release-gate result,
including any release blockers or warnings.

## Output semantics

A passing result means only:

> all required evidence is internally consistent enough for a human to consider
> a tiny canary release.

It does not grant runtime authority. The result includes:

- a deterministic upstream evidence hash;
- the PR-046 canary report hash;
- the PR-047 release manifest hash;
- machine-stable blockers;
- `live_mode_mutated=false`.

## Review focus

1. Missing PR-060..063 evidence must block readiness.
2. Passing but unreviewed evidence must block readiness.
3. A green PR-047 release gate cannot bypass an active canary latch.
4. AI authority must always block the release readiness state.
5. The module must remain offline and side-effect free.

## Focused verification

```bash
python -m pytest tests/test_pr064_canary_release_readiness.py -q
python -m compileall -q src/release_gate/canary_release_readiness.py tests/test_pr064_canary_release_readiness.py
python -m mypy --config-file mypy.ini src/release_gate
```
