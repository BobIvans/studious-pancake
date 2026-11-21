from __future__ import annotations

import json

from src.contracts.registry import get_schema_registry
from src.external_contracts.registry import ExternalContractRegistry
from src.intelligence.data_catalog import (
    DATA_CATALOG_SCHEMA_ID,
    build_data_catalog_snapshot,
    main,
)
from src.market.source_catalog import (
    MarketDataSource,
    MarketSourceCatalog,
    SourceAccess,
    SourceFamily,
    load_market_source_catalog,
)


def _single_source_catalog(source_id: str) -> MarketSourceCatalog:
    return MarketSourceCatalog(
        checked_at="2026-11-21",
        sources=(
            MarketDataSource(
                source_id=source_id,
                label=f"{source_id} source",
                family=SourceFamily.ROUTER,
                domains=("solana",),
                access=SourceAccess.UNVERIFIED,
                evidence_urls=("https://docs.example.org/provider",),
                limitation="Catalog fixture only; no runtime access is granted.",
            ),
        ),
    )


def test_data_catalog_is_a_valid_deterministic_read_only_projection() -> None:
    first = build_data_catalog_snapshot()
    second = build_data_catalog_snapshot()
    payload = first.to_payload()

    assert first.to_json() == second.to_json()
    assert first.snapshot_sha256 == second.snapshot_sha256
    assert payload["snapshot_sha256"] == first.snapshot_sha256
    assert payload["schema_version"] == DATA_CATALOG_SCHEMA_ID
    assert get_schema_registry().validate_payload(DATA_CATALOG_SCHEMA_ID, payload)

    entities = payload["entities"]
    entity_types = {item["entity_type"] for item in entities}
    assert {
        "market-source",
        "provider",
        "external-contract",
        "pinned-artifact",
        "schema",
        "canonical-dataset",
    } <= entity_types

    source_count = len(load_market_source_catalog().sources)
    contract_count = len(ExternalContractRegistry.load_default().contracts)
    schema_count = len(get_schema_registry().records)
    assert (
        sum(item["entity_type"] == "market-source" for item in entities)
        == source_count
    )
    assert (
        sum(item["entity_type"] == "external-contract" for item in entities)
        == contract_count
    )
    assert sum(item["entity_type"] == "schema" for item in entities) == schema_count
    assert sum(item["entity_type"] == "canonical-dataset" for item in entities) == 4


def test_catalog_does_not_export_probe_urls_or_credential_bindings() -> None:
    payload = build_data_catalog_snapshot().to_payload()
    encoded = json.dumps(payload, sort_keys=True)

    assert "conformance_probe" not in encoded
    assert "required_env" not in encoded
    assert "credential_header_env" not in encoded
    assert "JUPITER_API_KEY" not in encoded
    assert "raw_events" not in encoded
    assert "payload_bytes" not in encoded


def test_provider_to_source_link_requires_exact_canonical_id_match() -> None:
    contract_registry = ExternalContractRegistry.load_default()
    source_catalog = _single_source_catalog("jupiter-router-alias")

    snapshot = build_data_catalog_snapshot(
        source_catalog=source_catalog,
        contract_registry=contract_registry,
        schema_registry=get_schema_registry(),
    )

    assert not any(
        relationship.relationship_type == "EXACT_ID_MATCHES_MARKET_SOURCE"
        and relationship.target_urn.endswith("jupiter-router-alias")
        for relationship in snapshot.relationships
    )


def test_provider_to_source_link_is_emitted_for_exact_id_match_only() -> None:
    contract_registry = ExternalContractRegistry.load_default()
    source_catalog = _single_source_catalog("jupiter")

    snapshot = build_data_catalog_snapshot(
        source_catalog=source_catalog,
        contract_registry=contract_registry,
        schema_registry=get_schema_registry(),
    )

    matches = [
        relationship
        for relationship in snapshot.relationships
        if relationship.relationship_type == "EXACT_ID_MATCHES_MARKET_SOURCE"
    ]
    assert len(matches) == 1
    assert matches[0].target_urn.endswith(":jupiter")
    assert matches[0].provenance == "exact-canonical-id-equality"


def test_catalog_cli_summary_is_bounded_and_read_only(capsys) -> None:
    assert main(["--summary"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["read_only"] is True
    assert output["entities"] > 0
    assert output["relationships"] > 0
    assert output["snapshot_sha256"]


def test_catalog_search_and_lineage_are_bounded_and_evidence_linked() -> None:
    snapshot = build_data_catalog_snapshot()
    provider = next(
        entity for entity in snapshot.entities
        if entity.entity_type == "provider" and entity.name == "jupiter"
    )

    results = snapshot.search("jupiter", entity_type="provider", limit=10)
    assert [item.urn for item in results] == [provider.urn]

    lineage = snapshot.trace_relationships(
        provider.urn, direction="outbound", max_hops=2, limit=10
    )
    assert {item.relationship_type for item in lineage} == {
        "HAS_API_CONTRACT",
        "HAS_PINNED_ARTIFACT",
    }
    assert all(item.provenance for item in lineage)
    assert all(item.evidence_refs for item in lineage)


def test_catalog_search_and_lineage_fail_closed_on_invalid_bounds() -> None:
    snapshot = build_data_catalog_snapshot()
    provider = next(
        entity for entity in snapshot.entities
        if entity.entity_type == "provider"
    )

    with pytest.raises(ValueError, match="search limit"):
        snapshot.search("provider", limit=0)
    with pytest.raises(ValueError, match="lineage max_hops"):
        snapshot.trace_relationships(provider.urn, max_hops=9)
    with pytest.raises(ValueError, match="lineage result limit"):
        snapshot.trace_relationships(provider.urn, max_hops=3, limit=1)
