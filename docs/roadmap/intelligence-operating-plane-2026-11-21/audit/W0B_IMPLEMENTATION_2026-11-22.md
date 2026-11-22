# OCA-W0B — deterministic repo graph + task_context/expand_context (implementation)

- **Date:** 2026-11-22
- **Lane:** OCA-W0B (ADDITIVE_DEV_INTELLIGENCE_IMPLEMENTATION; WORK_PACKAGE_MATRIX.json, design PR #666 head `6214202b`)
- **Base main SHA:** `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54`
- **Branch:** `codex/oca-w0b-deterministic-repo-graph-2026-11-22`
- **Contracts honored:** `LLM_FREE_DETERMINISTIC_INDEXING_CONTRACT_RU.md` + `UNIVERSAL_TASK_CONTEXT_API_RU.md`. Inputs consumed from audit lanes: #680 (OCA-W0 owner inventory), #681 (OCA-W0A golden corpus), #682 (OCA-W0C inventory).

## 1. Delivered

| Deliverable | Path |
|---|---|
| Versioned graph schema + canonical serialization | `src/intelligence/repo_graph/schema.py` (`studious.repo-graph.v1`) |
| Coverage inventory (no silent omissions) | `src/intelligence/repo_graph/inventory.py` |
| Python AST symbols (qualified names, scopes, byte ranges, stable IDs) | `src/intelligence/repo_graph/symbols.py` |
| Provenance-typed edges (DEFINES/IMPORTS/CALLS_RESOLVED/CALLS_STATIC/TESTED_BY) | `src/intelligence/repo_graph/edges.py` |
| Content-addressed parse cache + rename/delete classification | `src/intelligence/repo_graph/incremental.py` |
| Build pipeline (snapshot → inventory → parse → edges → artifact) | `src/intelligence/repo_graph/graph_build.py` |
| Content-addressed artifact store + SQLite/FTS5 derived cache | `src/intelligence/repo_graph/store.py` |
| **Single query backend**: `task_context` / `expand_context` / `repo_card` | `src/intelligence/repo_graph/service.py` |
| Read-only CLI (`build/card/task-context/expand-context/verify`) | `src/intelligence/repo_graph/cli.py` |
| Contract tests (8) | `tests/intelligence/test_repo_graph.py` |
| CI workflow incl. nightly reconciliation | `.github/workflows/intelligence-repo-graph.yml` |
| Receipts | `W0B_DETERMINISM_PROOF.json`, `W0B_GOLDEN_RECALL.json`, `W0B_RECEIPT.json` |

**Reuse (no duplicate owners):** snapshotting/secret-exclusion via `repo_snapshot.start_snapshot`/`verify_snapshot_roundtrip`; import resolution mirrors `repo_source` semantics; deterministic receipts via `intelligence.common`; relative-import handling kept identical to the CTX-02 primitive. Canonical stores untouched; the graph is a derived read-only view with no runtime dependency on strategy/provider owners.

## 2. Contract compliance (gate-by-gate)

- **LLM-free build:** no model packages, credentials, prompts, embeddings, or network calls anywhere in `repo_graph/` (stdlib `ast`, `sqlite3`, `hashlib`, `json` + existing snapshot primitives). CI runs contract tests with `--disable-socket`.
- **Determinism (real repo, pinned main `0a0c8ad9`):** two clean builds → **byte-identical canonical records and equal checksum `e7da461d644da73e…`**; equal generation identity. 3421 tracked files, 1851 modules parsed, 26,772 nodes, 71,812 edges (receipt: `W0B_DETERMINISM_PROOF.json`). Wall-clock fields live only in non-canonical receipts.
- **No silent omissions:** every tracked file carries a coverage status (`INDEXED` / `UNSUPPORTED`+reason / `EXCLUDED_WITH_REASON` / `PARSE_ERROR` / `UNCLASSIFIED`); fixture-tested for secret files (`.env` → `EXCLUDED_WITH_REASON`), binaries (`UNSUPPORTED`), config/text (`INDEXED`).
- **Clean-vs-incremental parity:** fixture tests prove equal checksums after add, modify, rename (`git mv` → explicit `renamed` records from blob identity), and delete. Blob-sha cache keys (never path/mtime); parser-version change invalidates the cache.
- **Stale-SHA rejection:** `task_context`/`expand_context` return `STALE`/`UNAVAILABLE` with `included_refs: []` for a SHA without an artifact; fixture-tested; CI-gated.
- **Dangling edges:** SQLite check `every edge endpoint resolves to a node` = **0** on the real-repo artifact (CI-gated). Unresolved call targets are attached to the caller's module node with `target_expr` evidence and `resolution: UNRESOLVED` — never fabricated node links.
- **No auto-promotion:** `CALLS_RESOLVED` requires structural evidence (same-module symbol or exact imported module root); same-name guesses stay `CALLS_STATIC`/`UNRESOLVED`; provenance is `STATIC_EXTRACTED` only. No `RUNTIME_OBSERVED` claims anywhere (zero producers exist per #680).
- **Secret exclusion:** inherits `repo_snapshot._secret`/`_secret_bytes` metadata-only policy; CI re-scans canonical records for secret patterns.
- **Token budget:** `task_context` packs target files FULL within budget; oversized targets become exact `omitted_refs` + `next_expansions` (`BUDGET_LIMITED`) — never mid-file truncation; tokenizer is labelled byte-estimate.

## 3. Universal task-context API (W0B minimal surface)

- `task_context(task, repo_sha, budget_tokens, dimensions, must_include_refs, exclude_refs)` → envelope: `status` (FRESH/BUDGET_LIMITED/STALE/UNAVAILABLE), repo SHA + graph generation + freshness, included/omitted refs, `next_expansions`, graph neighbours, tokenizer identity, token estimate.
- `expand_context(refs, repo_sha, depth)` → exact file payloads or exact symbol byte-slices by stable ID (`py::<path>::<qualified>`), `missing_refs` explicit, same-SHA pinning.
- Retrieval route: exact/must-include refs → identifier/FTS lexical (SQLite FTS5 over nodes) → path-term scoring → TESTED_BY neighbour expansion. Deterministic ordering; no embeddings.
- One backend: CLI (this lane) calls the same `QueryBackend`; W4 hardens ranking, W11 exposes it via MCP — no divergent engines.

## 4. Retrieval accuracy receipts (golden corpus, OCA-W0A)

Real-repo measurement through the new backend at 2000-token budget: **39/42 = 0.9286 recall** (vs 0.6667 lexical baseline at the same budget; whole-repo read ≈ 1.9M tokens). All 3 misses are directory-type required refs (`tests/observability`, `src/strategy/relation_generators`, `src/gpr_sui_shadow`) where the pack is file-granular — recorded in `W0B_GOLDEN_RECALL.json` and queued as the first W4 item (directory-aware ref resolution → target ≥0.95). Latency for the full 42-question run: ~12s.

## 5. Verification (exact commands + counts)

- `pytest tests/intelligence/test_repo_graph.py -q --disable-socket --allow-unix-socket` → **8 passed**.
- `pytest tests/intelligence -q --disable-socket --allow-unix-socket` → 54 passed, 3 failed — the 3 failures (`test_pressure_manager`, `test_rpc_campaign` ×2) are **pre-existing on clean main `0a0c8ad9`** (Windows ProactorEventLoop asyncio teardown, known Windows debt; reproduced on the `oca-w0` main worktree). Unrelated to this lane; recorded as blocker `PRE_EXISTING_WINDOWS_ASYNCIO`.
- `black --check` / `flake8` / `mypy` clean on all 11 new files; `scripts/quality_gate.py` passes with `config/format_targets.txt` registration (+11 lines).

## 6. Blockers

- `PRE_EXISTING_WINDOWS_ASYNCIO` — 3 pre-existing test failures on main; not introduced by this lane (CI runs Ubuntu).
- W4 item: directory-ref recall (0.9286 → ≥0.95).

## 7. Safety

No signing/sending/borrowing/spending/deployment/provider-enablement; LIVE hard-denied; no secrets in graph records (CI-gated); query surface read-only; build writes only local derived artifacts under the state root; no canonical-owner mutations.
