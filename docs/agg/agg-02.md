# AGG-02 — market data, shared source budgets and observable capital

Aggregate ID: `AGG-02`  
Branch: `codex/agg-20260920-02`  
Base observed at branch creation: `main@0c4f216a62d62b20f6fb4ec4bbd0548cea58df65`

## Scope implemented in this change

This change adds a sender-free aggregate seam around existing repository authorities.
It does not create a second runtime, source-quota database, financial reservation
authority, signer, sender, or live OMS.

Existing canonical owners reused:

- shared provider quota: `SQLiteQuotaAuthority`;
- public market truth: `MarketObservationV2`, watermarks and durable cursors;
- public RPC/WSS/oracle safety gates under `src.data_plane`;
- durable capital reservations: `DurableCapitalCoordinator`;
- existing provider-governance and external-resource boundaries remain owners of
  account credentials and remote provisioning.

New AGG-02 code supplies:

- causal `RawEventEnvelope` with received/available time, cursor, slot, decoder
  version, uncertainty and explicit gap state;
- point-in-time `StateFrame` materialization that excludes future, quarantined,
  missing and gap-affected dependencies;
- a durable raw-bytes SQLite journal that commits raw event and cursor in one
  transaction and refuses undeclared gaps/cursor rollback;
- explicit gap records and replay identity;
- optional Parquet analytical publication with checksums and atomic publish;
- multi-dimensional source-budget reservation over the existing quota authority;
- bounded retry, entitlement expiry, usage metering and deduplicated subscription
  planning primitives;
- chain/on-chain/token-program asset identity, typed operation graph,
  dependency-to-route invalidation, shared write/economic resource conflicts,
  capacity/fee surfaces and evidence lineage;
- read-only native SOL budget envelope that subtracts active durable reservations
  and never derives SOL from a USD amount;
- program/token admission against pinned program hashes, token-program,
  extension and destination allowlists.

## Important evidence boundary

This PR can prove offline implementation and repository integration. It cannot
manufacture account entitlements, activate trials, submit grant applications,
prove current provider quotas, create remote webhooks, or claim a real collector
fleet run without authorized external account/network evidence.

Accordingly:

- `implementation_status`: may become `MERGED_CODE` after current-head gates;
- `operational_status`: remains `UNQUALIFIED` / `BLOCKED` for external
  observations not actually collected;
- signing, transaction submission and live trading remain outside this package.

## NF disposition

The implementation directly covers the reusable code contracts behind:

- SOURCE-01: NF-031, 037-044 (registry/entitlement semantics, shared budgets,
  metering, bounded retry, subscription planning, failover/SLO data contracts).
  NF-032-035 and remote apply portions of NF-042 require account/network evidence.
- DATA-01: NF-045-054 and NF-061 causal envelope, durable journal, ordering/gap
  representation, StateFrame, as-of view and lineage primitives.
- DATA-02: NF-055-060 analytical projection/manifest/checksum seams. Real backup
  campaigns and scaled backends remain operational evidence.
- DATA-03: existing RPC/WSS/webhook owners are reused for NF-062-066/083. This
  PR does not claim that a real external collector fleet was run.
- DATA-04: existing RPC/oracle/discovery owners plus new graph/surface contracts
  support NF-067/069/071/075/076; real captured market surfaces remain evidence.
- CAPITAL-01: NF-012-015/197 receive read-only exact-lamport and trust/admission
  contracts; no wallet secret or remote effect is introduced.
- MARKET-01: NF-084-089/091-094 receive asset, operation, resource, affected-route,
  capacity/fee and evidence-lineage contracts.

## Required regression behavior

The AGG-02 focused test file verifies:

1. two workers/instances consume one durable provider budget;
2. expired entitlement fails before quota mutation;
3. 403 is not retried and 429 obeys the deadline;
4. shared account subscriptions are deduplicated across consumers;
5. raw bytes and cursor advance atomically and survive restart;
6. tampered payloads and undeclared cursor gaps cannot advance the cursor;
7. point-in-time frames cannot use future or gap-affected state;
8. a shared reserve creates an economic route conflict;
9. unknown fees fail closed;
10. evidence lineage rejects unsupported ancestry;
11. unknown/stale balance cannot become spendable capital;
12. native SOL remains exact integer lamports;
13. unknown token extensions/program drift remain inadmissible.

## Merge and rollback

Merge is permitted only after the exact PR head passes the repository's current
required checks. A green code merge does not activate any external source,
wallet effect, signing, submission or live trading.

Rollback is a normal revert of the aggregate PR. The new raw journal is
analytical/observation state only; existing durable financial lifecycle and
capital stores are not migrated or deleted by this change.

## Post-merge reconciliation

Historical base/dependency notes above describe the state when AGG-02 was
developed. Current merge identity is PR #496 /
`a52bbd11338e3c9092cd871227d2279450b928a3`. AGG-01 is now merged through
PR #501, so AGG-01 is not a current package-dependency blocker.

The code slice is present in main; current aggregate implementation truth is
tracked as `MERGED_CODE` by `config/agg_merge_receipts.json`. External
provider entitlements, collectors and current wallet/reserve observations remain
operational evidence requirements and are not upgraded by this reconciliation.
