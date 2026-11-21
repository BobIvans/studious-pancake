# NATS JetStream adoption decision

**Decision:** NOT_REQUIRED_YET  
**Decision date:** 2026-11-21  
**Repository snapshot audited:** main 0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54  
**Workstream order:** D, after Apicurio-style schema compatibility, the DataHub-style catalogue and the Debezium CDC assessment.

## 1. Decision summary

Do not deploy NATS Server or JetStream in the current runtime.

The repository has durable application-level journals, cursors, outboxes, leases/fencing, retry/recovery and local bounded queues. A targeted source/dependency search did not find a NATS client, JetStream stream/consumer configuration, NATS_URL or a production multi-host NATS publisher/consumer pair. The current persistence/lifecycle authority explicitly limits its SQLite topology to single-node.

This does **not** mean that NATS is unsuitable. It means a transport broker is not justified until there is a measured cross-process/cross-host fan-out requirement that the existing canonical outbox relay cannot meet.

## 2. What was checked

The current-main snapshot and targeted search covered:

- dependency manifests: pyproject.toml, requirements.lock and requirements-dev.lock;
- source searches for nats-py, nats.aio, nats.js, JetStream, NATS_URL and nats-server;
- DurableLifecycleStore in src/durability/lifecycle.py;
- PR196RuntimeKernelStore and its continuous supervisor in src/durability/runtime_kernel_pr196.py;
- ObservabilityStore and its outbox in src/observability/store.py;
- AGG-02 raw journal/cursor/gap/replay in src/agg02/storage.py;
- market stream cursor/watermark/reconnect journal in src/market/streams.py;
- persistence-authority policy in src/resources/persistence_authority_mpr_next_12.json;
- legacy in-process queue usage in src/ingest/** and src/config/events.py.

The package manifests do not include a NATS client; targeted code search found no JetStream publisher, stream, durable consumer, NATS connection URI or NATS_URL configuration. Legacy asyncio.Queue usages are process-local. The persistence policy classifies src/ingest/** as quarantined legacy ingest and src/legacy_arb_bot.py as a quarantined legacy monolith; these paths are not an authorization to expose a broker or reactivate legacy runtime.

This is a bounded source/dependency audit, not proof that no external operator process exists. Re-run the inventory against the current pinned main SHA before any future activation.

## 3. Existing delivery owners

| Existing owner | Current behavior | What it already solves |
|---|---|---|
| DurableLifecycleStore | SQLite/WAL state + transaction, durable_outbox, leases, fencing tokens, bounded claim, completion by owner/fence | Multiple local workers can claim an outbox item under a single-node database authority; stale workers cannot complete a newer claim |
| PR196RuntimeKernelStore | Attempt identity, lease/fence, terminal state and outbox; claim, publish marking and recovery scan | Explicit runtime lifecycle event handoff and recovery of pending outbox work |
| ObservabilityStore | EventEnvelope append, integrity chain, transactional export outbox, pending export lookup and completion | Durable operational event capture and controlled downstream export |
| AGG-02 DurableRawJournal | Raw payload + cursor update in one transaction, explicit gap/correction and replay/archive references | Decision-relevant provider payloads and cursor continuity remain canonical |
| Recoverable market stream journal | Source cursor, watermark, reconnect epoch, gap-aware reconstruction | Market feed recovery is owned by the market source boundary, not a general broker |

These owners do not provide a general multi-host message bus. In particular, DurableLifecycleStore explicitly rejects a topology other than single-node because SQLite cannot provide the required multi-host writer fence. That limitation should not be hidden or “fixed” by adding a broker around the same local database.

## 4. What JetStream would add — and what it would not

JetStream provides persistent streams and stateful consumers. Its documented delivery model is at-least-once: consumers acknowledge successfully handled messages, and unacknowledged messages can be redelivered. Separate consumers can track independent positions and replay from the beginning, a sequence or a time. See:

- https://docs.nats.io/concepts/jetstream
- https://docs.nats.io/learn/jetstream/
- https://docs.nats.io/learn/jetstream/pull-consumers

Core NATS without JetStream is at-most-once and does not retain messages for an offline subscriber. JetStream is the durable layer, not simply a faster local queue.

JetStream would add:
- a server/cluster and stream/consumer lifecycle;
- stream storage, retention, replication and discard policies;
- consumer cursor/ack/redelivery semantics;
- authentication, TLS, accounts/subject permissions and server operations;
- message schema/version policy and observability for consumer lag, ack latency and redelivery;
- a durable outbox-to-publisher relay and a durable consumer-to-canonical-store commit/ack protocol.

JetStream would **not**:
- become the canonical owner of raw market payloads, observations, financial decisions or EventEnvelope facts;
- replace AGG-02 cursors, provider adapters, block finality or reorg handling;
- make an application write and a broker publish atomic by itself;
- make consumers exactly-once merely because the broker is persistent;
- authorize a legacy ingest path or increase trading execution authority.

## 5. Why NOT_REQUIRED_YET is the correct current state

The current evidence does not establish:

1. an approved production deployment with multiple independent hosts/processes that must exchange the same durable event stream;
2. more than one independent consumer that needs its own replayable position;
3. a measured outbox queue/lag or delivery availability failure that cannot be solved by the current bounded publisher/lease/retry policy;
4. a named message taxonomy, subject/partitioning scheme, ordering key, payload/reference policy, retention budget or consumer ownership model;
5. a tested idempotency strategy for duplicate publish, ack loss, consumer restart and the crash window between broker publish and marking the local outbox row complete.

Some legacy modules do contain in-process asyncio.Queue instances. The persistence-authority policy explicitly quarantines src/ingest/** and src/legacy_arb_bot.py. Introducing JetStream to make those paths appear distributed would bypass their current quarantine and persistence-owner gates; it is not an acceptable reason to deploy a broker.

## 6. Reconsideration and implementation gate

Reconsider JetStream only when an implementation issue provides evidence for at least one concrete cross-process/cross-host delivery requirement and identifies:

- **Producers:** exact canonical outbox owner and event families to publish.
- **Consumers:** service/process owners, independent replay needs and their durable sink.
- **Topology:** number of hosts/workers, network trust boundary, expected availability and failure domains.
- **Delivery contract:** event ID/idempotency key, per-aggregate ordering, duplicate tolerance, ack policy, max deliveries, dead-letter handling and replay/reconciliation semantics.
- **Retention and resource policy:** stream retention (limits/workqueue/interest), max age/bytes/messages, replicas, storage, backpressure and quota behavior.
- **Schema governance:** schema ID/version, compatibility rules, unknown-field policy and version rollout/rollback.
- **Security:** TLS, credentials, NATS account/subject allowlists, secret rotation, no credentials in payloads/logs and isolated admin plane.
- **Failure evidence:** publisher crash between publish and outbox completion, consumer crash before/after durable sink commit, ack loss, network partition, broker restart/failover, retention pressure and duplicate replay.
- **Performance/economics:** measured event rate, p50/p95/p99 delivery lag, ack latency, consumer backlog, restart recovery and operational cost compared with the current outbox relay.

### Required delivery pattern if adopted later

1. Canonical owner commits the business/event fact and its outbox record in one transaction.
2. A bounded publisher claims the outbox under a lease/fencing token and publishes with the stable event ID.
3. The relay treats publish acknowledgement and local outbox completion as separate steps; a crash between them may republish.
4. Consumers deduplicate by stable event ID and commit to their canonical sink before acknowledging the JetStream message.
5. Reconciliation compares outbox events, stream sequence/consumer state and sink receipts. Missing or duplicate deliveries become explicit evidence, not silent correction.
6. Retention is bounded and configured by event family. High-volume market payloads remain in AGG-02/archive; the stream carries a reference or explicitly approved envelope, not a second unbounded raw market database.

Start with one producer, one stream and one consumer. Add more subjects/consumers only after evidence and tests. Do not move all application queues or every provider onto JetStream.

## 7. Status and safety boundary

- NATS Server/JetStream is **not installed or deployed** by this decision.
- No new message broker, database or canonical event store is introduced.
- Existing local durable outbox, journals, cursor and recovery owners remain authoritative.
- Quarantined legacy ingest remains quarantined; this decision grants no exception.
- No provider activation, signing, submission, borrowing, spending, production mutation or LIVE authority is added.

**Accepted outcome for step D:** \`CONDITIONAL_NOT_REQUIRED\` for the current single-node/local data-plane topology, with explicit criteria for re-entry when a real distributed transport requirement is demonstrated.
