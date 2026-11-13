# R12 — Dependency security remediation: strict pip-audit to zero (2026-11-13)

Workstream: R12 of the 2026-11-13 whole-project parallel execution (`PARALLEL_EXECUTION_MANDATE.md`).
Branch: `agent/r12-dependency-security`. Work started from base `86be458a87ed3f499cc32ff56426b2866c90422a`;
branch rebased onto origin/main (`65fda08f`) before push. Baseline test comparisons in section 7 use 86be458a.
Status: IMPLEMENTED (locks remediated through the official workflow; strict pip-audit locally 68 -> 0 findings; offline tests run natively with a typed Windows platform limitation).

## 1. Problem

Main-branch CI job "Repository verification" (`.github/workflows/linter.yml`) fails at the strict
pip-audit gate invoked by `scripts/verify_repo.py` -> `scripts/quality_gate.py --with-dependency-audit`:

```
$ python -m pip_audit -r requirements.lock -r requirements-dev.lock --strict --progress-spinner off
Found 68 known vulnerabilities in 9 packages
```

Captured from run 43502280783 (main push, 2026-11-13T20:32:55Z). This blocks every PR.

## 2. Advisory table (68 advisories / 9 packages, revalidated 2026-11-13)

Primary source of truth: live `pip-audit 2.9.0` (OSV + PyPI advisory DB) rerun locally on the base
locks on 2026-11-13 — result byte-for-byte matches the CI log advisory set (68/68 IDs, see section 5).
Corroborating web sources listed per package; retrieval date for all: 2026-11-13.

| Package | Locked | Fixed (pinned now) | Count | Profile in locks | Reachability / notes | Source (retrieved 2026-11-13) |
|---|---|---|---:|---|---|---|
| aiohttp | 3.14.3 | 3.14.4 | 8 | runtime, direct (pyproject `dependencies`) | HTTP client/server used by provider plane; server-side DoS classes (request/header timeout, WebSocket frame reassembly memory, etc.) | https://github.com/aio-libs/aiohttp/security/advisories/GHSA-5wr8-gcqf-gqf3 (CVE-2026-111064), https://github.com/advisories/GHSA-2g87-pp6c-29x5 (CVE-2026-123817); remaining 6 IDs (GHSA-494j-54xm-rwp3, GHSA-pqxq-w44r-73xw, GHSA-9xw5-w5jj-pvcg, GHSA-gx76-c99x-2c96, GHSA-6cjc-53gc-5rqm, GHSA-f9xw-jh8m-3mwq) enumerated by pip-audit/OSV, all fixed in 3.14.4 |
| brotli | 1.2.0 | 1.2.1 | 1 | runtime, direct | Brotli decoder OOB write (CVE-2026-111497) on compressed responses | https://osv.dev/vulnerability/PYSEC-2026-4322, https://github.com/advisories/GHSA-9v8h-qqgm-4m35 |
| certifi | 2026.6.17 | 2026.10.18 | 1 | transitive of requests/httpx/httpcore; present in BOTH locks | compromised emSign root CAs in bundled trust store (TLS validation) | https://docs.devguard.org/vulnerability-database/PYSEC-2026-4320 (GHSA-6q48-6c7w-9gw2) |
| setuptools | 83.0.0 | 84.1.0 | 1 | build-system.requires + dev direct; present in BOTH locks | Windows path escape via `namespace_packages.txt` in legacy wheel install path (build/dev surface only, not shipped runtime) | https://github.com/advisories/GHSA-xmj3-9gf7-h52w |
| black | 26.3.1 | 26.10.1 | 1 | dev, direct | GitHub Action RCE via unvalidated `required-version` (CVE-2026-114134); formatting-only tool | https://github.com/advisories/GHSA-cg8m-r9f2-5wm2 |
| msgpack | 1.2.2 | 1.2.3 | 1 | transitive of cachecontrol <- pip-audit; dev lock only | unbounded memory leak in C extension on malformed input (DoS of dev tooling) | https://github.com/advisories/GHSA-j586-36cw-2gc2 (CVE-2026-114613) |
| filelock | 3.32.5 | 4.2.1 | 12 | transitive of cachecontrol <- pip-audit; dev lock only | ReadWriteLock path traversal / SQLite side-file symlink issues (CVE-2026-112940 POSIX, CVE-2026-112913 Windows); one advisory (GHSA-j8f7-rjxc-mr56) fixes at 4.0.9, all 12 covered by 4.2.1 | https://github.com/tox-dev/filelock/security/advisories/GHSA-9vhv-jxww-xfm5, https://security-tracker.debian.org/tracker/CVE-2026-112940; remaining 10 IDs (GHSA-567q-5qvw-pf92, GHSA-m462-7rxw-wvpg, GHSA-j8f7-rjxc-mr56, GHSA-8mx5-7m5m-r77g, GHSA-69hj-f68j-2879, GHSA-9c4x-gm8v-wgc4, GHSA-rfpc-qcw5-3pc4, GHSA-cwqr-hh33-gh44, GHSA-fq56-3cx3-fjxp, GHSA-6627-m3xw-93mp) enumerated by pip-audit/OSV |
| pillow | 12.3.0 | 13.0.0 | 42 | transitive of matplotlib/seaborn (analytics profile); dev lock only | image decoder OOB reads, PDF parser recursion/DoS, heap overflows in format handlers (19 PYSEC + 23 GHSA); analytics/plotting-only surface, not shipped runtime | https://pillow.readthedocs.io/en/latest/releasenotes/13.0.0.html, https://www.openwall.com/lists/oss-security/2026/10/21/24, https://github.com/advisories/GHSA-p4wg-p73j-c528 (CVE-2026-112895), https://vulnerability.circl.lu/vuln/pysec-2026-4327; full ID list below |
| uv | 0.11.15 | 0.13.4 | 1 | dev, direct (lock resolver tool) | vendored webpki-root-certs bundle contains compromised emSign root; TLS verification of index downloads (CVE via GHSA-hq85-5cpj-mr62) | https://osv.dev/vulnerability/PYSEC-2026-4321 |

