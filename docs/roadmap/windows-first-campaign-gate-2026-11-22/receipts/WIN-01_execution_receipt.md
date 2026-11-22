# WIN-01 Execution Receipt — lock generator re-applies uvloop Windows marker

- Date: 2026-11-22
- Worktree: `sp-worktrees/wt679-win-lock`, branch `codex/679-win-lock-2026-11-22`, base main `0a0c8ad9`
- Defect: `WINDOWS_LOCK_UVLOOP_NO_MARKER` — `requirements.lock` / `requirements-dev.lock` contained `uvloop==0.22.1` without the `platform_system != 'Windows'` marker carried by the pyproject.toml pin, so `pip download --require-hashes --only-binary=:all:` failed on Windows (no uvloop wheel).

## Environment / preflight

- `uv` not on PATH. Installed `uv==0.13.4` into a TEMP venv OUTSIDE the repo: `%TEMP%\wt679-win-lock-tools\toolsvenv` (`python -m venv` + `pip install uv==0.13.4`), `uv 0.13.4 (7456b60bc 2026-10-20)`; its Scripts dir prepended to PATH for regeneration runs only. No global install; repo untouched outside the worktree.
- Python: repo venv `.../studious-pancake/.venv/Scripts/python.exe` = Python 3.13.15 (3.13.x required by script). `uv --version` = 0.13.4 = `UV_VERSION` in `scripts/lock_requirements.py`. Worktree `git log -1` = `0a0c8ad9`, clean before edits.

## Approach

- Empirical test: `uv pip compile --universal --python-version 3.13 --python-platform linux --generate-hashes ...` → uv 0.13.4 rejects the combination (`error: the argument '--universal' cannot be used with '--python-platform <PYTHON_PLATFORM>'`, exit 2). Fallback approach implemented.
- Fallback: new `_reapply_direct_markers(path, project)` in `scripts/lock_requirements.py` re-applies the environment markers of DIRECT dependencies (parsed from pyproject.toml via the existing `_direct_versions`) to the compiled `.lock` lines, after the second-pass `uv pip compile --generate-hashes`, before the sha256 manifest digest. Extends the same mechanism `_write_merged_dev_lock` already uses for `requirements-dev.txt`. Also normalized the existing-pins constraint comparison to compare bare versions (pins in `requirements-dev.lock` may now carry markers). Manifest `platforms` extended to `["linux", "macos", "windows"]` (no schema validator restricts the list; consumers `tests/test_pr025_packaging.py` and `tests/deployment/test_pr008_supply_chain.py` assert python/resolver/digests only).

## Commands run (cwd = worktree) and results

1. `python scripts/lock_requirements.py` (repo venv, uv 0.13.4 on PATH) → exit 0; regenerated requirements.txt, requirements-analytics.txt, requirements-dev.txt, requirements.lock, requirements-dev.lock, config/requirements-lock.json. Output: `re-applied direct-dependency markers to requirements.lock: 1 line(s)` (same for requirements-dev.lock).
2. Marker evaluation (`packaging.markers`, `platform_system != 'Windows'`): linux=True, darwin=True, windows=False → uvloop still installs on Linux/macOS, skipped on Windows.
3. `python -m pip download --require-hashes --only-binary=:all: -r requirements.lock -d %TEMP%\wt679-lock-check` → **exit 0**; 0 uvloop wheels downloaded.
4. Second generator run → `git diff --stat` identical to first run (4 files: config/requirements-lock.json +7/-3... total 6 insertions/5 deletions across the 3 generated artifacts; scripts +46/-2) → deterministic, zero unexpected diff. `requirements.txt` / `requirements-analytics.txt` / `requirements-dev.txt` show byte-identical content (status M was stat-cache only; `git diff --numstat` = empty).

## Diff summary (final)

- `scripts/lock_requirements.py`: +46/−2 (mechanism + platforms list)
- `requirements.lock`: 1 line changed (uvloop marker + hash block intact)
- `requirements-dev.lock`: 1 line changed (same)
- `config/requirements-lock.json`: platforms + digests updated
- New: `tests/test_win01_lock_uvloop_marker.py`, this receipt.

## Verification

- `uvloop==0.22.1 ;platform_system != 'Windows' \` present in both `.lock` files with full `--hash=sha256:` block intact.
- Gates (repo venv, on changed files): black --check = 0, flake8 --max-line-length 140 = 0, mypy --config-file mypy.ini = 0 (script and new test).
- Test receipt: `python -m pytest tests/test_win01_lock_uvloop_marker.py -q` → **4 passed in 0.85s** (pytest.mark.unit).

## Blockers

None.
