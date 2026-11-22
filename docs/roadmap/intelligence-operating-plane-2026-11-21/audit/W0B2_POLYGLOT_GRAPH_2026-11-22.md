# OCA-W0B2 — complete repository coverage and polyglot structural graph

- **Date:** 2026-11-22
- **Lane:** OCA-W0B2 (POLYGLOT_GRAPH_AND_ASSET_EXTRACTORS; WORK_PACKAGE_MATRIX.json v2 at design head `f7c09b81436e9a16c89a680ce314937fc6a52fa4`)
- **Branch:** `codex/oca-w0b2-polyglot-graph-2026-11-22` — **stacked on chain-A tip #686** (`2c8cd383`, contains W0B+W4+W11); base main `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54`.

## 1. Reconciliation (PRs #680–#690 — see `W0B2_RECONCILIATION_RECEIPT.json`)

All ten PRs OPEN/MERGEABLE on `0a0c8ad9`; remote heads equal local tips; `git merge-base --is-ancestor` proves chain A (#684→#685→#686) and chain B (#689→#690) exactly as previously claimed — **no correction needed**. CI green on sampled PRs. Overlaps: only `config/format_targets.txt` EOF-appends (trivial); all other write scopes distinct; zero canonical-owner modifications. W13/W14/W1/W3 are delivered by open PRs #689/#690/#687/#688 — not re-implemented.

## 2. Delivered

| Deliverable | Path |
|---|---|
| Artifact-class classifier (14 classes) + first-party/vendor rules | `src/intelligence/repo_graph/extractors.py` (`classify_artifact`) |
| Expanded coverage statuses (STRUCTURE_INDEXED/TEXT_INDEXED/METADATA_ONLY/PARTIAL/…) | `src/intelligence/repo_graph/schema.py` |
| Tree-sitter adapters, import-guarded, pinned | `src/intelligence/repo_graph/parsers.py` + `[repo-graph-parsers]` pyproject extra (`tree-sitter==0.25.2`, bash `0.25.1`, yaml `0.7.2`, markdown `0.5.4`; all MIT; `requirements.lock` untouched) |
| Stdlib structured extractors (json/toml/ini/dependency-pins/markdown/workflow-fallback) — keys/names only, never values | `src/intelligence/repo_graph/extractors.py` |
| Polyglot build integration (per-file status decision, `_index_non_python`, cross-language node records `<lang>::<path>::<qualified>`) | `src/intelligence/repo_graph/graph_build.py` |
| Polyglot + multi-language golden tests (7) | `tests/intelligence/test_repo_graph_polyglot.py` |
| SCIP/LSP measured decision | `W0B2_SCIP_LSP_DECISION.md` |
| CI (with-grammars + grammar-absent fallback + determinism + nightly) | `.github/workflows/repo-intelligence-polyglot.yml` |
| Receipts | `W0B2_RECONCILIATION_RECEIPT.json`, `W0B2_DETERMINISM_COVERAGE_PROOF.json`, `W0B2_RECEIPT.json` |

## 3. Language inventory (detected from the tree, not from popularity)

| Language | Files | Decision | Parser |
|---|---|---|---|
| Python (first-party, 1,851 modules) | majority of 3,421 tracked | STRUCTURE_INDEXED | native stdlib-AST (primary, unchanged) |
| YAML (workflows + configs) | ~160 workflows + config rows | STRUCTURE_INDEXED | tree-sitter-yaml (workflow jobs via grammar spec; line-based fallback is deterministic and recorded via `parser` field) |
| Markdown (docs/ADRs) | docs tree | STRUCTURE_INDEXED | regex heading/link extractor (deterministic; tree-sitter-markdown available) |
| JSON (configs/schemas/fixtures) | ~55 under src/ + more | STRUCTURE_INDEXED / PARSE_ERROR explicit | stdlib `json` |
| TOML/INI (build/config) | pyproject + *.toml/*.ini/*.cfg | STRUCTURE_INDEXED | stdlib `tomllib` / `configparser` |
| Bash (scripts) | scripts/*.sh | STRUCTURE_INDEXED with grammar; explicit `PARTIAL: TREE_SITTER_GRAMMAR_ABSENT` without | tree-sitter-bash |
| Rust | 2 vendor contract snapshots (`src/resources/contracts/marginfi/*.rs`) | **METADATA_ONLY** — vendor-reference decision, no parse; first_party=False | none (recorded) |
| Binaries/other | e.g. blob assets | UNSUPPORTED `LANGUAGE_other` | — |
| Secrets (.env-like) | excluded upstream | EXCLUDED_WITH_REASON | repo_snapshot policy |

No silent "other" bucket: every tracked path gets exactly one coverage row with status, artifact_class, language, first_party, parser and reason fields.

## 4. Determinism and coverage receipts (real main, grammars installed)

See `W0B2_DETERMINISM_COVERAGE_PROOF.json`: two clean builds → equal canonical checksum; counts recorded; per-status and per-artifact-class counters; rows-without-status count (must be 0 → INVENTORY_COMPLETE). Fixture-level proofs: clean-vs-incremental parity and rename handling re-verified on the polyglot fixture (existing chain-A tests), multi-language golden retrieval questions (workflow/config/doc/dependency-lock) retrieve their targets through the same `QueryBackend`.

## 5. SCIP/LSP

`NOT_ADOPTED_NO_REPRODUCIBLE_INDEXER` with reproduction commands and a re-open gate (see `W0B2_SCIP_LSP_DECISION.md`). Zero adoption valid per matrix guardrails.

## 6. Four completeness levels (reported separately, not collapsed)

- **INVENTORY_COMPLETE:** yes — every tracked path one coverage record (receipt counter `rows_without_status: 0`).
- **STRUCTURAL_GRAPH_COMPLETE:** per-language — python/yaml/json/toml/ini/markdown/bash STRUCTURE_INDEXED (with recorded parser identity); rust vendor METADATA_ONLY (explicit decision); anything grammar-absent → explicit PARTIAL with reason+owner. No unqualified "100% polyglot complete" badge.
- **DOMAIN_GRAPH_COMPLETE:** not claimed this lane (W4C).
- **RUNTIME_LINEAGE_COMPLETE:** not claimed (W10/W2 pending; W20 later).

## 7. Tests + gates (actual counts)

- `pytest tests/intelligence/test_repo_graph_polyglot.py tests/intelligence/test_repo_graph.py -q --disable-socket --allow-unix-socket` → **12 passed**; full `tests/intelligence` batch → 61 passed + 3 pre-existing Windows-asyncio failures (unchanged from main, blocker `PRE_EXISTING_WINDOWS_ASYNCIO`).
- black/flake8/mypy clean on all touched files; `scripts/quality_gate.py` PASS; format_targets +5 lines.

## 8. Blockers

- `PRE_EXISTING_WINDOWS_ASYNCIO` (unchanged, pre-existing on main).
- Grammar-absent environments produce explicit PARTIAL rows (CI proves both modes; extra installed in the polyglot workflow only — no lock changes).
