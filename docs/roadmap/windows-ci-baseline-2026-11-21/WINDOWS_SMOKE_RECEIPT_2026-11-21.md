# WINDOWS SMOKE RECEIPT — 2026-11-21

**Platform:** Windows 10.0.26300 x64, Git Bash; Python 3.13.15 (`>=3.13,<3.14` pin satisfied), venv `.venv`.
**Scope:** make the local Windows verification path runnable and produce an honest stage-by-stage receipt. This is repo-hygiene work, not campaign execution; no `src/` changes.
**Base:** `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54` (main, after #664/#668 merges).

## 1. Environment fixes applied (local venv only, no repo file changes)

| Step | Result |
|---|---|
| `pip install "build==1.5.0"` (pin per `pyproject.toml` dev extras + `requirements-dev.txt:13`) | installed, `pip show build` = 1.5.0 |
| `pip install "setuptools==84.1.0" "wheel==0.47.0"` (exact `[build-system] requires` pins; `--no-isolation` needs them in-venv) | installed |
| `pip-audit` version drift: installed **2.10.1** vs pin **2.9.0** | recorded, NOT changed (audit stage is skipped locally anyway; CI Linux authoritative) |

## 2. Stage-by-stage receipts (exit codes)

| Stage | Exit | Notes |
|---|---|---|
| `pip check`, `quality_gate.py` (flake8/black/mypy/bandit), `validate_authority_map.py` | 0 | passed in the earlier `verify_repo --skip-dependency-audit` run (log `.zcode/pr664/verify_repo.log`, pre-#664-merge main; unchanged code paths) |
| `scripts/package_smoke.py` — wheel build | 0 | after installing `build` + backend pins, `python -m build --wheel --no-isolation` succeeds |
| `scripts/package_smoke.py` — wheelhouse stage | **1** | `pip download --require-hashes --only-binary=:all: -r requirements.lock` fails: **`WINDOWS_LOCK_UVLOOP_NO_MARKER`** — `requirements.lock:1428` pins `uvloop==0.22.1` with no environment marker and zero markers exist in the whole lock (`grep -c 'sys_platform|platform_system'` = 0); uvloop ships no Windows wheel. Linux CI unaffected. Fix = regenerate lock with markers (`scripts/lock_requirements.py`) — separate task. |
| `python -m compileall -q arb_bot.py src scripts tests` | 0 | |
| `arb_bot.py status --json` / `capabilities --json` | 0 / 0 | |
| 27 pinned `scripts/verify_*` stages (list per `scripts/verify_repo.py:312-338`) | **26 × 0, 1 × 1** | all green except `verify_occ_durable_host.py` → **`WINDOWS_SQLITE_TEMP_CLEANUP_PERMISSION`**: `PermissionError [WinError 32]` on `content.sqlite3` — sqlite connection still open when `TemporaryDirectory` cleanup unlinks it (Windows file-lock semantics; POSIX unaffected) |
| full offline pytest (`-m "not live and not manual" --disable-socket --allow-unix-socket -q`) | **1** | baseline without PR changes (commit `e394c77b`): **288 failed, 5599 passed, 9 skipped, 327 errors** (13m30s); with #664 changes: 287/5600/327 — see `BASELINE_PYTEST_CLASSIFICATION_V1.json` |

## 3. Root causes of remaining Windows red (all typed, none caused by recent PRs)

1. **`WINDOWS_PYTEST_SOCKET_PROACTOR_LOOP`** — all 327 errors are fixture-setup `pytest_socket.SocketBlockedError`: `--disable-socket` blocks the Windows `ProactorEventLoop` self-pipe (`socketpair` AF_INET fallback created inside `events.new_event_loop`); `--allow-unix-socket` covers AF_UNIX only. Candidate fix: pre-create the loop before the socket guard or allow the loop self-pipe in `tests/conftest.py` (separate bounded task). Large share of the 288 failures share this root cause.
2. **`WINDOWS_LOCK_UVLOOP_NO_MARKER`** — see package_smoke stage above.
3. **`WINDOWS_SQLITE_TEMP_CLEANUP_PERMISSION`** — `verify_occ_durable_host.py` temp-dir cleanup.

## 4. Verdict

Windows verification is now **runnable end-to-end** (it previously could not even start: missing `build`). Honesty rules: `verify_repo` is **NOT green on Windows**; remaining work is exactly the three typed tasks above plus the genuine test-failure tail (GPR cluster = 146 failures etc.) classified in `BASELINE_PYTEST_CLASSIFICATION_V1.json`. This does not block docs-only PR merges while required CI checks on GitHub (Linux) are green; it remains open Windows-compatibility debt, tracked here — do not treat the 288 failures as fixed or harmless.

**Receipts on disk (session, untracked):** `.zcode/pr664/{package_smoke_receipt.log,package_smoke_receipt2.log,stage_receipts.txt,occ_durable_host.log,verify_repo.log,pytest_baseline.log,pytest_offline.log,replay_receipts.json}`.
