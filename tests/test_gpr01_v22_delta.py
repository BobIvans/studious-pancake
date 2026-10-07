"""Additive V2.2 identity and non-token transport regressions."""

from dataclasses import replace
import json

import pytest

from src.research_economic_graph import (
    AssetRegistry,
    CampaignSeed,
    ExecutionClass,
    ResearchEconomicGraph,
)
from src.research_economic_graph.registry import DEFAULT_PACK
from src.research_economic_graph.transformations import load_transformations


def test_v22_ssui_identity_and_f12_are_research_only():
    registry = AssetRegistry.load()
    seed = CampaignSeed.load(registry)
    asset = registry.resolve("sui-mainnet:sSUI")
    assert (
        asset.canonical_identifier
        == "0x83556891f4a0f233ce7b05cfe7f957d4020492a34f5405b2cb9377d060bef4bf::spring_sui::SPRING_SUI"
    )
    assert asset.issuer == "SpringSui/Suilend" and asset.representation_kind == "lst"
    assert (
        asset.economic_asset == "SUI"
        and not asset.runtime_enabled
        and not asset.exact_graph_allowed
    )
    assert (
        asset.asset_id
        in next(r for r in seed.relations if r.relation_id == "F12").representations
    )
    assert (
        len(seed.relations) == 14
        and len(seed.pools) == 9
        and len(registry.assets) == 92
    )


def test_v22_transports_do_not_create_mints_or_atomic_edges():
    registry = AssetRegistry.load()
    seed = CampaignSeed.load(registry)
    graph = ResearchEconomicGraph(registry, seed)
    assert len(seed.transformations) == 4
    mesh = next(
        t
        for t in seed.transformations
        if t.transformation_id == "USDT0_LEGACY_MESH_SOLANA"
    )
    assert (
        registry.resolve(mesh.source_representation).canonical_identifier
        == "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
    )
    assert mesh.target_representation is None
    for transform in seed.transformations:
        assert transform.execution_class == ExecutionClass.REBALANCE_ONLY
        assert not transform.atomic_graph_allowed
        relation = transform.relation()
        if relation is not None:
            assert graph.relations[relation.relation_id] == relation
            assert all(ref in registry.assets for ref in relation.representations)
            with pytest.raises(ValueError, match="transport|cross-chain"):
                replace(relation, execution_class=ExecutionClass.LOCAL_ATOMIC)
        with pytest.raises(ValueError, match="non-atomic"):
            replace(transform, execution_class=ExecutionClass.LOCAL_ATOMIC)
    template = next(t for t in seed.transformations if t.kind.endswith("_TEMPLATE"))
    assert template.relation() is None
    assert set(graph.registry.assets) == set(registry.assets)


@pytest.mark.parametrize("label", ["USDT0", "CCTP", "WORMHOLE_ROUTE", "WORMHOLE"])
def test_transport_labels_cannot_be_asset_keys_or_aliases(label):
    raw = json.loads((DEFAULT_PACK / "ASSET_REGISTRY_V2.json").read_text())
    for alias in (False, True):
        mutated = json.loads(json.dumps(raw))
        row = next(
            r
            for r in mutated["assets"]
            if r["chain"] == "solana-mainnet" and r["asset_key"] == "USDT"
        )
        if alias:
            row["legacy_aliases"] = [label]
        else:
            row["asset_key"] = label
        with pytest.raises(ValueError, match="fake asset"):
            AssetRegistry(mutated)


def test_transformation_row_order_is_canonical_and_unsafe_rows_fail(tmp_path):
    registry = AssetRegistry.load()
    path = DEFAULT_PACK / "TRANSFORMATION_REGISTRY_V2_2.json"
    configuration, transforms = load_transformations(registry, path)
    raw = json.loads(path.read_text())
    raw["transformations"].reverse()
    copy_path = tmp_path / path.name
    copy_path.write_text(json.dumps(raw))
    assert load_transformations(registry, copy_path) == (configuration, transforms)
    raw["transformations"][0]["creates_token_identity"] = True
    copy_path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="manufacture"):
        load_transformations(registry, copy_path)
