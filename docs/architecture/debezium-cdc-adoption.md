# Debezium CDC adoption decision

**Decision:** NOT_REQUIRED_YET  
**Decision date:** 2026-11-21  
**Repository snapshot audited:** main \`0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54\`  
**Workstream order:** C, after Apicurio-style schema compatibility and the DataHub-style read-only catalogue.

## 1. Decision summary

Do not deploy Debezium, Kafka Connect or Debezium Server in the current Studious runtime.

This is a deliberate adoption decision, not a claim that Debezium is unsuitable or that the project has no databases. The current repository uses SQLite/aiosqlite in multiple local owners, but the source/consumer audit did not establish a requirement to replicate committed changes between independently owned database systems. The current problem visible in the repository is persistence-owner consolidation and governed event delivery, not database CDC.

Debezium remains an approved future candidate if a concrete cross-database CDC requirement appears. It must not be used as a replacement for DEX/RPC/provider adapters, MarketObservation, AGG-02, EventEnvelope or the canonical persistence owners.

## 2. What was checked

The current-main spot check and targeted source/dependency search covered:

- \`pyproject.toml\`, \`requirements.lock\` and \`requirements-dev.lock\`;
- \`src/persistence_authority_mpr_next_12.py\` and \`src/resources/persistence_authority_mpr_next_12.json\`;
- AGG-02 raw journal and its cursor/gap/replay code;
- ObservabilityStore, its durable event append/outbox and export/replay paths;
- DurableLifecycleStore, its leases, fencing, outbox, recovery and backup/restore;
- PR196 runtime kernel, its lease/fencing, terminal/outbox, recovery and backup/restore;
- market stream cursor and recoverable stream journal;
- targeted source searches for PostgreSQL, MySQL/MariaDB, MongoDB, Redis, ClickHouse, Kafka Connect and Debezium client/connector usage.

The dependency manifests include SQLite/aiosqlite; the targeted scan found no production PostgreSQL, MySQL, MongoDB, Redis or ClickHouse client, no installed Debezium connector and no Kafka Connect producer/consumer integration. Textual roadmap mentions are not executable clients. This is a bounded source audit, not a guarantee that no dynamic/external process exists; a future W0 inventory should re-run the scan against its exact pinned main SHA.

## 3. Canonical owners already present

| Existing owner | Current role | Why this is not automatically CDC |
|---|---|---|
| \`src/agg02/storage.py::DurableRawJournal\` | Raw provider payload journal; cursor commits with event receipt; gap, retention and replay support | It is already the canonical raw-data owner for this boundary. A second CDC copy would duplicate events and complicate cursor ownership. |
| \`src/observability/store.py::ObservabilityStore\` | EventEnvelope ledger, integrity chain, transactional outbox and export completion | The outbox is already an explicit application-level publication contract; a CDC connector is not required just to export these events. |
| \`src/durability/lifecycle.py::DurableLifecycleStore\` | Atomic lifecycle, reservation, lease/fencing, durable outbox, recovery and backup/restore | Multi-owner persistence cleanup must be solved through the persistence-authority migration, not hidden behind a second stream of table mutations. |
| \`src/durability/runtime_kernel_pr196.py::PR196RuntimeKernelStore\` | Runtime attempt identity, leases/fencing, terminal/outbox atomicity, recovery scan, backup/restore and bounded supervisor | It already defines explicit durable transitions and outbox semantics for the current local/single-node boundary. |
| \`src/market/streams.py\` | Durable source cursors, watermarks, reconnect epochs, recovery journal and reconstruction | These are source-stream semantics for market adapters; database CDC cannot substitute for DEX/RPC source capability or chain finality. |
| \`src/persistence_authority_mpr_next_12.py\` | Static audit and classification of direct SQLite/aiosqlite connections against approved factories | The observed database-owner split is a governance/cutover issue. CDC does not make unapproved direct connections canonical or safe. |

### Important distinction

Multiple SQLite files and direct SQLite connection sites do not, by themselves, establish a need for Debezium. First determine whether each store is an independent source of truth, a projection, a temporary fixture, a quarantined legacy component or an owner scheduled for migration. If two modules need to coordinate, prefer one canonical owner, a documented application event/outbox contract or a controlled migration before considering table-level CDC.

## 4. Debezium capability and integration cost

Debezium is a valid CDC technology. Its connectors capture committed database changes and preserve connector offsets; connector state and, for applicable database engines, internal schema history must survive restart. The common deployment runs Debezium source connectors inside Kafka Connect and publishes change events to Kafka topics. See:

- https://debezium.io/installation/kafka-connect/
- https://debezium.io/documentation/reference/stable/configuration/storage.html
- https://debezium.io/documentation/reference/install-kafka-connect.html

**SQLite nuance:** current Debezium documentation does include a SQLite connector. It installs capture triggers and creates a \`_debezium_cdc_log\` table in the source database. The connector process needs read/write access to the database file and its directory, including SQLite WAL/SHM sidecars; the Kafka Connect worker must run on the same host with access to the local filesystem. A network filesystem or a remote/container-separated database file is not supported by that connector's documented topology. See https://debezium.io/documentation/reference/stable/connectors/sqlite.html.

That is an especially important consideration for Studious: enabling SQLite CDC is not a passive read-only inspection. It adds trigger/table writes to the source database, requires an additional runtime and permissions, and creates a second event-delivery path that must be reconciled with existing event IDs, outboxes, cursors and recovery rules.

Debezium Server can use connectors without a Kafka cluster and supports several sinks, but that does not remove the need to define persistent offsets, schema history, idempotent delivery, replay and ownership. It is not justified simply because the project might add NATS or more agents later.

## 5. Why NOT_REQUIRED_YET is the correct current state

The current evidence does not identify:

1. two independent, active database owners whose committed table mutations must be replicated to another service;
2. a concrete downstream consumer that needs table-level changes rather than an application-level event/outbox contract;
3. a source database engine/version and supported connector whose mutation/permission model has been approved;
4. a table/key/schema mapping, transaction-ordering requirement, tombstone/delete policy, snapshot plan or offset recovery contract;
5. a measured failure of the existing canonical outbox/replay path that CDC would solve.

Deploying Debezium now would add a connector runtime, offset store, schema-history store where applicable, service credentials and permissions, connector health/lag monitoring, duplicate-delivery semantics, snapshot/backfill procedures and a new security surface without a demonstrated owner/consumer gap.

The known direct-SQLite persistence-authority migration remains important, but it is a separate workstream. Do not use Debezium to bypass blocked/unapproved persistence owners or to replicate quarantined legacy databases into an apparently canonical stream.

## 6. Reconsideration gate

Change this decision from NOT_REQUIRED_YET only when an implementation issue names all of the following:

- **Source owner:** exact database product/version, canonical owner, database/table set, primary-key identity and permitted read/write topology.
- **Consumer:** independent service/team and explicit business/operational reason it needs every committed row change.
- **Gap evidence:** why the existing owner API, EventEnvelope, transactional outbox, journal replay or a small purpose-built exporter cannot satisfy it.
- **Connector fit:** official connector support for the exact source/version and the proposed deployment topology.
- **Mutation approval:** explicit owner approval for connector-installed triggers/tables and any source-database writes (mandatory review for the Debezium SQLite connector).
- **Delivery semantics:** at-least-once duplicate handling, idempotency keys, ordering/transaction boundaries, tombstones/deletes, snapshot/bootstrap, backfill, restart offsets and schema history.
- **Data governance:** schema compatibility, PII/secret redaction, retention, access control, lineage/provenance and evidence export.
- **Operations:** measured throughput, lag, restart/rebalance recovery, queue/backpressure, failure injection, backup/restore and rollback.
- **Economics:** operational/service cost compared with the existing outbox and a bounded application-level relay.

If these conditions are met, open a separate implementation PR for one database owner and one consumer first. Do not connect all SQLite files or all providers in one step.

## 7. Status and safety boundary

- Debezium/Kafka Connect is **not installed or deployed** by this decision.
- No production database is mutated and no credentials are added.
- No market/RPC provider is enabled.
- Existing canonical owners remain authoritative; no duplicate raw market or EventEnvelope store is created.
- The decision must be re-evaluated when the repository introduces a genuinely independent database consumer or a measured CDC requirement.

**Accepted outcome for step C:** \`CONDITIONAL_NOT_REQUIRED\` with evidence and explicit re-entry criteria. This counts as the completed adoption assessment for the current architecture; it does not claim that a Debezium connector was implemented.
