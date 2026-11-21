"""Read-only metadata graph projection over canonical Studious data owners.

This is a DataHub-inspired catalogue export, not a second database or an
embedded DataHub deployment. Canonical source, contract, schema and runtime
facts remain owned by their existing modules.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Mapping, Sequence
from urllib.parse import quote

from src.contracts.registry import SchemaRegistry, get_schema_registry
from src.external_contracts.registry import ExternalContractRegistry
from src.kernel import canonical_json_bytes, domain_sha256
from src.market.source_catalog import (
    MarketDataSource,
    MarketSourceCatalog,
    load_market_source_catalog,
)

DATA_CATALOG_SCHEMA_ID = "intelligence.data-catalog-snapshot.v1"
DATA_CATALOG_SCHEMA_VERSION = DATA_CATALOG_SCHEMA_ID

_CANONICAL_DATASETS = (
    {
        "dataset_id": "agg02.raw-provider-events",
        "name": "AGG-02 raw provider event journal",
        "owner_module": "src.agg02.storage.DurableRawJournal",
        "description": (
            "Canonical raw provider payload journal with cursor, receipt, "
            "gap, retention pin and replay ownership."
        ),
        "properties": {
            "record_type": "RawEventEnvelope",
            "payload_authority": "raw-bytes-journal",
            "cursor_and_payload_commit": "same-transaction",
        },
    },
    {
        "dataset_id": "market.normalized-observations",
        "name": "MarketObservation",
        "owner_module": "src.market.observations.MarketObservationV2",
        "description": (
            "Canonical normalized market observations with generation, "
            "cursor, watermark, completeness and correction semantics."
        ),
        "properties": {
            "record_type": "MarketObservationV2",
            "correction_kinds": ("original", "correction", "retraction"),
            "completeness_states": ("complete", "degraded", "blocked"),
        },
    },
    {
        "dataset_id": "observability.operation-events",
        "name": "EventEnvelope operation evidence",
        "owner_module": "src.observability.events.EventEnvelope",
        "description": (
            "Canonical operation event envelope with redaction, reason codes, "
            "event identities and export/replay owners."
        ),
        "properties": {
            "record_type": "EventEnvelope",
            "store_owner": "src.observability.store",
            "replay_owner": "src.observability.replay",
        },
    },
    {
        "dataset_id": "intelligence.market-episodes",
        "name": "MarketEpisode projections",
        "owner_module": "src.market_data_evolution.contracts.MarketEpisode",
        "description": (
            "Evidence-bound operation and market episode projection. "
            "The catalogue records the owner, not individual episode payloads."
        ),
        "properties": {
            "record_type": "MarketEpisode",
            "builder_owner": "src.intelligence.episode_builder",
            "payloads_included": False,
        },
    },
)


def _urn(entity_type: str, key: str) -> str:
    if not entity_type or not key:
        raise ValueError("catalogue URN requires an entity type and key")
    return f"urn:studious-pancake:{entity_type}:{quote(key, safe='-._~')}"


def _market_source_catalog_digest(catalog: MarketSourceCatalog) -> str:
    payload = {
        "checked_at": catalog.checked_at,
        "sources": [
            {
                "source_id": source.source_id,
                "label": source.label,
                "family": source.family.value,
                "domains": source.domains,
                "access": source.access.value,
                "evidence_urls": source.evidence_urls,
                "limitation": source.limitation,
            }
            for source in catalog.sources
        ],
    }
    return domain_sha256(
        domain="market-source-catalog-projection",
        schema_id="shadow.market-source-catalog.v1",
        payload=canonical_json_bytes(payload),
    )


def _external_contract_catalog_digest(
    entities: Sequence[CatalogEntity],
    relationships: Sequence[CatalogRelationship],
    *,
    schema_version: str,
) -> str:
    payload = {
        "entities": [
            item.to_payload()
            for item in entities
            if item.entity_type in {"provider", "external-contract", "pinned-artifact"}
        ],
        "relationships": [
            item.to_payload()
            for item in relationships
            if item.relationship_type
            in {"HAS_API_CONTRACT", "HAS_PINNED_ARTIFACT"}
        ],
    }
    return domain_sha256(
        domain="external-contract-catalog-projection",
        schema_id=schema_version,
        payload=canonical_json_bytes(payload),
    )


def _json_value(value: object) -> object:
    """Normalize approved metadata values without accepting arbitrary objects."""
    if value is None or type(value) in {str, int, bool}:
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    raise TypeError(f"unsupported catalogue metadata value: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class CatalogEntity:
    urn: str
    entity_type: str
    name: str
    owner_module: str
    description: str
    properties: Mapping[str, object]

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (
                self.urn,
                self.entity_type,
                self.name,
                self.owner_module,
                self.description,
            )
        ):
            raise ValueError("catalogue entity identity and owner are required")
        normalized = _json_value(self.properties)
        if not isinstance(normalized, dict):
            raise ValueError("catalogue entity properties must be an object")
        canonical_json_bytes(normalized)
        object.__setattr__(self, "properties", MappingProxyType(normalized))

    def to_payload(self) -> dict[str, object]:
        return {
            "urn": self.urn,
            "entity_type": self.entity_type,
            "name": self.name,
            "owner_module": self.owner_module,
            "description": self.description,
            "properties": dict(self.properties),
        }


@dataclass(frozen=True, slots=True)
class CatalogRelationship:
    source_urn: str
    relationship_type: str
    target_urn: str
    provenance: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (
                self.source_urn,
                self.relationship_type,
                self.target_urn,
                self.provenance,
            )
        ):
            raise ValueError("catalogue relationship identity is required")
        if not self.evidence_refs or any(not item for item in self.evidence_refs):
            raise ValueError("catalogue relationships require evidence references")
        object.__setattr__(
            self, "evidence_refs", tuple(sorted(set(self.evidence_refs)))
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "source_urn": self.source_urn,
            "relationship_type": self.relationship_type,
            "target_urn": self.target_urn,
            "provenance": self.provenance,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class CatalogSourceGeneration:
    owner: str
    resource_version: str
    sha256: str

    def to_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "resource_version": self.resource_version,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class DataCatalogSnapshot:
    """Immutable, deterministic metadata projection; never stores market facts."""

    source_generations: tuple[CatalogSourceGeneration, ...]
    entities: tuple[CatalogEntity, ...]
    relationships: tuple[CatalogRelationship, ...]
    schema_version: str = DATA_CATALOG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        entity_urns = tuple(item.urn for item in self.entities)
        if len(entity_urns) != len(set(entity_urns)):
            raise ValueError("duplicate catalogue entity URN")
        if self.entities != tuple(sorted(self.entities, key=lambda item: item.urn)):
            raise ValueError("catalogue entities must be sorted by URN")
        relationship_keys = tuple(
            (
                item.source_urn,
                item.relationship_type,
                item.target_urn,
                item.provenance,
            )
            for item in self.relationships
        )
        if len(relationship_keys) != len(set(relationship_keys)):
            raise ValueError("duplicate catalogue relationship")
        if self.relationships != tuple(
            sorted(
                self.relationships,
                key=lambda item: (
                    item.source_urn,
                    item.relationship_type,
                    item.target_urn,
                    item.provenance,
                ),
            )
        ):
            raise ValueError("catalogue relationships must be deterministically sorted")
        if any(
            item.source_urn not in set(entity_urns)
            or item.target_urn not in set(entity_urns)
            for item in self.relationships
        ):
            raise ValueError("catalogue relationship references an unknown entity")

    def _payload_without_digest(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_generations": [
                item.to_payload() for item in self.source_generations
            ],
            "entities": [item.to_payload() for item in self.entities],
            "relationships": [item.to_payload() for item in self.relationships],
        }

    @property
    def snapshot_sha256(self) -> str:
        return domain_sha256(
            domain="studious-data-catalog-snapshot",
            schema_id=self.schema_version,
            payload=canonical_json_bytes(self._payload_without_digest()),
        )

    def to_payload(self) -> dict[str, object]:
        payload = self._payload_without_digest()
        payload["snapshot_sha256"] = self.snapshot_sha256
        return payload

    def to_json(self, *, pretty: bool = False) -> str:
        payload = self.to_payload()
        if pretty:
            return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
        return canonical_json_bytes(payload).decode("utf-8")

    def require_entity(self, urn: str) -> CatalogEntity:
        for entity in self.entities:
            if entity.urn == urn:
                return entity
        raise KeyError(f"unknown catalogue entity: {urn}")

    def search(
        self,
        query: str,
        *,
        entity_type: str | None = None,
        limit: int = 50,
    ) -> tuple[CatalogEntity, ...]:
        """Bounded lexical search over metadata only; never searches raw payloads."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("catalogue search query is required")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("catalogue search limit must be between 1 and 500")
        needle = query.casefold().strip()
        matches = []
        for entity in self.entities:
            if entity_type is not None and entity.entity_type != entity_type:
                continue
            haystack = canonical_json_bytes(entity.to_payload()).decode("utf-8").casefold()
            if needle in haystack:
                matches.append(entity)
                if len(matches) > limit:
                    raise ValueError("catalogue search result limit exceeded")
        return tuple(matches)

    def trace_relationships(
        self,
        start_urn: str,
        *,
        direction: str = "both",
        max_hops: int = 3,
        limit: int = 256,
    ) -> tuple[CatalogRelationship, ...]:
        """Bounded breadth-first lineage traversal over evidenced relationships."""
        self.require_entity(start_urn)
        if direction not in {"outbound", "inbound", "both"}:
            raise ValueError("lineage direction must be outbound, inbound or both")
        if type(max_hops) is not int or not 0 <= max_hops <= 8:
            raise ValueError("lineage max_hops must be between 0 and 8")
        if type(limit) is not int or not 1 <= limit <= 2048:
            raise ValueError("lineage limit must be between 1 and 2048")

        frontier = {start_urn}
        visited_nodes = {start_urn}
        visited_edges: set[tuple[str, str, str, str]] = set()
        selected: list[CatalogRelationship] = []
        for _ in range(max_hops):
            next_frontier: set[str] = set()
            for relationship in self.relationships:
                edge_key = (
                    relationship.source_urn,
                    relationship.relationship_type,
                    relationship.target_urn,
                    relationship.provenance,
                )
                if edge_key in visited_edges:
                    continue
                neighbor: str | None = None
                if direction in {"outbound", "both"} and (
                    relationship.source_urn in frontier
                ):
                    neighbor = relationship.target_urn
                elif direction in {"inbound", "both"} and (
                    relationship.target_urn in frontier
                ):
                    neighbor = relationship.source_urn
                if neighbor is None:
                    continue
                visited_edges.add(edge_key)
                selected.append(relationship)
                if len(selected) > limit:
                    raise ValueError("catalogue lineage result limit exceeded")
                if neighbor not in visited_nodes:
                    visited_nodes.add(neighbor)
                    next_frontier.add(neighbor)
            if not next_frontier:
                break
            frontier = next_frontier
        return tuple(selected)


