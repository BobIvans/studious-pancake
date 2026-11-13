# Assignment — R-11 platform, CI, offline reproducibility and release readiness

Copy-ready trigger: Establish reproducible developer and CI validation for the full project without weakening security/capability gates. Inspect pyproject.toml, lockfiles, workflow definitions, scripts/verify_repo.py, platform-specific imports, package quarantine and current Windows/WSL state.

## Required work
1. Record exact OS, shell, Python patch version, venv, Git core.autocrlf, installed extras and WSL status. Do not assume a historical platform decision is already applied.
2. Run three offline reference verifiers:
   - docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/verify_bundle.py
   - docs/roadmap/r02-capacity-recovery-2026-10-08/offline/verify_offline.py
   - docs/integrations/offline/solana-p0/verify_offline_bundle.py
3. Run focused suites with network sockets disabled and full scripts/verify_repo.py. Record platform-specific collection failures distinctly from test failures.
4. Investigate existing fcntl/os.getuid Windows constraints and CRLF/hash-pinned reference behavior. Current P0 baseline records WSL-first choice; verify whether WSL exists and whether its Python 3.13 environment is usable. Do not weaken POSIX locking, hash verification or security gates.
5. Check GitHub Actions/CI status, branch protection, dependency audit, typing, formatting, security scanning, package build/wheel smoke and non-root container health.
6. Preserve deterministic replay, bounded external requests, provider quotas, clean-tree checks, immutable receipts and source/license manifests.
7. Document exact PowerShell and WSL commands for this user's Windows 11 development environment; no secrets in shell history or docs.

## Acceptance
A clean reproducible command sequence from a fresh checkout; exact pass/fail/skip counts; no ignored failures; CI checks green for the scoped PR; no change to live hard-deny, signer/sender quarantine or production boundaries.
