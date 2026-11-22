# Correlation completeness contract V1 (OCA-W1)

- **Date:** 2026-11-22 · **Base main:** `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54`
- **Status:** CONTRACT_AND_FIXTURE lane — binding rules for cross-store correlation; no code changes. Design source: PR #666 (head `6214202b`). Inputs: OCA-W0 audit (PR #680), OCA-W0C inventory (PR #682).
- **Non-negotiables:** no duplicate canonical stores; reuse existing identifiers; unknown ≠ zero; replay must be deterministic; LIVE hard-denied.

## 1. Canonical correlation keys (reuse, never reinvent)

| Key | Defined by | Owner | Rules |
|---|---|---|---|
| `event_id` (uuid) | `EventEnvelope` field | `src/observability/events.py` | unique per event; producer sets it, never the store |
| `trace_id` / `logical_opportunity_id` | `EventEnvelope` | same | one logical opportunity = one trace; stages share `trace_id`, advance `stage` |
| `correlation_id` | `EventEnvelope` | same | links provider/venue-scoped sub-events to the opportunity trace |
| `sequence_no` + `attempt_id` + `attempt_generation` | `EventEnvelope` | same | ordering within a trace/attempt; monotonic per (trace_id, attempt_id) |
| `idempotency_key` | `EventEnvelope` | same | dedupe key for at-least-once producers |
| `source_cursor` / watermark | `SourceCursor`, `ObservationWatermark` | `src/market/observations.py` | AGG-02 journal cursor → observation watermark promotion is the only sanctioned raw→normalized join |
| payload `sha256` + dedupe key | `DurableRawJournal` receipts | `src/agg02/storage.py` | raw payload identity; normalization versions ride alongside, never overwrite |
| `strategy_id` (registration-scoped) | `StrategyRegistry` | `src/strategy/registry.py` | strategy identity comes from the registry; W14 adds typed data requirements, not new IDs |
| `provider_id` / `venue_id` | catalog + governance | `src/market/source_catalog.py`, `src/provider_governance/` | catalog row IDs are canonical; adapters reference them |
| stable symbol ID `py::<path>::<qualified>` | W0B schema `studious.repo-graph.v1` | PR #684 | code-side join key; W3 extends to rename-safe callsite IDs |
| slot/checkpoint/block + tx signature + log index | chain identity | per-chain readers | rooted-state facts; finality/reorg corrections append new linked facts, never overwrite (W13/W15) |

## 2. Sanctioned joins (and their current status — evidence in PR #680 §3)

| Join | Keys | Status | Contract rule |
|---|---|---|---|
| AGG-02 → MarketObservation | source_cursor + payload sha256 + normalization version | PARTIAL | cursor promotion must be monotonic; gaps stay `GapRecord`, never interpolated |
| MarketObservation → MarketEpisode | observation ids → episode stage inputs | PRESENT | episodes are point-in-time; as-of rebuild must be deterministic |
| Strategy → provider/data requirement | strategy_id → capability/capacity evidence | PARTIAL | W14 CompatibilityEvaluator output is COMPATIBLE/PARTIAL/INCOMPATIBLE/UNKNOWN with reason codes; UNKNOWN never reaches QUALIFIED |
| Decision → outcome (operation events) | trace_id/correlation_id over EventEnvelope | MISSING | **blocked on producers** (OCA-W10): no `make_event()` production callsite exists on `0a0c8ad9` (PR #680 §4); this contract defines the keys, W10 wires the producers |
| Code symbol → runtime callsite | symbol ID → callsite ID | MISSING | W3 defines rename-safe callsite IDs; ambiguity → NEEDS_REVIEW, never guessed |
| Static edge → runtime-observed edge | provenance classes | ENFORCED | `CALLS_STATIC`/`CALLS_RESOLVED` never upgrade to `RUNTIME_OBSERVED` without proven producer evidence |

## 3. Replay rules

1. Any projection replay must pin repo SHA (for code-side joins), source generation (market side), and schema versions; mixed-generation replays are rejected, not blended.
2. Replay output must be byte-identical for identical inputs and versions (determinism receipts, per W0B pattern).
3. Corrections/reorgs append linked invalidation facts; replay after a correction replays the corrected chain, with the original preserved for as-of queries.
4. Sampling of critical decision/correction/gap/replay/paper-shadow events is prohibited (contract §6 of the LLM-free indexing contract).

## 4. Fixture contract

`correlation_examples.v1.json` provides synthetic, `FIXTURE_ONLY` examples of each sanctioned join — they define expected shapes for tests and are never live evidence. Fixtures must carry `"fixture": true` and a `note` field; absence of those fields in any future fixture is a contract violation.

## 5. Gap closure mapping

- Producer gap → OCA-W10 (wires real producers across test/paper/shadow paths).
- Callsite ID gap → OCA-W3.
- Strategy↔provider machine join → OCA-W14 (schema) over W13 registry.
- Temporal/bitemporal as-of semantics → OCA-W15.
- Cross-store read surface → OCA-W11 facade (PR #686, stacked).
