# PR-133 — Hermetic CI/build and artifact provenance

This patch adds an offline, review-only evidence gate for the PR-133 release
supply-chain contract.

The roadmap says PR-133 must prevent mutable GitHub Action refs, mutable Docker
tags, unhashed dependency artifacts and cache/network behavior from silently
changing release bytes after review.

## What changed

- Adds `src/hermetic_artifacts_pr133.py` with:
  - full-length reviewed GitHub Action SHA evidence;
  - Docker image digest evidence;
  - dependency wheel artifact SHA-256 evidence;
  - `pip --require-hashes` / offline wheelhouse controls;
  - network-denied reproducible-build control;
  - no-unreviewed-sdist control;
  - wheel/container/SBOM/dependency-graph/provenance hashes;
  - signature and trusted OIDC controls;
  - cache-integrity controls;
  - build-twice/reproducibility or documented nondeterminism gate;
  - release trust-root and key-rotation runbook gates.
- Adds `tests/test_pr133_hermetic_artifacts.py`.

## Safety / non-goals

- No workflow file changes.
- No Dockerfile changes.
- No requirements lock changes.
- No publishing path changes.
- No release signing key material.
- No live trading, sender, signer, wallet, RPC, Jito, MarginFi or paper runtime
  behavior.
- No claim that the repository is already release-hermetic; this patch only
  makes the acceptance contract explicit and testable.

## Parallel PR compatibility

This PR intentionally avoids high-churn repository-wide files such as
`config/format_targets.txt`, `scripts/verify_repo.py`, workflow files,
Dockerfile and requirements files. That keeps the branch reviewable while other
PRs continue moving `main`.

The new test is collected by the repository-wide non-live pytest sweep. The new
module is still covered by `compileall`, flake8 critical syntax checks and
import-time test coverage.

## Suggested verification

```bash
python -m pytest tests/test_pr133_hermetic_artifacts.py -q
python scripts/verify_repo.py --skip-dependency-audit
```

## Follow-up integration

Later PR-133 slices can wire this contract into actual workflow/Docker/lockfile
checks and release artifacts after the parallel PR queue stabilizes.
