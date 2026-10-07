# Implementation Roadmap

Codex should implement this as a sequence of reviewable checkpoints even if the user asks it to continue through all of them.

## CTX-01 — Exact repo snapshot

Implement:
- pinned Git HEAD;
- streaming/resumable inventory;
- exact byte/hash proof;
- complete accounting of tracked entries;
- no repository code execution;
- secret-bearing files excluded or metadata-only;
- deterministic manifest;
- resource receipt.

Do not wire Laya.

## CTX-02 — Dependency-aware groups

Implement:
- symbols/imports;
- reverse imports;
- SCC;
- tests/contracts/config relations;
- logical parts;
- unsupported/oversized groups explicit;
- exact source refs.

## CTX-03 — History, coverage, context packs

Implement:
- repo history/delta;
- stale invalidation;
- coverage/gaps;
- WHOLE_REPO / RUNTIME_PATH / TEST_IMPACT / TECH_DEBT / DELTA packs;
- exact retrieval benchmark;
- portable archive/recovery after core tests.

## DATA-RET-01 — Storage observability

Before deleting anything:
- measure actual AGG-02/raw/Parquet/episode bytes;
- storage budget;
- forecast;
- pin references;
- dry-run retention reports.

Acceptance:
zero destructive writes.

## DATA-RET-02 — Rollups + sampling

Add:
- 1m/5m/1h rollups;
- baseline periodic sample;
- significant-delta retention;
- repeated-failure reservoir sample;
- candidate-window pins;
- negative example sampling.

Acceptance:
replay/coverage proof and no candidate evidence loss.

## DATA-RET-03 — Verified compaction

Use existing AnalyticalDatasetPublisher/DatasetReplayReader.

Add:
- partition manifests;
- ZSTD Parquet if supported by chosen writer configuration;
- exact checksum;
- row/availability range verification;
- reference/deletion-impact check;
- retention receipt.

Still default to dry-run for physical pruning.

## RND-01 — Retrospective episodes

Bind:
observation → graph → candidate → stage decisions → simulation → reconciliation → paper outcome.

Preserve rejections and negative examples.

## RND-02 — Performance intelligence

Reuse production_qualification:
- funnel;
- baseline comparison;
- delay stress;
- dashboard.

Add:
- provider utility;
- disk cost;
- data quality;
- episode learning value.

## LAYA-01 — Local triage

Only now:
- compact-state builder;
- typed decisions;
- cache;
- confidence thresholds;
- extension-of-retention only;
- strong-AI review queue.

No direct delete.

## DATA-RET-04 — Conservative pruning

Physical raw deletion may be enabled only after:
- old enough;
- unreferenced;
- compacted;
- replay proof;
- retention receipt;
- not experiment-pinned;
- minimum samples retained.

First release should retain a safety rollback/tombstone manifest.

## Final acceptance

A fresh machine with Python analytics extras can:
1. index repo;
2. run qualification data collection;
3. stay within storage budget;
4. build reports offline;
5. explain every retained/expired class;
6. reconstruct pinned episodes;
7. use Laya optionally;
8. function without ChatGPT Pro.
