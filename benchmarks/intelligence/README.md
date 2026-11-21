# benchmarks/intelligence — OCA-W0A golden retrieval benchmark (native baseline)

Scope: OCA-W0A (ISOLATED_READ_ONLY_BENCHMARK) from `WORK_PACKAGE_MATRIX.json`
(design PR #666, head `6214202b`). Base main: `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54`.

## Contents

- `golden_questions.jsonl` — 42 golden questions across code / tests / configs /
  strategies / providers / market_data / flash_capital / runtime / tooling
  dimensions. Every `required_refs` path was verified to exist on the pinned SHA
  before commit. Ground truth is `KNOWN` with explicit refs; `UNKNOWN` accuracy
  evaluation (answer-level correctness) is a W4/W7 extension — this harness
  measures retrieval reachability only.
- `run_benchmark.py` — offline deterministic lexical baseline: tokenized task →
  path/name/content term scoring → bounded pack (files that fit) plus exact
  omitted/expansion refs (top 10, `BUDGET_LIMITED`) — never silent drops, never
  mid-file truncation. Byte-estimate tokenizer (utf-8 bytes / 4), labelled as
  such; no model tokenizer, embeddings, or network access.
- `baseline_report_{500,1000,2000}t.json` — measured baseline runs on the
  pinned checkout (2026-11-22, Python 3.13.15).

## Measured baseline (exact receipts)

| Metric | Value |
|---|---|
| Questions | 42 |
| Tracked text files scored | 3478 |
| Whole-repo size (retrieval baseline to replace) | 7,604,448 bytes ≈ **1,901,112 tokens** (byte-estimate) |
| Pack budget cap | 500 / 1000 / 2000 tokens |
| Mean required-ref recall (pack ∪ top-10 expansion refs) | **0.6667 / 0.6667 / 0.6667** |
| Budget-limited questions | 37–38 of 42 |
| Unresolved required refs | 0 |

The 14 missed questions are pure lexical-ranking gaps (e.g. "JSON resource that
catalogs market sources" vs `src/resources/market_source_catalog.json` —
token-form mismatch), which is the measured motivation for OCA-W0B's exact-ID /
symbol-graph / FTS retrieval backend: target ≥0.95 recall on this corpus within
2000-token packs, with ranked omissions instead of silent loss.

Token-savings framing: replacing a whole-repo read (≈1.67M tokens) with a
2000-token pack + expansion refs is a ≥99.8% reduction at the reported recall;
recall improvements are W0B's acceptance target, not a baseline claim.

## Run

```bash
python benchmarks/intelligence/run_benchmark.py \
  --repo <checkout-at-pinned-sha> --budget-tokens 2000 \
  --out benchmarks/intelligence/baseline_report_2000t.json
```

Latency is informational only (environment-dependent, not part of any canonical
checksum).

## Tool bake-off policy (native first)

External graph/index tooling is **not installed** by this lane. Candidates are
recorded in `TOOL_CANDIDATE_MATRIX.json` as `NOT_VERIFIED` with the check
that would be required before any isolated install (license path, telemetry,
install side-effects, pinned commit). Zero adoption is a valid outcome per the
contract; the native stdlib-AST + SQLite path is the working baseline until a
same-SHA, same-golden-question bake-off proves a measured gap.
