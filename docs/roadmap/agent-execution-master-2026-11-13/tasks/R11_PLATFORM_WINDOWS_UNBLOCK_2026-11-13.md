# R11 — Windows-native unblock: fcntl fallback + getuid guard + blob-path dir-fsync (POSIX-identical)

Workstream: R11 platform/CI reproducibility. Branch `agent/platform-repro` (base `86be458a87ed3f499cc32ff56426b2866c90422a`), review-only PR, not merged.

## Environment (recorded, not assumed)

- OS: Windows 11 native (10.0.26300 x64), Git Bash, no WSL — `wsl.exe --status` reports "Windows Subsystem for Linux is not installed" (Russian locale message). The P0 baseline's WSL-first choice is therefore unusable on this machine; the in-repo native fallback (PR-0 design intent, `docs/roadmap/p0-offline-execution-master-2026-11-13/P0_IMPLEMENTATION_PLAN.md`) is implemented instead.
- Python: CPython 3.13.15 (MSC v.1944, 64-bit) at the shared venv `.venv/Scripts/python.exe`.
- Git `core.autocrlf=true` locally; commits made with `git -c core.autocrlf=false`.
- Note: creating symlinks (`OSError WinError 1314`) requires a Windows privilege this user does not hold; several remaining failures below stem from that environment fact, not from code.

## Blockers fixed (scope — all in two files owned by this lane)

1. `src/qualification_campaign/evidence.py` imported `fcntl` at module level (Unix-only) → `ModuleNotFoundError` at collection. On base, **10 test modules were uncollectible** (not just the 3 named in the P0 baseline): `tests/test_din00_source_admission.py`, `tests/test_din01_bounded_discovery.py`, `tests/test_gpr01_research_economic_graph.py`, `tests/test_gpr01_v22_delta.py`, `tests/test_gpr02_solana_parallel_radar.py`, `tests/test_gpr03_sui_shadow.py`, `tests/test_qpr02_data_plane.py`, `tests/test_qpr03_source_intake.py`, `tests/test_r02_prerequisite_capture.py`, `tests/test_rcn00_reconciliation.py` — all `No module named 'fcntl'` via `evidence.py` (311 tests).
2. `src/durability/lifecycle.py:378` (and the same comparison in `_secure_sqlite_files`) used bare `os.getuid()`/`os.getgid()` → `AttributeError` for every file-backed durable-store test on Windows (146 test-level failures/errors on base, after `fcntl` unblocking).
3. `src/qualification_campaign/evidence.py` blob path (>750 KB payloads) used bare `os.O_DIRECTORY` + directory-fsync → `AttributeError` on Windows (test `test_qpr02_data_plane.py::test_large_evidence_blob_is_durable_hash_verified_and_bounded`).

## Change

- `src/qualification_campaign/evidence.py`: `import fcntl` behind a `sys.platform == "win32"` guard (hotfix restructure of the original `try/except ImportError` so static analysis is platform-conditional — mypy analyzes the msvcrt branch only on win32 and the POSIX branch only on POSIX; runtime selection is unchanged); win32 path defines `_PosixFlockShim` emulating the flock operations this module uses via stdlib `msvcrt.locking`, with one targeted `# type: ignore[assignment]` on the documented module-name rebinding; the blob-path directory fsync runs the POSIX-exact branch on POSIX and a documented conservative branch on win32. No new dependency; POSIX hosts import real `fcntl` and never enter the shim.
- `src/durability/lifecycle.py`: new `_posix_owner_ids()` helper returning `(os.getuid(), os.getgid())` on `sys.platform != "win32"`, else `None`; the two ownership comparisons and the group/world-writable mode comparison are gated on it. Same checks, same order, same error messages on POSIX.

## POSIX-equivalence argument

