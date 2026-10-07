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
