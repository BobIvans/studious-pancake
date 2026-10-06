"""Offline inspection of the current GPR research corpus; no campaign/network I/O."""

import argparse
import json
from pathlib import Path

from .graph import ResearchEconomicGraph
from .registry import AssetRegistry, CampaignSeed, DEFAULT_PACK


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    args = parser.parse_args()
    registry = AssetRegistry.load(args.pack / "ASSET_REGISTRY_V2.json")
    seed = CampaignSeed.load(registry, args.pack)
    graph = ResearchEconomicGraph(registry, seed)
    print(
        json.dumps(
            {
                "schema_version": "gpr.seed-inspection.v1",
                "assets": len(registry.assets),
                "first_campaign_families": len(seed.relations),
                "deepbook_pool_identifiers": len(seed.pools),
                "transport_transformations": len(seed.transformations),
                "registry_generation": registry.generation,
                "seed_generation": seed.generation,
                "research_graph_identity": graph.identity,
                "families": [
                    {
                        "relation_id": r.relation_id,
                        "heat": r.heat,
                        "execution_class": r.execution_class,
                        "evidence_state": r.evidence_state,
                    }
                    for r in seed.relations
                ],
                "hard_bound": "BLOCKED_UNTIL_STARTUP_CHAIN_STATE_RECEIPTS",
                "runtime_enabled": False,
                "live_authorization": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
