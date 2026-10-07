# Codex — Studious Local Intelligence + Retention V2

Canonical R&D folder:
docs/strategy/local-intelligence-v2/

Audited base:
- Studious main: ac6297e3f174d073c524099f599490edfe30f7b1
- Scaling Chrome Extensions reference main: 2bda32d0b3b51ceb98db09fb1591100a843fabff

Read in order:
1. docs/strategy/local-intelligence-v2/MASTER_CONTEXT_RU.md
2. docs/strategy/local-intelligence-v2/STORAGE_RETENTION_RU.md
3. docs/strategy/local-intelligence-v2/RETROSPECTIVE_DATA_CONTRACT_RU.md
4. docs/strategy/local-intelligence-v2/FUNCTION_BACKLOG.json
5. docs/strategy/local-intelligence-v2/LAYA_RETENTION_QUESTIONS.json
6. docs/strategy/local-intelligence-v2/CLI_AND_REPORTS_RU.md
7. docs/strategy/local-intelligence-v2/PR_ROADMAP_RU.md

Goal:
build a local-first repository intelligence + market retrospective intelligence layer that remains useful without ChatGPT Pro.

Critical architecture rules:
- reuse Studious market/evidence owners instead of creating a second trading store;
- reuse AGG-02 DurableRawJournal / AnalyticalDatasetPublisher;
- reuse market_data_evolution contracts and production_qualification analytics;
- port only domain-neutral repo intelligence primitives from Scaling Chrome Extensions;
- Laya is advisory scoring/triage, never deletion or trading authority;
- deletion requires deterministic retention policy + provenance + replay/rollup proof;
- no live signing/submission authority is added.

First implementation milestone:
CTX-01 exact pinned repo snapshot and deterministic manifest.
Then CTX-02 dependency-aware symbol/import/SCC logical groups.
Then DATA-RET-01 measured retention/compaction over existing market data owners.

Do not start by wiring Laya into every event. First make the data lineage and deterministic retention correct.
