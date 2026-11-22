# OCA-W4 — adaptive retrieval hardening (golden receipts)

- **Date:** 2026-11-22
- **Lane:** OCA-W4 (READ_ONLY_QUERY_API hardening; WORK_PACKAGE_MATRIX.json, design PR #666 head `6214202b`)
- **Branch:** `codex/oca-w4-adaptive-retrieval-2026-11-22` — **stacked on PR #684 (OCA-W0B)**, which is unmerged pending human approval; this PR shows W0B's commit plus the W4 commit until #684 merges, then rebases onto main.
- **Base chain:** main `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54` → #684 tip → this lane.

## 1. Delivered

| Deliverable | Path |
|---|---|
| Deterministic task-type router (`bug/test/provider/strategy/refactor/architecture/generic`) with prefix-based boosts | `src/intelligence/repo_graph/service.py` (`detect_task_type`, `TASK_TYPE_BOOSTS`) |
| Directory-ref resolution (`must_include_refs` accepting directories; envelope reports `resolved_directory_refs`) | `service.py` (`_resolve_directory_refs`) |
| Continuation cursor (`continuation_cursor` in/out, task-hash bound, stale cursor raises) | `service.py` |
| W4 contract tests (4) | `tests/intelligence/test_repo_graph_w4.py` |
| Golden recall receipt post-hardening | `W4_GOLDEN_RECALL.json` |
| Lane receipt | `W4_RECEIPT.json` |

Boosts reorder retrieval only; they never promote provenance/verification state (contract §1.5/§4).

## 2. Measured results (pinned main `0a0c8ad9`, 2000-token budget)

| Metric | OCA-W0B (baseline of this lane) | OCA-W4 |
|---|---|---|
| Golden-corpus recall (42 questions) | 0.9286 (39/42) | **1.0000 (42/42)** |
| Measurement latency | ~12.4s | ~15.2s |
| Backend | `QueryBackend` exact-ID/FTS/path | same + directory-aware refs + task-type boosts |

All three W0B misses were directory-type required refs (`tests/observability`, `src/strategy/relation_generators`, `src/gpr_sui_shadow`); directory-aware ref resolution closes exactly those. Target ≥0.95 met. The directory-hit rule is recorded in the receipt (a directory ref counts as retrieved when a contained tracked file is in included/omitted refs — the API never silently drops it either way).

## 3. Contract notes

- Router is deterministic keyword/prefix logic — no embeddings, no model calls; semantic fallback remains unbuilt and unneeded at this recall.
- Continuation cursor is task-hash + repo-SHA bound; a stale/mismatched cursor raises instead of silently returning foreign slices.
- Budget overflow behavior unchanged: exact omitted refs + `next_expansions`, never mid-file truncation.
- One backend: CLI, this service, and (next lane) W11 MCP all call `QueryBackend.task_context/expand_context`.

## 4. Verification

- `pytest tests/intelligence/test_repo_graph_w4.py -q --disable-socket --allow-unix-socket` → **4 passed**.
- `pytest tests/intelligence -q ...` → 58 passed, 3 failed (same pre-existing Windows-asyncio failures on clean main; unchanged from #684).
- `black --check` / `flake8` / `mypy` clean; `config/format_targets.txt` +1 line.

## 5. Scope note

W4's operation-context pack parts (per WORK_PACKAGE_MATRIX) depend on OCA-W2 (`operation_context`), which is dependency-blocked; the retrieval hardening delivered here is the W0B-backend portion the user sequenced. Not silently skipped — recorded as dependency-blocked.
