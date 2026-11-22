# OCA-W11B — expanded universal typed graph-query MCP + client handoff

- **Date:** 2026-11-22 · **Branch:** `codex/oca-w11b-mcp-expansion-2026-11-22` — stacked on **PR #702 (W4B, tip `f42601e1`)**; full chain: #684→#685→#686→#700→#702→this. Base main `0a0c8ad9`.

## 1. Delivered — all nine read-only MCP tools (one shared backend)

| Tool | Operation | Notes |
|---|---|---|
| repo_overview | T0 card + store inventory | existing |
| task_context / expand_context | evidence packs / exact refs | existing (W4B token accounting) |
| **graph_query** | typed edge filters, pagination (deterministic offset cursor, `next_cursor`, total) | `repo_graph/query_ops.py` |
| **symbol_search** | exact > prefix > substring > fuzzy (casefold), scope/kind filters, exact ranks first (match_rank) | new |
| **trace_path** | bounded 0–N hop traversal; **unresolved hops returned as-is with `unresolved: true`** — never invented | new |
| **domain_catalog** | provider/lender rows from the canonical catalog resource (`CANONICAL_CATALOG_ROW (not an active connector)`), schemas from graph nodes; strategies → explicit `STRATEGY_CATALOGUE_PENDING_OCA_W4C` | new |
| **impact_query** | reverse callers + tests; **`labelling: STATIC_ONLY`**, `runtime_impact: UNAVAILABLE until OCA-W10` | new |
| **history_query** | local git log per path with cursor; PR/issue feed → `UNAVAILABLE (permission-bounded separate feed)` | new |

Every response carries repo SHA pinning, `graph_generation`, freshness and provenance. `repo_ref`→SHA resolution added on the facade (`resolve_repo_ref`) with **automatic local refresh** (explicit `auto_refresh` flag, one-writer lock file, repo-local artifacts only). **Immutable SHA-bound index publication** (`publish_index`, immutable republish semantics). Client handoff: `client_setup.py` — repo-local stdio config only (`.repo-intel/mcp.json`, no global writes, no credential copying), `health_check` ("installed ≠ connected"), `smoke_test` (subprocess initialize → tools/list (9 tools) → real query).

## 2. Tests (8 new; 12 W11-surface total; 36 chain total)

- pagination + generation stability; exact-first search; unresolved-hop honesty; STATIC_ONLY impact with TESTED_BY direction fix; history permission gate; strategy-catalogue explicit pending; repo_ref resolution incl. **auto-refresh end-to-end (missing index → FRESH)**; publication immutability; subprocess stdio connection smoke (9 tools + real query, `PYTHONPATH`-scoped).
- black/flake8/mypy clean; `scripts/quality_gate.py` PASS; format_targets +3 lines.

## 3. Four completeness levels

INVENTORY/STRUCTURAL unchanged (W0B2); DOMAIN_GRAPH: catalogue scaffolding live, strategy dimension pending W4C; **RUNTIME_LINEAGE: NOT CLAIMED** — runtime/trace/history-runtime dimensions report UNAVAILABLE until W10/W2/W15.

## 4. Blockers

`PRE_EXISTING_WINDOWS_ASYNCIO` (unchanged); PR/issue history feed permission-gated (explicit UNAVAILABLE, not wired).
