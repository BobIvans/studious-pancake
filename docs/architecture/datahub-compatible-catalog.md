# DataHub-style metadata catalogue projection

## Decision

Studious keeps its canonical data owners. It does not deploy a second metadata database for the initial DataHub workstream.

The first implementation is a deterministic, read-only metadata graph export in src/intelligence/data_catalog.py. It borrows DataHub's entity/relationship and ownership-oriented metadata model, but it is **not** a DataHub server, a DataHub ingestion connector, or a claim of wire-level Metadata Change Proposal compatibility.

DataHub's own metadata model is based on typed entities and aspects, with relationships between entities; its ingestion framework supports pull-based connectors and push-based metadata change proposals. Those are useful reference patterns if a multi-team catalog service becomes necessary:
- https://docs.datahub.com/docs/components
- https://docs.datahub.com/docs/architecture/metadata-ingestion
- https://github.com/datahub-project/datahub/blob/master/docs/modeling/metadata-model.md

## Canonical owners reused

| Catalogue projection | Canonical owner | What is exposed |
|---|---|---|
| Market source | src.market.source_catalog | Source identity, family, domains, access class, evidence URLs, limitations and source-catalog generation |
| Provider identity / API contract | src.external_contracts.registry | Provider IDs, contract status, declared capabilities, official docs, pinned artifact identities, promotion/evidence state |
| Pinned artifact | ExternalContractRegistry artifact pins | Relative path, artifact kind, required flag and SHA-256; artifact contents are not copied |
| Schema | src.contracts.registry + src.resources/schema_registry.json | Schema ID, owner module, boundary class, compatibility policy, status, validation mode and schema-definition hash |
| Canonical dataset owner | Existing AGG-02, MarketObservation, Observability and MarketEpisode modules | Dataset identity, owner module, description and selected non-sensitive semantic attributes; no rows or raw payloads |

The catalogue does not replace the source registry, ExternalContractRegistry, SchemaRegistry, AGG-02 journal, MarketObservation, EventEnvelope or MarketEpisode.

## Export contract

Run:

~~~bash
python -m src.intelligence.data_catalog
python -m src.intelligence.data_catalog --summary
~~~

The JSON export contains:
- source_generations: version/hash of each canonical metadata input;
- entities: stable Studious URNs, entity type, display name, owner module, description and typed metadata properties;
- relationships: directed relation type, endpoints, provenance and evidence references;
- snapshot_sha256: domain-separated digest of the complete deterministic export.

The payload is validated by intelligence.data-catalog-snapshot.v1 in the existing canonical schema registry. Sorting and stable IDs make identical source generations produce byte-identical exports.

## Lineage and uncertainty policy

- provider HAS_API_CONTRACT comes directly from each registered contract.
- external_contract HAS_PINNED_ARTIFACT comes directly from each pinned artifact record and references its SHA-256.
- provider EXACT_ID_MATCHES_MARKET_SOURCE is emitted only when the external contract's provider ID exactly equals the market catalogue's source ID. No display-name, URL-host or fuzzy-name inference is allowed.
- No source-to-observation, observation-to-event, event-to-episode or strategy-to-dataset lineage is invented. Those links require explicit producer/consumer evidence and remain a separate implementation task.
- An entity's metadata listing or contract capability does not authorize network calls or activate a provider. execution_allowed is exposed as a source-owned evidence state only; the catalogue itself cannot grant authority.

## Security boundary

The projection intentionally omits conformance_probe, request URLs with query parameters, credential environment bindings, credential references, secrets, raw market payloads, raw event IDs and observation rows. External contract status and pinned artifact SHA values are sufficient for catalogue discovery; the corresponding owner remains responsible for reading/verifying its own evidence.

The CLI performs no network requests and makes no writes. It is suitable for local export, CI artifact generation and later adapter development.

## What is not included yet

- No DataHub server, Kafka, MySQL, Elasticsearch or metadata-store deployment.
- No direct DataHub MCP server or DataHub REST/MCP emitter.
- No source-specific DEX/RPC ingestion connector is enabled by this projection.
- No continuous freshness or provider-health monitoring is inferred from a catalogue snapshot.
- No canonical operational data is duplicated into a metadata store.

A real DataHub deployment or emitter should be considered only when multi-repository/team search, federated ownership, access policy or external consumers require a service. If so, implement a one-way, versioned exporter from this projection and preserve the existing canonical owners.
