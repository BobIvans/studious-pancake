# MASTER CONTEXT — Studious Local Intelligence + Retention V2

## Purpose

This R&D turns Studious Pancake into a local research workstation that can:
- snapshot and chunk the whole repository with exact source provenance;
- build bounded context packs for any AI or local model;
- keep enough market history for retrospective strategy analysis;
- control disk growth on a laptop;
- use Laya for fast local relevance/novelty/utility decisions;
- produce MD/TXT/JSON/ZIP evidence bundles;
- continue to work if ChatGPT Pro is unavailable.

## Important new finding

Studious already has more of the correct market-data foundation than the earlier R&D assumed.

Existing owners to reuse:

1. src/agg02/storage.py
   - DurableRawJournal
   - JournalCursor / GapRecord
   - AnalyticalDatasetPublisher
   - DatasetReplayReader

2. src/agg02/contracts.py
   - RawEventEnvelope
   - StateRecord / StateFrame
   - availability-time and cursor lineage

3. src/market/observations.py
   - MarketObservationV2
   - generation identity
   - correction/retraction/completeness
   - watermarks

4. src/market/streams.py
   - durable cursors
   - reconnect epochs
   - gap-aware observation publication

5. src/market_data_evolution/contracts.py
   - RawObservation
   - NormalizedObservation
   - MarketEpisode
   - ReplayManifest
   - QualificationEvidence
   - ModelCandidate
   - RetentionReport / evaluate_retention

6. src/production_qualification.py
   - build_agg04_funnel
   - qualify_agg04_campaign
   - compare_agg04_baselines
   - summarize_agg04_delay_stress
   - build_agg04_dashboard

7. src/runtime_discovery_models.py
   - duplicate snapshots/candidates
   - provider failures
   - detector rejection counts

8. src/strategy/market_graph_ingest.py
   - exact source traces with observation_id, cursor, response hash and request fingerprint.

Therefore: DO NOT create a second raw market database.

The new project should be an additive intelligence + retention plane over these owners.

## Repo intelligence primitives worth adapting from Scaling Chrome Extensions

Core:
- repo_inventory.py
- repo_context.py
- repo_source.py
- repo_groups.py
- repo_manifest.py

Additional useful functions discovered in this pass:
- repo_history.py: complete snapshot history + bounded delta pages
- repo_coverage.py: explicit coverage/gaps views
- source_ledger.py: immutable originals, versions, delta parts
- context_library.py: versioned context items + deletion impact
- context_handoff.py: exact evidence-bound handoff
- context_recovery.py: SQLite backup/restore/sync with integrity proof
- context_benchmark.py: frozen exact-retrieval benchmark
- repo_archive.py: verified portable ZIP64 export with resource budgets

These are much more valuable than copying Chrome UI or browser automation.

## Two independent but linked intelligence planes

### A. Code Intelligence

Git HEAD
→ exact inventory
→ byte ranges
→ AST/symbols/imports
→ dependency graph
→ SCC/logical groups
→ context parts
→ evidence/questions
→ Laya relevance/need scoring
→ bounded context pack

### B. Market Intelligence

AGG-02 raw/cursors/gaps
→ canonical observations
→ graph/candidates
→ simulation/reconciliation/paper outcome
→ MarketEpisode
→ rollups/funnel/provider utility
→ Laya novelty/research-value scoring
→ retrospective report

They share experiment IDs, evidence references and hashes.
They do not share one giant text corpus.

## Laya role

Laya should answer small typed questions over compact state JSON.

Good:
- is this observation novel enough to keep beyond the baseline sample?
- is this candidate episode useful for future research?
- is this failure distinct from already-seen failures?
- which repo group is most relevant to a known blocker?
- does this episode need strong-model review?
- does a result contradict current strategy assumptions?

Bad:
- choose which raw market bytes to permanently delete;
- decide whether trading may go live;
- decide whether evidence is authoritative;
- replace replay/reconciliation;
- scan an unbounded corpus by passing all text to one inference.

Canonical filtering before Laya:
dedupe → schema validation → deterministic delta → rollup → candidate pinning → retrieval.
Laya only sees the remaining compact states.

## Success criterion

After a 24h campaign, one local command must be able to answer:
- how much data was seen vs retained;
- which providers produced useful unique evidence;
- which pairs/routes produced candidates;
- rejection reasons by stage;
- candidate→simulation→reconciliation conversion;
- strategy A vs strategy B;
- which episodes deserve deeper AI analysis;
- exact source/evidence refs for every conclusion;
- disk forecast and what can be safely compacted.