Pillow advisory IDs (all fixed in 13.0.0): PYSEC-2026-4326, PYSEC-2026-4327, PYSEC-2026-4328,
PYSEC-2026-4329, PYSEC-2026-4330, PYSEC-2026-4331, PYSEC-2026-4332, PYSEC-2026-4333,
PYSEC-2026-4334, PYSEC-2026-4335, PYSEC-2026-4336, PYSEC-2026-4337, PYSEC-2026-4338,
PYSEC-2026-4339, PYSEC-2026-4340, PYSEC-2026-4341, PYSEC-2026-4342, PYSEC-2026-4343,
PYSEC-2026-4363, GHSA-p4wg-p73j-c528, GHSA-65qm-jvmh-6pqg, GHSA-q45j-58j2-45rg,
GHSA-462x-pgg6-55fp, GHSA-c6hw-5grf-ff96, GHSA-vx6w-vv9f-6gvg, GHSA-w889-685w-c8fh,
GHSA-j4m9-6w36-pw47, GHSA-fc9g-5qg7-mf45, GHSA-22hg-r758-rrw9, GHSA-74r2-7ff9-mjj2,
GHSA-254f-3936-288h, GHSA-jg86-v3jv-hrpm, GHSA-f2g6-542v-9j58, GHSA-5xm2-6676-qcp9,
GHSA-gg2r-wvfm-q9rx, GHSA-332p-7hrc-92wf, GHSA-24rc-8hj2-v98c, GHSA-mrfp-p49p-3hf2,
GHSA-g7cr-3p24-7wf7, GHSA-78g4-xqwv-q3g8, GHSA-xcvg-w56q-r89m, GHSA-wqgw-9xfh-qf2g.

## 3. Remediation applied (official lock workflow only)

Source of truth remains `pyproject.toml`. Locks were regenerated with
`scripts/lock_requirements.py` (the pinned PR-025 workflow), never hand-edited inconsistently.

1. Direct pins bumped in `pyproject.toml` to the minimal fixed versions:
   aiohttp 3.14.4, brotli 1.2.1, setuptools 84.1.0 (dev profile AND `build-system.requires`), black 26.10.1, uv 0.13.4.
2. `scripts/lock_requirements.py` resolver pin updated `0.11.15 -> 0.13.4` (`UV_VERSION` constant and
   generated-header string) — required by PYSEC-2026-4321 and by the script's exact-version check;
   same pattern as the prior tool-advisory closure in 1550f58e (uv 0.10.0 -> 0.11.15).
3. Resolver-version assertions updated in `tests/test_pr025_packaging.py` and
   `tests/deployment/test_pr008_supply_chain.py` (0.13.4).
4. Transitive-only fixes (certifi, msgpack, filelock, pillow): the workflow keeps transitive versions
   from the existing hashed locks (uv pip compile prefers existing output-file pins; verified
   empirically: regenerating with unchanged inputs reproduces byte-identical locks). Therefore these
   four rows were first re-pinned in `requirements.lock` / `requirements-dev.lock` using
   uv-generated `--generate-hashes` rows (exact fix versions), then the official workflow was rerun,
   which re-resolved and rewrote both hashed locks and the manifest consistently. This mirrors the
   documented precedent ee60fa09 ("fix(deps): pin urllib3 2.8.0 in hashed dependency locks").