def _entity(
    entity_type: str,
    key: str,
    name: str,
    owner_module: str,
    description: str,
    properties: Mapping[str, object],
) -> CatalogEntity:
    return CatalogEntity(
        urn=_urn(entity_type, key),
        entity_type=entity_type,
        name=name,
        owner_module=owner_module,
        description=description,
        properties=properties,
    )


def _market_source_entity(
    source: MarketDataSource, *, checked_at: str
) -> CatalogEntity:
    return _entity(
        "market-source",
        source.source_id,
        source.label,
        "src.market.source_catalog.MarketSourceCatalog",
        source.limitation,
        {
            "source_id": source.source_id,
            "family": source.family.value,
            "domains": source.domains,
            "access": source.access.value,
            "evidence_urls": source.evidence_urls,
            "catalog_checked_at": checked_at,
            "activation_authorized": False,
        },
    )


def _contract_entities(
    registry: ExternalContractRegistry,
) -> tuple[list[CatalogEntity], list[CatalogRelationship]]:
    contracts = registry.contracts
    providers = sorted({item.provider for item in contracts})
    entities: list[CatalogEntity] = []
    relationships: list[CatalogRelationship] = []

    for provider in providers:
        provider_contracts = sorted(
            (item for item in contracts if item.provider == provider),
            key=lambda item: item.id,
        )
        provider_urn = _urn("provider", provider)
        entities.append(
            _entity(
                "provider",
                provider,
                provider,
                "src.external_contracts.registry.ExternalContractRegistry",
                "Provider identity referenced by one or more pinned API contracts.",
                {
                    "provider_id": provider,
                    "contract_ids": tuple(item.id for item in provider_contracts),
                    "contract_count": len(provider_contracts),
                    "contract_statuses": tuple(
                        sorted({item.status.value for item in provider_contracts})
                    ),
                    "execution_allowed": any(
                        item.execution_allowed for item in provider_contracts
                    ),
                },
            )
        )
        for contract in provider_contracts:
            contract_urn = _urn("external-contract", contract.id)
            entities.append(
                _entity(
                    "external-contract",
                    contract.id,
                    contract.id,
                    "src.external_contracts.registry.ExternalContractRegistry",
                    contract.notes or f"Pinned external API contract for {provider}.",
                    {
                        "contract_id": contract.id,
                        "provider_id": contract.provider,
                        "status": contract.status.value,
                        "capabilities": tuple(
                            sorted(item.value for item in contract.capabilities)
                        ),
                        "official_source_url": contract.official_source_url,
                        "source_ref": contract.source_ref,
                        "artifact_count": len(contract.artifacts),
                        "artifact_pins": tuple(
                            {
                                "path": pin.path,
                                "sha256": pin.sha256,
                                "kind": pin.kind.value,
                                "required": pin.required,
                            }
                            for pin in sorted(
                                contract.artifacts, key=lambda item: item.path
                            )
                        ),
                        "promotion_state": contract.promotion_state.value,
                        "execution_allowed": contract.execution_allowed,
                        "evidence": contract.evidence.model_dump(mode="json"),
                        # Deliberately omit conformance_probe: it may contain
                        # query parameters, credential environment bindings
                        # and request examples that do not belong in a catalogue.
                    },
                )
            )
            relationships.append(
                CatalogRelationship(
                    source_urn=provider_urn,
                    relationship_type="HAS_API_CONTRACT",
                    target_urn=contract_urn,
                    provenance="canonical-external-contract-registry",
                    evidence_refs=(
                        "src/resources/external_contracts.json",
                        f"external-contract:{contract.id}",
                    ),
                )
            )
            for pin in contract.artifacts:
                artifact_key = f"{contract.id}/{pin.path}"
                artifact_urn = _urn("pinned-artifact", artifact_key)
                entities.append(
                    _entity(
                        "pinned-artifact",
                        artifact_key,
                        pin.path,
                        "src.external_contracts.registry.ExternalContractRegistry",
                        "Pinned contract evidence artifact; content is not copied.",
                        {
                            "relative_path": pin.path,
                            "sha256": pin.sha256,
                            "kind": pin.kind.value,
                            "required": pin.required,
                        },
                    )
                )
                relationships.append(
                    CatalogRelationship(
                        source_urn=contract_urn,
                        relationship_type="HAS_PINNED_ARTIFACT",
                        target_urn=artifact_urn,
                        provenance="canonical-external-contract-registry",
                        evidence_refs=(
                            "src/resources/external_contracts.json",
                            f"artifact-sha256:{pin.sha256}",
                        ),
                    )
                )
    return entities, relationships


