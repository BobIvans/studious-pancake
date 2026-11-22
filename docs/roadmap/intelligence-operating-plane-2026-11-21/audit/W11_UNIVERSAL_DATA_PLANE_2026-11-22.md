# OCA-W11 — unified read-only data plane, portable export, allowlisted MCP

- **Date:** 2026-11-22
- **Lane:** OCA-W11 (READ_ONLY_CROSS_OWNER_PROJECTION_AND_EXPORT; WORK_PACKAGE_MATRIX.json, design PR #666 head `6214202b`)
- **Branch:** `codex/oca-w11-readonly-mcp-2026-11-22` — **stacked on PR #685 (OCA-W4)**, itself stacked on **PR #684 (OCA-W0B)**; both unmerged pending human approval. Review order: #684 → #685 → this PR; rebases onto main after each merge.
- **Base main:** `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54`.

## 1. Delivered

| Deliverable | Path |
|---|---|
| Store inventory + facade over the single backend | `src/intelligence/universal_data_plane/__init__.py`, `facade.py` |
| Allowlisted read-only MCP server (stdlib JSON-RPC over stdio) | `src/intelligence/universal_data_plane/mcp_server.py` |
| Portable SHA-bound context-pack export | `facade.export_context_pack` |
| Tests (4) | `tests/intelligence/test_universal_data_plane.py` |
| Lane receipt | `W11_RECEIPT.json` |

## 2. Single backend (no divergent engines)

`UniversalDataPlane.task_context/expand_context/repo_card` delegate directly to `repo_graph.service.QueryBackend` — the same functions the CLI calls. The MCP server exposes exactly three tools (`task_context`, `expand_context`, `repo_overview`) whose handlers are thin wrappers over the facade. No retrieval logic exists anywhere outside `QueryBackend`.

## 3. MCP surface (allowlisted, read-only)

- Protocol: JSON-RPC 2.0 line-delimited; `initialize`, `tools/list`, `tools/call`; unknown tool → `-32602`; unknown method → `-32601`; notifications produce no response.
- Exposed tools: `task_context`, `expand_context`, `repo_overview` — **only**. No shell, edit, delete, admin, signer, sender, borrowing, spending, deployment, provider-enablement, or LIVE capability is reachable from the server (grep-verifiable: the module has no subprocess, no os.system, no file-write outside the caller-requested export path API in the facade).
- Unknown/absent SHA → `status UNAVAILABLE/STALE` in a normal tool response, never an exception or fabricated data (honesty rule §6 of the universal API contract).

## 4. Store inventory and honest unavailability

`STORES` records the canonical owner and read status per store: `repo_graph` (derived view, AVAILABLE), `observability` (**READ_READY_NO_PRODUCERS** — per OCA-W0 trace, PR #680: zero production producer callsites), `market_observation`, `agg02`, `flash_capital` (AVAILABLE via their canonical read APIs). Runtime/trace dimensions report UNAVAILABLE until OCA-W10 wires producers; the facade marks `source_fallback_required` when a stale/missing index is hit, per contract §6.

## 5. Portable export

`export_context_pack(envelope, out)` writes a JSON bundle: schema `studious.universal-data-plane.v1.context-pack`, full envelope manifest, resolved contents (sorted), and `pack_sha256` over the canonical serialization (no timestamps in the hash). New chats receive data via this pack, authorized GitHub access, or a connected local MCP — never implicit disk access.

## 6. Scope note (dependency-scoped delivery)

Full W11 also includes cross-store bitemporal joins (needs OCA-W2 projection) and runtime replay (needs OCA-W10). Those are dependency-blocked, recorded here and in the receipt — the facade structure is ready to add those projections behind the same interface once their owners land. Not silently skipped.

## 7. Verification

- `pytest tests/intelligence/test_universal_data_plane.py -q --disable-socket --allow-unix-socket` → **4 passed**.
- Combined W0B+W4+W11: `pytest tests/intelligence/test_repo_graph.py tests/intelligence/test_repo_graph_w4.py tests/intelligence/test_universal_data_plane.py` → **16 passed**.
- `black --check` / `flake8` / `mypy` clean; 4 new lines in `config/format_targets.txt`; `scripts/quality_gate.py` PASS.

## 8. Safety

Read-only surfaces only; no subprocess/network in the MCP server; no secrets in packs (inherited snapshot exclusion); LIVE hard-denied; execution_authority NONE.
