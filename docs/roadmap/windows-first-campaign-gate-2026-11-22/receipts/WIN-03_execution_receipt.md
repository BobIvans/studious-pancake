# WIN-03 Execution Receipt

Defect: WINDOWS_SQLITE_TEMP_CLEANUP_PERMISSION — `scripts/verify_occ_durable_host.py`
fails on native Windows with `PermissionError [WinError 32]` deleting
`content.sqlite3` inside `TemporaryDirectory`.

Root cause: `src/occ_durable_library.py` used `with self._connect() as connection:`
at four sites. The sqlite3 connection context manager commits/rolls back but never
closes, leaving OS file handles to GC — on Windows, open handles block deletion.

## Connection sites found (`_connect(` in src/occ_durable_library.py)

| Site | Status before | Fix |
|---|---|---|
| `src/occ_durable_library.py:76` `_connect()` (factory) | n/a | unchanged |
| `src/occ_durable_library.py:82` `_initialize()` | open, never closed | `contextlib.closing(...)` + `with connection:` |
| `src/occ_durable_library.py:150` `sync()` | already correct (`connection.close()` in `finally`) | unchanged |
| `src/occ_durable_library.py:247` `get_version()` | open, never closed | `contextlib.closing(...)` + `with connection:` |
| `src/occ_durable_library.py:284` `latest()` | open, never closed | `contextlib.closing(...)` + `with connection:` |
| `src/occ_durable_library.py:329` `history()` | open, never closed | `contextlib.closing(...)` + `with connection:` |

(Line numbers are pre-fix; post-fix the four sites use
`with contextlib.closing(self._connect()) as connection, connection:` — exact
commit/rollback semantics preserved, no `ignore_errors`, no retries, no suppression.)

## Other sqlite handles in the verify flow

- `scripts/run_occ_native_host.py:177` constructs a second `OCCDurableLibrary(context_db)`
  — all its call paths now close explicitly; no direct `sqlite3.connect` outside the
  library (grep confirmed). No journal/WAL files are left open (default journal mode,
  connections closed before `TemporaryDirectory` cleanup).
- `scripts/verify_occ_durable_host.py` opens no sqlite handles of its own.

## New regression test

`tests/test_win03_occ_sqlite_close.py` (pytestmark = pytest.mark.unit, offline,
Windows + Linux safe):

1. `test_temporary_directory_cleanup_after_full_use_releases_handles` — sync() twice
   + get_version/latest/history, then `td.cleanup()` while the library object is
   still referenced; looped 3x; must not raise WinError 32.
2. `test_read_methods_release_handles_immediately` — after read methods return,
   `path.unlink()` succeeds immediately without `gc.collect()`.
3. `test_sync_history_round_trip_preserved` — one real sync + history round-trip
   asserts CREATED/UPDATED outcomes and event_seq 1, 2.

`tests/test_win03_occ_sqlite_close.py` added to `config/format_targets.txt`.

## Commands and exit codes

| Command | Exit code |
|---|---|
| `python scripts/verify_occ_durable_host.py` (worktree cwd) | 0 |
| `python -m pytest tests/test_win03_occ_sqlite_close.py tests/test_occ_durable_host.py tests/test_occ_memory_qualification_bridge.py -q` | 0 (29 passed) |
| `python -m black --check src/occ_durable_library.py tests/test_win03_occ_sqlite_close.py` | 0 |
| `python -m flake8 --max-line-length 140 <changed files>` | 0 |
| `python -m mypy --config-file mypy.ini <changed files>` | 0 (no issues) |

## verify_occ_durable_host.py output tail

```
{"delegated_owner":"scripts.run_qualification_task","duplicate_sync_noop":true,"errors":[],"exact_head_ci_embedded":false,"live_authorized":false,"namespace_guarded":true,"ok":true,"registered_action_only":true,"release_authorized":false,"schema_version":"occ.durable-host-verification.v1"}
VERIFY_EXIT=0
```

## Base and head

- Base: main `0a0c8ad9`
- Head SHA after push: see commit `fix(win-03): close OCCDurableLibrary sqlite connections to fix Windows temp cleanup` on `origin/codex/679-win-occ-2026-11-22`

## Blockers

None.
