# Capability gap report (OCA-W0C)

Each gap carries: id, priority, typed blocker class, owning lane, and the evidence basis. Unknowns are preserved, not zeroed.

| ID | P | Gap | Blocker class | Owning lane | Evidence |
|---|---|---|---|---|---|
| GAP-1 | P0 | No runtime observation plane: zero EventEnvelope producers; no observed source modes; no freshness/lag/gap measurement | `BLOCKED_MISSING_PRODUCER` | OCA-W10 (after W1/W3) | PR #680 §4 trace; grep receipts on 0a0c8ad9 |
| GAP-2 | P0 | Effective flash-capital capacity UNKNOWN for all 27 candidates | `BLOCKED_LIVE_EVIDENCE_GATE` | R-02 shared live gate | PROVIDER_CATALOG.json status; TASK_INDEX Track B |
| GAP-3 | P1 | No machine-readable strategy↔provider data-requirement join | `MISSING_SCHEMA` | OCA-W14 | trace matrix lane SX row; no CompatibilityEvaluator in src |
| GAP-4 | P1 | 21/53 market-catalog rows `access-not-verified`; quotas/fees/licenses unpinned | `BLOCKED_MISSING_PIN` | R-07/R-13 + OCA-W13 registry | market_source_catalog.json access counter |
| GAP-5 | P1 | No ProviderCapabilityRegistry / DataContract / source-mode declaration in code | `MISSING_SCHEMA` | OCA-W13 (coordinate with open #672) | grep `provider_contracts` = string keys only (PR #680 §2) |
| GAP-6 | P2 | Chain identity/finality/reorg/correction semantics unrepresented in any store | `MISSING_SCHEMA` | OCA-W13/W15 | no such schema in src (grep) |
| GAP-7 | P2 | Market-source catalog staleness risk (checked 2026-10-06; main audited 2026-11-22) | `STALE_EVIDENCE` | OCA-W13 registry revalidation | catalog checked_at field vs lane date |
| GAP-8 | P2 | ONE_SHOT capture mode misreporting risk | `EVIDENCE_DISCIPLINE` | W10/W11 reporting rules | native_cpmm_capture.py docstring; KB map §10 |

Promotion rule: a gap closes only with evidence at the owning lane's acceptance gate (tests/replay receipts on a pinned SHA), never by documentation alone.
