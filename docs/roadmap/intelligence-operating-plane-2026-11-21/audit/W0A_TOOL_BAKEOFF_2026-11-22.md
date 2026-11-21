# OCA-W0A — Parallel polyglot code-intelligence and tool bake-off (native baseline)

- **Date:** 2026-11-22
- **Lane:** OCA-W0A (ISOLATED_READ_ONLY_BENCHMARK; WORK_PACKAGE_MATRIX.json, design PR #666 head `6214202b`)
- **Base main SHA:** `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54`
- **Branch:** `codex/oca-w0a-tool-bakeoff-2026-11-22`
- **Mode:** benchmark-only. No runtime dependency added; no external tool installed; no network probes.

## 1. Delivered

| Deliverable | Path |
|---|---|
| Golden-question corpus (42 questions, verified refs) | `benchmarks/intelligence/golden_questions.jsonl` |
| Offline deterministic benchmark harness | `benchmarks/intelligence/run_benchmark.py` |
| Measured baseline reports (500/1000/2000 tokens) | `benchmarks/intelligence/baseline_report_500t.json`, `baseline_report_1000t.json`, `baseline_report_2000t.json` |
| Tool candidate matrix (~30 candidates, pinned roles) | `benchmarks/intelligence/TOOL_CANDIDATE_MATRIX.json` |
| Harness README (run instructions + policy) | `benchmarks/intelligence/README.md` |

## 2. Golden corpus

42 questions spanning the dimensions required by the universal task-context contract: code (10), tests (6), configs (4), strategies (6), providers (6), market_data (3), flash_capital (4), runtime (2), tooling (1). Each row pins `required_refs` that were verified to exist on `0a0c8ad9` before commit (existence check receipts in the lane commit). Every target file was chosen from the OCA-W0 owner inventory (PR #680) so the corpus doubles as a regression set for W0B's graph retrieval.

Answer-level correctness (does the produced pack let an answerer state "producer MISSING" for GQ-003, etc.) is explicitly out of scope here; W4/W7 add answer-level evaluation. UNKNOWN-accuracy measurement is listed as a W4 deliverable, not claimed by W0A.

## 3. Measured native baseline (exact receipts)

Environment: Python 3.13.15, offline, socket-disabled policy honored (pure local file reads). Harness: deterministic lexical scorer (path/name/content term overlap), pack = files that fit the byte budget (tokens×4), plus top-10 exact omitted/expansion refs (`BUDGET_LIMITED`) — silent drops and mid-file truncation are prohibited by construction.

| Budget | Mean required-ref recall | Budget-limited questions | Notes |
|---|---|---|---|
| 500 tokens | 0.6667 | 38/42 | pack ≈ 2.0 files avg |
| 1000 tokens | 0.6667 | 37/42 | pack ≈ 2.5 files avg |
| 2000 tokens | 0.6667 | 37/42 | pack ≈ 2.9 files avg |

- Whole-repo reading baseline: **7,604,448 bytes ≈ 1,901,112 tokens** (labelled byte-estimate, utf-8 bytes/4). A 2000-token pack is a ≥99.8% reduction whenever the required refs are retrieved.
- Tokenizer: byte-estimate only (no model tokenizer installed) — reported as such per the contract.
- All 42 questions' required refs resolved against the checkout (0 unresolved).
- The 14 recall misses are lexical-ranking gaps (token-form mismatches between task text and file identity). This is the measured baseline gap that **OCA-W0B's exact-ID/symbol-graph/FTS5 backend must close: target ≥0.95 recall on this corpus within 2000-token packs**, with ranked omissions.
- Latency recorded in reports as informational only (environment-dependent; excluded from any canonical checksum).

## 4. Tool bake-off decision (zero adoption, evidence-gated)

No external tool was installed or executed. `TOOL_CANDIDATE_MATRIX.json` records ~30 candidates with roles, statuses (`NOT_VERIFIED`, `PATTERN_ADOPTED_LIKE`, `EXCLUDED`) and the exact checks required before any isolated install (license path, telemetry/network audit, isolated HOME profile, MCP/hooks/AGENTS side-effect review, same-SHA golden bake-off). Notable policy outcomes:

- Graph backend: native SQLite + stdlib-AST proceeds (W0B); external graph daemons stay `NOT_VERIFIED` until a measured gap is proven.
- Ranking patterns (Aider RepoMap/PageRank, grep-ast/TreeContext) and incremental patterns (Salsa/Buck2/CocoIndex ideas) are adopted as **patterns implemented natively**, not dependencies.
- Semantic overlays (mimir/growmos variants): ≤1 allowed, never a raw market/quote/PnL store; `NOT_VERIFIED`.
- `jCodeMunch` excluded (no licensing approval); Stack Graphs is archived reference-only.
- Vendor grammar counts and third-party latency benchmarks are not treated as Studious results.

Per the contract, "zero adoption is a valid outcome"; the bake-off gate for external tools reopens only if W4/W7 benchmarks show the native backend misses the ≥0.95 recall / ≤2000-token targets.

## 5. Per-language coverage

Python 3.13 is fully covered by the native stdlib-AST baseline (all corpus targets are Python/config/JSON). YAML/Markdown/JSON are covered as text. Binary/vendor/other-language assets are `UNSUPPORTED` in the harness scope and will be explicit coverage statuses in W0B's inventory — no silent omissions.

## 6. What this lane does not claim

- No recall/precision claims beyond the lexical baseline receipts above.
- No answer-level benchmark, no UNKNOWN-accuracy metric (W4/W7 scope).
- No external-tool performance numbers (none were executed).
- No changes to `src/`, CI, or canonical owners.
