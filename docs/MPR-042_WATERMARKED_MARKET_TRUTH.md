# MPR-042 — Watermarked Market Truth

This pull request is the installed-runtime cutover for the compressed former
PR-042, PR-050 and PR-046 scopes. It preserves the residual traceability
namespaces `R042-*`, `R050-*` and `R046-*`.

## Authority

- `MarketObservationV2` separates expected and guaranteed output and binds every
  observation to source, cursor, commitment, correction and generation identity.
- `ObservationBatch` is immutable and carries a source watermark, completeness
  policy and explicit `complete`, `degraded` or `blocked` verdict.
- `WatermarkedObservationBuffer` rejects duplicate/reordered events and blocks a
  reconnect epoch until every required source finishes durable backfill.
- `GenerationBoundCache` stores immutable hashed JSON values with entry, byte and
  per-provider bounds, provenance/generation validation, negative caching and
  cancellation-safe single-flight.
- Active discovery and detectors consume the guaranteed amount and refuse a
  batch that is not complete.

## Retirement

`src.market.snapshots` remains only as an import-compatible façade. The exported
`MarketQuoteSnapshot` and `SnapshotSet` names instantiate the V2 observation and
batch authority; no separate V1 data model remains.
