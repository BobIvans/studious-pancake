# OCA-W4B — tokenizer-accurate, loss-aware task context retrieval

- **Date:** 2026-11-22 · **Branch:** `codex/oca-w4b-tokenizer-retrieval-2026-11-22` — stacked on **PR #700 (OCA-W0B2, tip `ac723b4e`)**; chain: #684→#685→#686→#700→this. Base main `0a0c8ad9`.

## 1. Delivered

| Deliverable | Path |
|---|---|
| Tokenizer adapters (labelled fallback + real tokenizer when configured) | `src/intelligence/repo_graph/tokenizers.py` + `[repo-graph-tokenizer]`-style profile string (no new hard dependency; `requirements.lock` untouched) |
| Task-conditioned personalized PageRank (pure Python, bounded boost ≤0.35×, frequency never dominates) | `src/intelligence/repo_graph/ranking.py` |
| Signature/body split with independent hashes | `symbols.py` (`signature_hash`/`body_hash` per symbol) + `store.py` (schema additive) |
| Loss-aware FULL/SKELETON/REFERENCE builder + per-ref token cost | `service.py` (`_skeleton` from recorded symbol ranges — never arbitrary truncation; `_reference` names-only) |
| Tokenizer-accurate benchmark runner | `benchmarks/intelligence/w4b_token_benchmark.py` (new file; no #681 collisions) |
| Tests (7) | `tests/intelligence/test_repo_graph_w4b.py` |

## 2. Measured receipts (pinned SHA `ac723b4e`, real repo, 42-question golden corpus)

| Metric | Value |
|---|---|
| Tokenizer used | **tiktoken:o200k_base (real)** — loaded locally; `tokenizer_uncertainty: exact` |
| Golden recall | **1.0000 (42/42)** |
| **Critical omissions** | **0** (financial needles `10_000`, `fee`, `slippage`, `decimals` verified verbatim in retrieved FULL targets) |
| Whole-repo baseline | 6,164,643 tokens (real tokenizer, same profile) |
| Latency | p50 0.88s / p95 1.11s per question |
| Determinism | two runs → identical recall + pack sizes (`determinism: True`) |

## 3. Contract notes

- Real tokenizer used **only when configured** (`token_profile="tiktoken:o200k_base"`); without a profile → `char-class-estimator-v1` labelled with ±15% uncertainty; a tiktoken load failure degrades explicitly with `degraded_reason: TIKTOKEN_UNAVAILABLE…` (never a silent estimate pretending to be exact).
- Target functions FULL; next-ranked neighbors SKELETON (signature lines **only from recorded symbol ranges** — a fixture invariant asserts every skeleton line ends with `:`), outer neighbors REFERENCE (declared names only); overflow → NEEDS_EXPANSION. No mid-body truncation anywhere.
- PageRank is one bounded signal; exact-ID matches (base score 1000) can never be outranked.
- Same task+SHA+budget+tokenizer → byte-identical packs (fixture-tested).

## 4. Verification (actual counts)

- `pytest tests/intelligence/test_repo_graph_w4b.py …` → **7 passed**; chain total **28 passed** (incl. pre-existing-chain suites; the 3 known Windows-asyncio failures on main unchanged).
- black/flake8/mypy clean; `scripts/quality_gate.py` PASS; format_targets +4 lines.

## 5. Four completeness levels

INVENTORY/STRUCTURAL: unchanged from W0B2 (still claimed); DOMAIN/RUNTIME: not claimed. This lane adds the **token/retrieval accuracy receipts** layer.

## 6. Blockers

- `PRE_EXISTING_WINDOWS_ASYNCIO` (unchanged). tiktoken is NOT added to any lock — used only when configured and locally available (CI runs the labelled estimator; both modes covered by tests).