5. Workflow executed twice; second run byte-identical (idempotence/reproducibility proof,
   sha256 comparison of all six generated artifacts).

### Dependency diff (exact)

- requirements.txt / requirements-analytics.txt: aiohttp 3.14.3->3.14.4, brotli 1.2.0->1.2.1
- requirements-dev.txt: aiohttp, brotli (as above), black 26.3.1->26.10.1, setuptools 83.0.0->84.1.0, uv 0.11.15->0.13.4, header "with uv 0.13.4"
- requirements.lock: aiohttp, brotli, certifi 2026.6.17->2026.10.18, setuptools, plus companion transitive yarl 1.24.2->1.25.1
- requirements-dev.lock: all of the above plus msgpack 1.2.2->1.2.3, filelock 3.32.5->4.2.1, pillow 12.3.0->13.0.0
- config/requirements-lock.json: resolver version 0.13.4 + recomputed sha256 for all six artifacts

Companion bump justification: aiohttp 3.14.4 declares `yarl<2.0,>=1.25.1` (3.14.3 declared
`yarl<2.0,>=1.17.0`), so yarl 1.25.1 is forced by the security fix; verified against PyPI metadata
(retrieved 2026-11-13). No other transitive moved (fresh-cache dry run on base inputs produced
byte-identical locks, proving zero drift).

### Constraint compatibility checks

- matplotlib 3.11.1 requires `pillow>=9` (no upper cap) -> pillow 13.0.0 compatible.
- certifi consumers (requests, httpx, httpcore) have lower-bound-only constraints.
- msgpack/filelock consumers (cachecontrol via pip-audit) have lower-bound-only constraints.
- filelock 4.x is a major bump; its only consumer here (cachecontrol) declares no upper cap; the
  workflow's full linux/py3.13 resolution succeeded with the new pins (twice).

## 4. Verification

### pip-audit before/after (local, 2026-11-13)

| Run | Command | Result |
|---|---|---|
| before | `python -m pip_audit -r requirements.lock -r requirements-dev.lock --strict --no-deps --disable-pip --progress-spinner off` | `Found 68 known vulnerabilities in 9 packages` (exit 1) — ID set identical to CI log 43502280783 (68/68) |
| after | same command | `No known vulnerabilities found` (exit 0) |

Platform caveat: locally the audit ran with `--no-deps --disable-pip` because both hashed locks
target linux (they contain uvloop wheels/sdist; pip-based resolution cannot build uvloop on
Windows). The locks are complete resolutions pinned to exact versions, so `--no-deps` audits every
package/row of both locks by exact version — equivalent coverage to CI's full-resolution audit on
ubuntu-latest. The gate itself is unchanged: `--strict` kept, no `--ignore-vuln`, no exclusions.

### Offline tests (native Windows run, socket-disabled)

- Command: `python -m pytest tests/ -q --disable-socket --allow-unix-socket -p no:cacheprovider` with the shared 3.13.15 venv, cwd = worktree.
- Exact counts: see section 7 (filled from the actual run log).
- Platform limitation: tests importing `fcntl` (POSIX-only) fail collection on Windows with
  `ModuleNotFoundError: No module named 'fcntl'`. Per the execution mandate these are typed
  LOCAL_PLATFORM_BLOCKED and are fixed by the platform lane; they were not hacked around.

### Gates

- Lock workflow: exit 0, twice, second run byte-identical.
- Lock manifest digests (`config/requirements-lock.json` vs actual sha256 of the six artifacts): consistent (asserted by the two updated tests).
- `pytest tests/test_pr025_packaging.py tests/deployment/test_pr008_supply_chain.py -q`: included in counts in section 7.

## 5. Provenance