fcntl shim (Windows path only):
- `flock(fd, LOCK_EX)` — blocking exclusive whole-file advisory lock. Emulated with `msvcrt.locking(fd, LK_NBLCK, 2**31-1)` anchored at offset 0 inside a retry loop (`time.sleep(0.002)`), because `LK_LOCK`'s bounded 10-second wait would diverge from flock's indefinite blocking. Verified cross-process: blocking acquire waited 3.00 s for another process to release.
- `flock(fd, LOCK_EX | LOCK_NB)` — raises `BlockingIOError(errno.EAGAIN, ...)`, matching POSIX `EWOULDBLOCK`. Verified cross-process.
- `flock(fd, LOCK_UN)` — releases the held range (unlock only follows a successful acquire in `claim_attempt`'s try/finally, so the POSIX "unlock without lock" edge is not exercised).
- Lock scope/ownership: Windows range locks are per open handle, matching flock's per-open-file-description semantics. The lock file (`<db>.campaign-lock`) is dedicated and never written, so a fixed range anchored at offset 0 is equivalent to flock's whole-file lock for cooperating processes, and the advisory-vs-mandatory distinction is unobservable.
- Constants carry POSIX fcntl values (`LOCK_SH=1, LOCK_EX=2, LOCK_NB=4, LOCK_UN=8`); `LOCK_SH` is conservatively mapped to exclusive (msvcrt has no shared lock; unused here; no weakening). The caller's fd position is saved/restored around every call.

getuid guard:
- On POSIX, `_posix_owner_ids()` returns the real ids and the comparisons evaluate exactly as before, in the same order, raising the same `UnsupportedTopologyError` messages (`os.getuid()` is a pure syscall; calling it once per method instead of per component is unobservable).
- On Windows, `os.stat` reports placeholder `0` for `st_uid`/`st_gid` and synthetic mode bits (a writable directory always reads `0o777`, so `st_mode & 0o022` is true for every writable directory — the check is vacuous there). The POSIX-DAC comparisons are skipped on win32; every other topology gate still runs: symlink rejection (including all parent components), regular-file requirement, hard-link count, SQLite sidecar checks, `mkdir(mode=0o700)` + `chmod` attempts, `_revalidate_open_file` identity checks. Documented follow-up hardening (not done, to avoid changing admission semantics beyond platform neutrality): explicit NTFS-ACL verification via ctypes for the durable parent on Windows.

Blob-path directory fsync:
- POSIX: unchanged (`os.open(dir, os.O_DIRECTORY)` + `os.fsync`).
- Windows: `os.open` cannot open directory handles at all (the previous code crashed every large-blob append). The blob bytes are already `os.fsync`ed before the hardlink; NTFS journals link metadata, so a lost dirent cannot corrupt retained evidence — replay fails closed on a missing/mismatched blob reference (`EVIDENCE_BLOB_REFERENCE_INVALID` / `EVIDENCE_BLOB_HASH_MISMATCH`). Hash and admission semantics are untouched; a ctypes `FlushFileBuffers` directory handle is the possible future hardening.

## Evidence hashes — exact artifact audit

No contract-evidence hash pin covers either changed file. Verified directly:

- `config/jupiter_endpoint_quarantine.json`: sha256 pins only `src/solana_parallel_radar/cli.py` (`f699fba...`) and `src/solana_parallel_radar/probes.py` (`c7262a8...`) under `read_only_research_references`; `policy_reference_paths` and `quarantined_paths` are path-only.
- `scripts/verify_mpr_next_08_jupiter_v2_contract.py` hashes exactly: `config/product_contract_pr195.json`, `src/resources/product_contract_pr195.json`, `docs/external_contracts.yaml`, `src/providers/jupiter/router.py`, `src/providers/conformance/mega_b2.py`, `src/resources/production_surface_manifest.json`, `config/jupiter_endpoint_quarantine.json`, `scripts/verify_repo.py`. None is `evidence.py` or `lifecycle.py`. Script re-run after the change: **passed**.
- `config/product_contract_pr195.json`: no source hash pins.

Conclusion: no shared contract artifact affected; nothing to coordinate on hash pins.

## Exact test counts (Windows native, full suite, `-q -p no:cacheprovider --continue-on-collection-errors`)

| metric | BEFORE (base 86be458a) | AFTER (this branch) |
|---|---|---|
| collection errors (modules) | 10 (all `ModuleNotFoundError: fcntl` via `evidence.py`) | 0 |
| test-level errors | 25 | 0 |
| failed | 181 | 60 |
| passed | 4826 | 5283 |
| skipped | 3 | 3 |
| collected | 5035 + 10 uncollectible modules (311 tests) | 5346 (all) |

Reconciliation (exact): 5283 − 4826 = 457 = 311 newly-collected (all pass) + 146 formerly-failing tests now passing. The 146 were re-run on the base worktree: 121 failed + 25 errors (all still failing on base), causes dominated by `AttributeError: module 'os' has no attribute 'getuid'` at `src/durability/lifecycle.py:378` (114 direct matches; `pytest.raises(UnsupportedTopologyError)` blocks interrupted by the same AttributeError account for the rest). The AFTER failure set is a **strict subset** of the BEFORE failure set (`comm` verified: zero after-only failures) — no regression introduced.

Previously-blocked suites, after the fix:
- 10 fcntl-blocked modules: **311 passed, 0 failed, 0 skipped** (226.85 s), including the P0 baseline triple (`test_gpr02_solana_parallel_radar.py`, `test_din01_bounded_discovery.py`, `test_qpr03_source_intake.py`: 99 passed, 79.98 s).
- 13 durable-lifecycle modules (all file-backed store tests): **207 passed, 0 failed, 0 errors** (35.31 s); before: 23 failed + 25 errors + 159 passed.
- `tests/test_qpr02_data_plane.py` (incl. the large-blob durability test): **15 passed**.

Representative POSIX-semantics proof: cross-process exclusion, `BlockingIOError` on `LOCK_EX|LOCK_NB`, indefinite blocking (3.00 s wait for release) and `LOCK_UN` verified with a standalone two-process probe (kept outside the repo). Black `--check` clean on both changed files. `scripts/verify_mpr_next_08_jupiter_v2_contract.py`: passed.

## Remaining 60 Windows failures — pre-existing, outside R11 scope (coordination notes)

Strict-subset verified; sampled causes, none related to the three fixes:

- `tests/durability/test_pr003_storage_security.py` (6) and `tests/test_pr06_management_audit_anchor.py` (3), `test_pr170_management_plane.py` (3), `test_pr205_asymmetric_qualification.py`, `test_pr120_secret_resolver_config_jito.py` (2): the `OSError WinError 1314` symlink-creation privilege this environment lacks, plus Windows mode-bit semantics (chmod only toggles read-only) and `PermissionError` on directory `os.chmod`/`os.replace` semantics. The sibling `_fsync_directory` helpers using `os.open(..., getattr(os, "O_DIRECTORY", 0))` (`src/security/filesystem.py:87`, `src/security/secure_files.py:202`, `src/observability/audit_anchor_pr06.py:162`) have the same latent Windows directory-open issue that this PR fixed only in `evidence.py` — owners should adopt the same conservative branch.
- `tests/test_dynamic_correlation_ledger.py` (3): `FileNotFoundError` on deep content-addressed partition paths — Windows MAX_PATH (260-char) limitation. **Lane H scope** (platform risk reported, not fixed here); long content-addressed names exceed MAX_PATH unless long-path opt-in or `\\?\` prefixes are adopted.
- `tests/intelligence/test_pressure_manager.py` (12): includes `test_cross_process_lock_blocks_a_second_pressure_cycle` with a bare in-function `import fcntl`; the intelligence lane can adopt the same shim (natural follow-up: extract `_PosixFlockShim` into a shared `src` compat module). `src/config/activation.py` and `src/intelligence/pressure_manager.py` keep their pre-existing guarded `fcntl = None` fallbacks (skip cross-process locking on Windows).
- Others (container runtime, parquet/zstd storage, decision-model artifacts, hermetic runtime, instance resources, external-contract registries): same families of Windows ACL/mode-bit/privilege differences; before-state failure list preserved in the PR description.

## Safety flags

- Network usage: 0 (offline tests only; no fixtures touched).
- Private keys / signing / sending / borrowing / deployment / promotion: none (all false).
- Gates weakened or tests skipped: none — POSIX locking, ownership, hash-verification and admission semantics are byte-for-byte unchanged on POSIX; no test was modified; the after-failure set is a strict subset of before.

## Follow-ups (not in this PR)

1. Extract `_PosixFlockShim` to a shared compat module; adopt in `tests/intelligence/test_pressure_manager.py`, `src/config/activation.py`, `src/intelligence/pressure_manager.py`.
2. NTFS-ACL ownership verification via ctypes for durable paths (replaces the conservative skip).
3. Same conservative directory-fsync branch for the three sibling `_fsync_directory` helpers (security/observability lanes own those files).
4. Lane H: correlation-ledger MAX_PATH strategy (long-path opt-in or `\\?\` prefixes).
5. P0 baseline `p0_blocked_on_windows` command now passes natively; supersede the WSL-first note in `P0_BASELINE.json` when this PR lands.
