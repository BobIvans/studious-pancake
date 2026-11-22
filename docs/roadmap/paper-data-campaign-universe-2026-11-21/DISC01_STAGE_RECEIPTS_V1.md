# DISC-01 Stage Receipts V1 (per-source intake denominators)

Task: `DISC-01` in `docs/roadmap/data-to-paper-readiness-2026-11-22/TASK_BACKLOG_V1.json`
(master DAG #683). Owner: `PublicMarketDiscovery` + `MarketSourceCatalog` +
`SourceIntakePlane` (no duplicate catalog or discovery adapter introduced).

## Contract

`SourceIntakePlane.stage_receipts()` returns one `SourceStageReceipt` per
source with observations in the durable evidence journal:

| Field | Meaning |
|---|---|
| `stage_denominators.requests` | source observations retained for the source |
| `stage_denominators.attempts` | physical attempts claimed for the provider profile |
| `stage_denominators.responded` | observations with HTTP 200 |
| `stage_denominators.normalized` | responded observations that reached normalization |
| `stage_denominators.candidates` | durable `discovery_candidate` records with provenance |
| `stage_denominators.rejected` | per-observation reject counts summed |
| `schema_drift` | any observation reached `schema-drift` quality state |
| `quota_status` | `UNKNOWN` unless the dossier declares a positive quota (`CAPPED`) |
| `response_bytes_total` / `latency_ns_total` | per-observation metrics summed |
| `terminal_results` | typed terminal-result histogram (DATA-01 vocabulary) |

Determinism: receipts are recomputed **from the evidence journal only** (no
in-memory counters); `stage_receipts_digest()` is byte-identical across
processes and restarts for the same store — proven by test.

## Guardrails

- **No unsupported streaming claim** — `require_supported_capabilities()`
  fails closed (`UNSUPPORTED_SOURCE_CAPABILITY:...`) for any capability
  outside the implemented set; `SourceDossier` validation additionally
  refuses capability upgrades at construction.
- **No aggregator route counted as independent liquidity** —
  `independent_correlation_groups()` denominates independence by correlation
  group and excludes aggregator-classified sources from the independent
  count.
- **No paid provider activation / credential probing** — receipts observe
  only; admission still fails closed on missing credential bindings and
  spend stays hard-zero.
- **No duplicate catalog or adapter** — the catalog `.with_intake()` owner
  rejects duplicate source ids (regression test included).

## Evidence state

DISC-01 closes as `PASS_OFFLINE` (deterministic replay, typed receipts,
zero network beyond the offline-suite boundary). Actual capture remains
`CS06_PENDING_CAPTURE` and requires the operator authorization gates.
