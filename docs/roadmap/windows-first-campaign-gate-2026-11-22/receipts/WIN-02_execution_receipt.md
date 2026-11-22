# WIN-02 Execution Receipt — narrow socketpair exemption for Proactor self-pipe

- **Branch:** `codex/679-win-socket-2026-11-22` (base = main `0a0c8ad9`)
- **Head after push:** `ca2297588b625f6af3fd8b6d2376df512a4ce1c7`
- **Worktree:** `sp-worktrees/wt679-win-socket`
- **Python:** 3.13.15 (`studious-pancake/.venv/Scripts/python.exe`), Windows native
- **PR:** none (per task instructions)

## Changes

- `tests/conftest.py`: capture `_PRISTINE_SOCKET` / `_PRISTINE_SOCKETPAIR` at module import; install `_guarded_socketpair` as `socket.socketpair` which temporarily restores the pristine `socket.socket` class around the socketpair call only. Existing `CompatibilityEventLoopPolicy` and `pytest_configure` hook unchanged. No `--allow-hosts`, no broad AF_INET allowance, no loopback/DNS/TCP/UDP exemption.
- `tests/test_win02_proactor_socket_bootstrap.py` (new): 4 regression tests (unit mark, offline, fast). Guard-active tests skip at runtime when pytest-socket's per-test guard is inactive.
- `config/format_targets.txt`: added the new test file.

## Commands and results

| Command | Result | Exit |
| --- | --- | --- |
| `python -m pytest tests/test_win02_proactor_socket_bootstrap.py --disable-socket --allow-unix-socket -q` | 4 passed in 0.48s | 0 |
| `python -m pytest tests/test_win02_proactor_socket_bootstrap.py -q` (no flags) | 2 passed, 2 skipped (skip path verified) | 0 |
| `python -m pytest tests/test_qpr03_source_intake.py tests/test_qpr02_data_plane.py tests/test_din01_bounded_discovery.py --disable-socket --allow-unix-socket -q` | 34 passed in 21.88s | 0 |
| `python -m black tests/conftest.py tests/test_win02_proactor_socket_bootstrap.py` | 2 files left unchanged | 0 |
| `python -m flake8 --max-line-length 140 <changed files>` | clean | 0 |
| `python -m mypy --config-file mypy.ini <changed files>` | Success: no issues found in 2 source files | 0 |
| `git push origin codex/679-win-socket-2026-11-22` | new branch pushed | 0 |

## Before/after (representative set)

Baseline classification (`.zcode/pr664/baseline_classification.json`, #670 Windows baseline, fixture-setup errors from SocketBlockedError):

- `tests/test_qpr03_source_intake.py`: before 10 failed → after 0 failed (passed in set)
- `tests/test_qpr02_data_plane.py`: before 11 failed → after 0 failed
- `tests/test_din01_bounded_discovery.py`: before 3 failed → after 0 failed

Combined representative set: 34 passed, 0 errors after fix.

## Notes

- pytest-socket 0.7.0 applies GuardedSocket per-test via its autouse fixture (not at import), so guard detection in the regression tests is a runtime check (`socket.socket is not _PRISTINE_SOCKET`), not a module-level skipif.
- mypy required `# type: ignore[misc]` on the two `socket.socket` reassignments ("Cannot assign to a type").
- Full suite intentionally not run (integration phase does that).

## Blockers

None.
