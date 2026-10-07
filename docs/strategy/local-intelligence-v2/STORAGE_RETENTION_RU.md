# Storage + Retention Policy

## Reality: Laya can help filter, but should not delete directly

There are two different reductions.

### 1. Context reduction for AI

This can be aggressive.
Target: strong AI sees roughly 0.1–1% of the original observation stream.

Pipeline:
raw/event stream
→ exact deterministic filters
→ rollups / deltas / episodes
→ retrieval
→ Laya scoring
→ top context only

It is realistic to cut AI context by 99%+ because most repeated polls are not individually useful to reasoning.

### 2. Physical storage reduction

This must be conservative and deterministic.

Laya may assign:
- utility_score
- novelty_score
- anomaly_score
- followup_value
- strong_ai_value

But a row/payload is physically removable only when all deterministic conditions pass:
- it is old enough;
- it is not referenced by a candidate/episode/replay/evidence receipt;
- a normalized or rollup representation exists;
- required provenance/hash/cursor/gap lineage survives;
- no active experiment pins it;
- compaction verification passed;
- policy says the retention class is expirable.

## Why this is necessary

Long-context Laya harnesses are good at locate-and-score workflows, but broad categorical screening over thousands of unrelated passages accumulates false positives/negatives. Therefore Laya is useful for prioritization, not irreversible deletion.

## Data volume example

Planning case:
- 160 pairs
- 4 data sources
- one poll every 5 seconds

Maximum poll observations:
160 × 4 × 17,280 = 11,059,200 observations/day.

If a normalized persisted observation averages about 700 bytes:
~7.7 GB/day before SQLite/WAL/index overhead.

Keeping every response is not appropriate for a laptop qualification system.

## Recommended durable target

Engineering target, not guarantee:
- 50–300 MB/day long-lived market intelligence;
- candidate/research-heavy days may exceed this;
- raw hot buffer is separately bounded.

At 50 MB/day, 20 GB is roughly 400 days.
At 300 MB/day, 20 GB is roughly 66 days.

Actual code must measure bytes/hour rather than trusting this estimate.

## Default laptop storage budget

Recommended initial default:
20 GB total intelligence budget.

Dynamic policy:
1. reserve at least max(30 GB, 25% of total disk) for Windows/system/user;
2. calculate spare = free_space - reserve;
3. intelligence_budget = clamp(8 GB, 30 GB, spare × 0.5);
4. if spare cannot support 8 GB, enter STORAGE_PRESSURE mode and shrink raw retention first.

Suggested tier allocation within a 20 GB budget:

- 2 GB: raw hot/recovery window
- 7 GB: normalized observations / Parquet rolling history
- 5 GB: candidate episodes and pinned evidence
- 2 GB: 1m/5m/1h rollups + provider metrics
- 2 GB: repo snapshots/context indexes
- 1 GB: reports/questions/Laya decisions
- 1 GB: compaction/transaction headroom

If the machine has >150 GB genuinely free after reserve:
allow 30–50 GB only by explicit configuration.

## Time tiers

T0 RAW HOT:
- 2–6 hours
- hard byte cap
- exact provider bytes only when admitted by existing AGG-02 semantics
- candidate windows are pinned and exempt from ordinary expiry

T1 NORMALIZED HIGH RESOLUTION:
- 3–14 days
- deltas, significant changes and bounded periodic samples

T2 EPISODES:
- 90–180 days minimum
- candidate, rejection, simulation, reconciliation, provider disagreement, anomalies
- high-value episodes may be kept permanently

T3 ROLLUPS:
- keep indefinitely while useful
- 1m/5m/1h statistics
- tiny compared with raw streams

T4 REPORT/EVIDENCE:
- keep indefinitely unless manually deleted
- experiment manifests, hashes, findings, decisions and comparison reports

## Deterministic retention classes

PIN_FOREVER:
- terminal paper outcomes;
- promotion/qualification evidence;
- unique anomaly;
- schema drift;
- replay mismatch;
- reconciliation failure;
- first occurrence of a new failure class;
- manually pinned episode.

PIN_EXPERIMENT:
- all evidence referenced by an active experiment.

KEEP_EPISODE:
- candidate window;
- provider disagreement around candidate;
- all stage transitions and rejection reasons.

KEEP_SAMPLE:
- baseline periodic sample to reconstruct quiet periods.

ROLLUP_ONLY:
- ordinary stable polling after its rollup has been verified.

EXPIRE_RAW:
- unreferenced raw payload whose normalized/rollup representation is verified.

## Reduction policy before Laya

The biggest disk savings should come from deterministic rules:

1. exact duplicate response hash:
   keep count + timing + one payload reference.

2. unchanged market state:
   keep periodic sample rather than every poll.

3. repeated identical failure:
   keep first, last, count and a bounded reservoir sample.

4. high-frequency normal observation:
   retain 5-minute baseline sample + rollups.

5. significant delta:
   retain.

6. candidate window:
   retain full relevant observation lineage.

7. correction/retraction/gap/reconnect:
   retain.

8. provider schema/version change:
   retain.

Only after those rules should Laya score remaining borderline items.

## Laya storage triage

Recommended outputs:
- research_value: 0..4
- novelty: 0..4
- anomaly_probability
- duplicate_semantics_probability
- strong_ai_needed_probability

Safe use:
- high score extends retention;
- low score does NOT immediately delete;
- low score allows normal deterministic expiry after minimum age.

## Required storage metrics

Implement:
- raw_events_seen
- raw_bytes_seen
- raw_events_retained
- raw_bytes_retained
- normalized_rows
- parquet_bytes
- episode_count
- pinned_bytes
- rollup_rows
- compression_ratio_ppm
- dedupe_ratio_ppm
- retention_ratio_ppm
- bytes_written_last_hour
- projected_bytes_per_day
- projected_days_until_budget
- free_disk_bytes
- storage_pressure_state

The report must show why bytes are retained.