def build_data_catalog_snapshot(
    *,
    source_catalog: MarketSourceCatalog | None = None,
    contract_registry: ExternalContractRegistry | None = None,
    schema_registry: SchemaRegistry | None = None,
) -> DataCatalogSnapshot:
    """Build the read-only catalogue from canonical registries and data owners.

    No network calls are performed. External contract artifact pins are verified
    by ExternalContractRegistry.load_default() before they enter the projection.
    """
    source_catalog = source_catalog or load_market_source_catalog()
    contract_registry = contract_registry or ExternalContractRegistry.load_default()
    schema_registry = schema_registry or get_schema_registry()

    entities: list[CatalogEntity] = []
    relationships: list[CatalogRelationship] = []

    for source in source_catalog.sources:
        entities.append(
            _market_source_entity(source, checked_at=source_catalog.checked_at)
        )

    contract_entities, contract_relationships = _contract_entities(contract_registry)
    entities.extend(contract_entities)
    relationships.extend(contract_relationships)

    # Link two registries only when the canonical IDs are exactly equal. Do not
    # infer a provider/source join from display names, URL hosts or fuzzy matches.
    market_sources_by_id = {item.source_id: item for item in source_catalog.sources}
    contract_providers = sorted({item.provider for item in contract_registry.contracts})
    for provider in contract_providers:
        source = market_sources_by_id.get(provider)
        if source is None:
            continue
        relationships.append(
            CatalogRelationship(
                source_urn=_urn("provider", provider),
                relationship_type="EXACT_ID_MATCHES_MARKET_SOURCE",
                target_urn=_urn("market-source", source.source_id),
                provenance="exact-canonical-id-equality",
                evidence_refs=(
                    "src/resources/external_contracts.json:provider",
                    "src/resources/market_source_catalog.json:source_id",
                ),
            )
        )

    for record in schema_registry.records:
        schema_hash = (
            hashlib.sha256(canonical_json_bytes(record.schema)).hexdigest()
            if record.schema is not None
            else None
        )
        entities.append(
            _entity(
                "schema",
                record.schema_id,
                record.schema_id,
                record.owner_module,
                f"Registered schema owned by {record.owner_module}.",
                {
                    "schema_id": record.schema_id,
                    "owner_module": record.owner_module,
                    "boundary_class": record.boundary_class,
                    "compatibility": record.compatibility,
                    "unknown_fields": record.unknown_fields,
                    "status": record.status,
                    "validation_mode": record.validation_mode,
                    "has_inline_schema": record.schema is not None,
                    "schema_definition_sha256": schema_hash,
                    "limits": {
                        "max_bytes": record.max_bytes,
                        "max_depth": record.max_depth,
                        "max_nodes": record.max_nodes,
                        "max_list_items": record.max_list_items,
                        "max_string_length": record.max_string_length,
                    },
                },
            )
        )

    for dataset in _CANONICAL_DATASETS:
        entities.append(
            _entity(
                "canonical-dataset",
                str(dataset["dataset_id"]),
                str(dataset["name"]),
                str(dataset["owner_module"]),
                str(dataset["description"]),
                dict(dataset["properties"]),  # type: ignore[arg-type]
            )
        )

    snapshot = DataCatalogSnapshot(
        source_generations=(
            CatalogSourceGeneration(
                owner="src.market.source_catalog",
                resource_version=source_catalog.checked_at,
                sha256=_market_source_catalog_digest(source_catalog),
            ),
            CatalogSourceGeneration(
                owner="src.external_contracts.registry",
                resource_version=contract_registry.model.schema_version,
                sha256=_external_contract_catalog_digest(
                    contract_entities,
                    contract_relationships,
                    schema_version=contract_registry.model.schema_version,
                ),
            ),
            CatalogSourceGeneration(
                owner="src.contracts.registry",
                resource_version="canonical.schema-registry.v1",
                sha256=schema_registry.registry_digest,
            ),
        ),
        entities=tuple(sorted(entities, key=lambda item: item.urn)),
        relationships=tuple(
            sorted(
                relationships,
                key=lambda item: (
                    item.source_urn,
                    item.relationship_type,
                    item.target_urn,
                    item.provenance,
                ),
            )
        ),
    )
    schema_registry.validate_payload(DATA_CATALOG_SCHEMA_ID, snapshot.to_payload())
    return snapshot


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export the read-only Studious data catalogue"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="print counts and snapshot digest instead of the JSON catalogue",
    )
    args = parser.parse_args(argv)
    snapshot = build_data_catalog_snapshot()
    if args.summary:
        payload = {
            "schema_version": snapshot.schema_version,
            "entities": len(snapshot.entities),
            "relationships": len(snapshot.relationships),
            "snapshot_sha256": snapshot.snapshot_sha256,
            "read_only": True,
        }
        print(json.dumps(payload, sort_keys=True))
    else:
        print(snapshot.to_json(pretty=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