- CI failure capture: `gh run view 43502280783 --repo BobIvans/studious-pancake --log-failed` (run on main push of PR #595 merge, 2026-11-13T20:32:55Z).
- Base locks audited locally reproduced the CI finding exactly: 68 advisories, 9 packages, identical ID set.
- All fix versions verified to exist on PyPI (release index queried 2026-11-13): aiohttp 3.14.4, brotli 1.2.1, certifi 2026.10.18, setuptools 84.1.0, black 26.10.1, msgpack 1.2.3, filelock 4.2.1, pillow 13.0.0, uv 0.13.4.
- Precedents followed: ee60fa09 (targeted transitive pin in hashed locks), 1550f58e (resolver-tool advisory closure incl. UV_VERSION bump).
- Pre-change dry run of the official workflow on unmodified inputs: byte-identical outputs (zero unrelated drift).

## 6. Safety flags

All false / unchanged (verified in `scripts/verify_repo.py` SAFE_ENV and not touched here):
PAPER_TRADING_ONLY=true, LIVE_TRADING_ENABLED=false, JITO_ENABLED=false, KAMINO_LIQUIDATION_ENABLED=false.
No signer/sender/authority/protocol behavior changed; diff touches only dependency metadata,
the lock script's resolver pin, and two resolver-version assertions.

## 7. Exact test counts

All runs: shared Python 3.13.15 venv, cwd = worktree, socket-disabled (offline-first). This venv
still has the PRE-remediation dependency versions installed, so its results reflect the old lock's
installed packages; CI installs fresh deps from this PR's locks and is the authority.

1. As prescribed: `python -m pytest tests/ -x -q --disable-socket --allow-unix-socket`
   -> stopped at first collection error: 1 error, 0 tests run in 15.52s
   (`tests/test_din00_source_admission.py`: `ModuleNotFoundError: No module named 'fcntl'`).
2. Full run, no `-x`: interrupted during collection: 10 errors (all fcntl, see section 8), 33.25s.
3. Full run with `--continue-on-collection-errors` on this branch:
   `4477 passed, 194 failed, 2 skipped, 333 errors, 10 collection errors in 225.85s`.
4. Identical command on base commit 86be458a (baseline):
   `4475 passed, 196 failed, 2 skipped, 333 errors in 189.52s`.
   Failed/error test-ID sets are identical between base and this branch except exactly two tests:
   `tests/test_pr025_packaging.py::test_optional_lock_profiles_are_explicit_and_hashed` and
   `tests/deployment/test_pr008_supply_chain.py::test_locks_include_resolved_transitive_dependencies`
   fail ONLY on the baseline because the stash-based checkout rewrote the base lock files with CRLF
   (core.autocrlf smudge), breaking the manifest digest comparison; committed LF content and this
   branch's files are LF and digest-consistent (both tests PASS on this branch — 12/12 in
   `tests/test_pr025_packaging.py` + `tests/deployment/test_pr008_supply_chain.py`).
   Conclusion: all 194 failures and 333 errors reproduce identically on base -> pre-existing
   Windows-platform / old-venv issues, unchanged by this PR (classification (a) per coordinator
   guidance; none are lock-related).
5. Lock validation on this branch: `pytest tests/test_pr025_packaging.py tests/deployment/test_pr008_supply_chain.py -q --disable-socket --allow-unix-socket` -> `12 passed in 14.99s`.

## 8. Typed blockers

- LOCAL_PLATFORM_BLOCKED (owned by platform lane; already fixed on main by R11 PR #603, merged as
  776c7223): 10 test modules fail collection on native Windows via
  `src/qualification_campaign/evidence.py:11` (`import fcntl`):
  tests/test_din00_source_admission.py, tests/test_din01_bounded_discovery.py,
  tests/test_gpr01_research_economic_graph.py, tests/test_gpr01_v22_delta.py,
  tests/test_gpr02_solana_parallel_radar.py, tests/test_gpr03_sui_shadow.py,
  tests/test_qpr02_data_plane.py, tests/test_qpr03_source_intake.py,
  tests/test_r02_prerequisite_capture.py, tests/test_rcn00_reconciliation.py.
  This branch is rebased onto origin/main (includes PR #603), so CI will not see these collection
  errors. Not hacked around here per the mandate.
- 194 failed / 333 errors: pre-existing on base (identical ID sets, section 7 item 4), environment
  = old deps in shared venv + Windows-specific behaviors (e.g., durability permission-pragmas,
  pytest-socket bind cases). Owned by platform lane / future dep-install rerun; out of R12 scope.
- Local pip-audit ran in `--no-deps --disable-pip` mode (see section 4 caveat); CI's
  ubuntu full-resolution audit is the authoritative gate and is expected to pass with the same
  zero findings (same pinned rows audited).

## 9. Rollback notes

Revert the single commit on `agent/r12-dependency-security`; all changes are dependency-metadata
only. The previous locks (base 86be458a) remain valid inputs to the same workflow.

## 10. Next task

R13/R14 (per TASK_INDEX) can proceed; after this PR merges, CI "Repository verification" should go
green and unblock every queued lane's PR.
