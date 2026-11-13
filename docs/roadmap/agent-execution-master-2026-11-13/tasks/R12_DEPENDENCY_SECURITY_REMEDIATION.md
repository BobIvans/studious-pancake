# Assignment — R-12 dependency and supply-chain security remediation

Copy-ready trigger: Audit and remediate the repository's dependency vulnerability baseline. The full repository verification workflow on PR #595 head 764d2cf40b3ea79c88fa725fd402f1f4c3355b10 failed in pip-audit after formatting, mypy, wheel/package smoke, non-root image smoke and secret scanning passed. The audit reported 68 known advisories across 9 pinned packages. This was not caused by this documentation-only PR: no runtime or dependency files changed. Treat the audit as a real current release blocker until refreshed against latest main and resolved or explicitly accepted through the existing security authority.

## Reported package findings and minimum fix candidates from the CI log

| Package | Locked version observed | Candidate fix shown by pip-audit |
|---|---:|---:|
| aiohttp | 3.14.3 | 3.14.4 |
| brotli | 1.2.0 | 1.2.1 |
| certifi | 2026.6.17 | 2026.10.18 |
| setuptools | 83.0.0 | 84.1.0 |
| black | 26.3.1 | 26.10.1 |
| msgpack | 1.2.2 | 1.2.3 |
| filelock | 3.32.5 | 4.2.1 (verify all advisory fix constraints; one row reported 4.0.9 as an alternative for one advisory) |
| pillow | 12.3.0 | 13.0.0 |
| uv | 0.11.15 | 0.13.4 |

This table is a captured CI finding, not permission to bulk-upgrade. Recheck current advisories, package releases, Python 3.13 support, transitive dependency constraints, license and lock-generation policy before changing pins.

## Required work
1. Re-run pip-audit on the latest main and record the exact main SHA, lockfile hashes, timestamp and full current advisory IDs. Distinguish runtime dependencies from development/build/test-only dependencies.
2. Inspect pyproject.toml, requirements.lock, requirements-dev.lock, uv lock tooling and package source constraints. pyproject remains the direct dependency source of truth.
3. For each advisory, record affected code path, exploitability/reachability, fixed versions, breaking changes and whether a direct or transitive update is required.
4. Update only compatible pins using the repository's pinned uv/lock workflow. Do not hand-edit generated lock files unless the documented lock process requires it.
5. Run dependency consistency, pip-audit, full offline tests, formatting, undefined-name/type/security checks, wheel/console smoke, non-root image smoke and scripts/verify_repo.py.
6. Include rollback notes, source provenance and exact dependency diff. Do not suppress advisories, weaken --strict, exclude packages without security review or mark a vulnerability accepted solely to green CI.
7. If no safe compatible version exists, leave the package BLOCKED with a documented mitigation and owner; never claim zero findings without a current audit.

## Acceptance
- Current pip-audit result has zero unaccepted findings, or each residual finding has a reviewed, time-bounded security disposition and compensating control.
- All locks regenerate reproducibly and pass dependency consistency.
- Full tests and package/runtime smoke pass on supported Python 3.13 platforms.
- No change to signer/sender quarantine, live hard-deny, production authority or protocol behavior.
- One focused review-only PR targeting current main with full audit artifact and exact test counts.
