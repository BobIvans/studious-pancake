# Codex — Storage Pressure Manager

Target PR branch: `chatgpt/storage-pressure-manager-2026-10-07`.

This PR implements a fail-closed automatic storage-pressure policy over the merged
Local Intelligence V2 owners.

## Required behavior

- <80% managed budget: NORMAL, no action.
- 80–90%: COMPACT — prepare exact Parquet replay and offload only verified eligible raw payloads.
- 90–95%: PRUNE — reclaim more verified eligible inline raw payload bytes.
- >=95%: CRITICAL — same safety gates; if safe reclaim is insufficient, require admission pause.
- Never delete a fixed oldest fraction.
- Never select owner-pinned, evidence-referenced, experiment-pinned, candidate-window,
  young, gap/correction/retraction, replay-mismatch, or otherwise unproven data.
- Laya/model output has no deletion authority.
- Reclaim target is byte-based with hysteresis, not row-count/fraction based.
- Exact payload replay must survive through verified ZSTD Parquet.
- SQLite file shrink is not claimed; inline pages become reusable. No unsafe VACUUM under pressure.

## Review/finish

Re-audit current branch, run Black/mypy and all Local Intelligence tests, fix any
regression, verify CLI `storage pressure` dry-run and execute paths, then let exact-head
CI run. Do not merge until CI is green.


## Final automatic wiring

After the focused manager tests pass, re-audit the current canonical long-running
market/qualification collection owner. Wire one pressure-cycle call at the
supervisor/batch boundary and on typed `AGG02_STORAGE_PRESSURE_ADMISSION_BLOCKED`,
never from inside the AGG-02 append transaction.

Requirements:
- no background thread hidden inside DurableRawJournal;
- at most one pressure cycle at a time;
- NORMAL performs no I/O mutation;
- COMPACT/PRUNE/CRITICAL use the same verified receipts as the CLI;
- CRITICAL shortfall pauses new collection and surfaces a durable blocker;
- restart/retry is idempotent by pressure batch/receipt identity;
- if no canonical long-running owner exists yet, leave the callable + CLI complete
  and record the runtime trigger as BLOCKED_NOT_WIRED rather than inventing a new scheduler.
