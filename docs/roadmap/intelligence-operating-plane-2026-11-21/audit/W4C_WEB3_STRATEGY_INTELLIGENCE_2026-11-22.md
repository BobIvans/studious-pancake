# OCA-W4C — Web3 strategy intelligence: catalogue, comparison and evidence query tools

- **Date:** 2026-11-22 · **Branch:** `codex/oca-w4c-web3-strategy-intel-2026-11-22`
- **Branch construction:** real merge commit joining chain A (#684→#685→#686→#700→#702→#703: graph/retrieval/MCP) with chain B+W2+W10+W15+W18+W20 (#689→#690→#704→#707→#709→#706→#713: contracts, episodes, capture, ontology, verification, diagnostics). Review order = the chain above; rebases as parents merge. Base main `0a0c8ad9`.

## 1. Delivered

| Deliverable | Path |
|---|---|
| Evidence-linked strategy catalogue (six-source union, lifecycle states) | `src/intelligence/universal_data_plane/strategy_catalog.py` |
| Seven operations over the shared backend | `src/intelligence/universal_data_plane/web3_tools.py`: `strategy_research{catalog,context,compare}` + `web3_data_trace{provider_trace,flash_capital_trace,operation_trace,performance_diagnostics}` |
| Two compact MCP tools (11 total allowlisted; no third Web3 schema) | `mcp_server.py` |
| Tests (6) incl. golden probes | `tests/intelligence/test_web3_strategy_tools.py` |
| Real-repo catalogue receipt | `W4C_CATALOG_RECEIPT.json` |

## 2. Contract compliance

- **Catalogue:** union of six sources (graph first-party symbols under strategy/planning/paper_shadow, canonical registries via merged chain B, configs, TESTED_BY tests, doc headings under `docs/strategy-expansion/`, permission-gated history); distinct lifecycle states (IMPLEMENTED/TESTED/DOC_ONLY/QUALIFICATION_PENDING…); doc-only discovery keeps `NOT_APPLICABLE (doc-only discovery is not a working strategy)`; unknowns preserved (capital_model/providers/data_requirements UNKNOWN until evidenced).
- **strategy_context:** exact FULL source for the target module (financial semantics never compressed); UNKNOWN for refs not in the catalogue.
- **strategy_compare:** shared vs unique aliases/entrypoints; novelty labels `RELATED_VARIANT`/`DISTINCT_CANDIDATE`/`INSUFFICIENT_EVIDENCE` — evidence-backed classification only.
- **provider_trace:** declared/configured/tested/captured/runtime-observed strictly separated (`runtime_observed: false` — a catalog row never implies live capability).
- **flash_capital_trace:** `effective_capacity: UNKNOWN (advertised liquidity is not flash-borrow capacity)`; fee/repayment semantics UNKNOWN without pinned contract evidence.
- **operation_trace:** PARTIAL over real W2 episodes from the W10-captured durable store (real producers on this branch); missing callsite linkage recorded.
- **performance_diagnostics (7th operation):** W20's build_diagnostics via the same backend; explicitly `no third MCP schema`.
- All tools read-only; zero fabricated runtime/provider/qualification claims (fixture-asserted `runtime_observed is False`).

## 3. Verification (actual counts)

- `pytest tests/intelligence/test_web3_strategy_tools.py -q --disable-socket --allow-unix-socket` → **6 passed**; merged-branch suite → 25 passed (chain B/W lanes) + chain A suites green.
- Real-repo catalogue receipt: per-class counts + sample compare novelty label (`W4C_CATALOG_RECEIPT.json`).
- black/flake8/mypy clean; `scripts/quality_gate.py` PASS; format_targets +3 lines.

## 4. Four completeness levels

- **INVENTORY_COMPLETE:** yes (W0B2 receipts).
- **STRUCTURAL_GRAPH_COMPLETE:** per-language claims (W0B2), unchanged.
- **DOMAIN_GRAPH_COMPLETE:** claimed **for discovered dimensions** — strategy catalogue (implemented/doc-only counts in receipt), providers/lenders (canonical catalog rows), schemas (graph nodes); per-dimension, not a blanket "domain complete".
- **RUNTIME_LINEAGE_COMPLETE:** partial — the supported atomic vertical is WIRED with operation_trace + performance_diagnostics proven end-to-end; all other routes stay explicit NO_RUNTIME_PATH/BLOCKED per the W10 coverage matrix. Full-bot claim forbidden.

## 5. Blockers

- `PRE_EXISTING_WINDOWS_ASYNCIO` (unchanged).
- Per-card W14 requirement binding and git-history novelty signals: follow-up scope, reason-coded as PENDING.
