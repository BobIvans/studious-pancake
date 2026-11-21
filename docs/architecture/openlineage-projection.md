# OpenLineage-compatible operation lineage projection

## Decision

Use OpenLineage's RunEvent and Dataset/Job/Run vocabulary as a portable export contract, while keeping Studious Pancake's canonical evidence owners unchanged.

The implementation is a local, read-only RunEvent projection in src/intelligence/openlineage.py. It is not an HTTP emitter, a Marquez deployment, a DataHub deployment, or a replacement for EventEnvelope, AGG-02, MarketObservation or MarketEpisode.

OpenLineage standardizes job/run/dataset lineage and lets producers attach versioned custom facets. The upstream specification and facet guidance are:
- https://openlineage.io/docs/spec/
- https://openlineage.io/docs/spec/facets/
- https://github.com/OpenLineage/OpenLineage/blob/main/spec/OpenLineage.json

The core RunEvent schema is pinned to the 2-0-2 versioned schema URL. Studious custom facet schemas are in src/resources/openlineage_facets.v1.json and their _schemaURL points to an immutable Git commit, not main.

## Canonical owners

| OpenLineage projection | Canonical source | Exported information |
|---|---|---|
| Run | src.observability.events.EventEnvelope | Stable run UUID derived from runtime/aggregate/attempt identity; event ID and payload digest; event type/stage/outcome; test/shadow/paper environment; trace/correlation; provider/venue; reason/config/evidence digest |
| Dataset | Caller-selected dataset identity | Namespace and name; no underlying rows or payload copied |
| Data quality facet | Explicit caller-supplied provider/observation metadata | Source mode, adapter/schema version, cursor/watermark, event/ingest time, freshness/coverage, gaps, correction/retraction type and raw payload reference/hash |
| Blockchain facet | Explicit caller-supplied chain evidence | Chain/network, block number/hash, transaction/log index, contract deployment, canonicality and finality |
| Strategy facet | Explicit strategy identity | Strategy family/id/version; live_authorized is always false |
| Lineage edges | Explicit caller-supplied evidence edges | Source dataset → target dataset, provenance and evidence refs |

EventEnvelope remains the canonical operation-event ledger. AGG-02 remains the raw market/provider payload and cursor owner. MarketObservation remains the normalized market fact owner. MarketEpisode remains the episode/outcome owner. The projection never copies raw rows/payloads into OpenLineage.

## Example

~~~python
from src.intelligence.openlineage import (
    DatasetRef,
    ExplicitLineageEdge,
    OpenLineageEventType,
    project_event,
)

event = project_event(
    envelope,
    event_type=OpenLineageEventType.RUNNING,
    job_namespace="studious://studious-pancake",
    job_name="paper-market-observation",
    repo_sha="<40-character-commit-sha>",
    inputs=(DatasetRef("studious://market", "raw-observations"),),
    outputs=(DatasetRef("studious://market", "normalized-observations"),),
    lineage_edges=(
        ExplicitLineageEdge(
            source=DatasetRef("studious://market", "raw-observations"),
            target=DatasetRef("studious://market", "normalized-observations"),
            provenance="AGG02_NORMALIZATION_RECEIPT",
            evidence_refs=("agg02:event:<event-id>", "normalization:<receipt-id>"),
        ),
    ),
)
~~~

The export is validated against:
- intelligence.openlineage-run-event.v1 in the canonical JSON Schema registry;
- each emitted custom facet definition from openlineage_facets.v1.json;
- exact pinned _schemaURL and producer URI for every Studious facet;
- explicit RFC3339 event/ingest timestamps and valid UUID Run identity.

For deterministic JSON, use Python helper serialize_run_event(...). It returns canonical JSON for a validated event. No network request is made and no source database is mutated.

## Lineage safety

- Inputs and outputs are supplied by the caller; no dataset is inferred from event attribute names.
- Lineage edges are supplied explicitly and must include evidence refs.
- Edges must link a declared input to a declared output. No Cartesian product is generated from all inputs × outputs.
- Run-scoped lineage edges live in run.facets, not job.facets, because they describe this execution and must not be mistaken for invariant metadata about every run of the job.
- A static or metadata-level relationship is not automatically a runtime-observed lineage edge.
- EventEnvelope.attributes is never copied into the export. Only typed, allowlisted context is projected. The event's redacted payload digest is exported instead.
- Raw payload references/hashes are optional explicit facets; raw payload contents, credentials, endpoint query parameters and secrets are never exported.
- Corrections/retractions remain explicit data-quality states; reorg/finality values are supplied from chain-specific evidence and are never inferred from address-only identity.
- live_authorized is hard-coded false; the serializer cannot enable runtime or financial authority.

## Not deployed

- No HTTP emitter or OpenLineage backend/Marquez service.
- No Kafka/NATS transport.
- No DataHub metadata service or second catalogue store.
- No automatic ingestion of every event; callers choose event type, datasets and lineage edges at an evidence-backed boundary.
- No claim that every current production paper/shadow producer is wired. That remains an OCA-W10 instrumentation and coverage task.

A future HTTP emitter can consume the same validated JSON and outbox receipt, but must be a separate delivery adapter with idempotency, durable retries, endpoint policy, auth and delivery/reconciliation evidence.
