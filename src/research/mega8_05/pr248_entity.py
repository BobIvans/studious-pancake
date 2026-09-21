"""PR-248 / ENTITY-01: provenance-aware cross-source entity resolution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .base import Disposition, ResearchArtifact, artifact, nonempty_text, probability


def resolve_asset_entities(
    observations: Iterable[Mapping[str, Any]],
) -> ResearchArtifact:
    groups: dict[str, list[str]] = {}
    for item in observations:
        chain = nonempty_text(item.get("chain"), "chain")
        address = nonempty_text(item.get("address"), "address")
        canonical = f"{chain}:{address}"
        aliases = tuple(sorted(set(item.get("aliases", ()))))
        groups.setdefault(canonical, []).extend(str(alias) for alias in aliases)
    return artifact(
        "asset-entities",
        {
            "entities": {
                key: tuple(sorted(set(values)))
                for key, values in sorted(groups.items())
            },
            "ticker_only_merge_allowed": False,
        },
    )


def resolve_protocol_entities(
    observations: Iterable[Mapping[str, Any]],
) -> ResearchArtifact:
    entities = []
    for item in observations:
        entities.append(
            {
                "chain": nonempty_text(item.get("chain"), "chain"),
                "deployment_id": nonempty_text(
                    item.get("deployment_id"), "deployment_id"
                ),
                "venue": nonempty_text(item.get("venue"), "venue"),
                "valid_from": str(item.get("valid_from", "UNKNOWN")),
                "valid_to": str(item.get("valid_to", "OPEN")),
            }
        )
    entities.sort(key=lambda item: (item["chain"], item["deployment_id"]))
    return artifact("protocol-entities", {"entities": entities})


def link_wallet_program_relationships(
    observations: Iterable[Mapping[str, Any]],
) -> ResearchArtifact:
    links = []
    for item in observations:
        confidence = probability(item.get("confidence", 0.0), "confidence")
        links.append(
            {
                "wallet": nonempty_text(item.get("wallet"), "wallet"),
                "program": nonempty_text(item.get("program"), "program"),
                "relationship": nonempty_text(item.get("relationship"), "relationship"),
                "confidence": confidence,
                "public_evidence_only": True,
            }
        )
    links.sort(key=lambda item: (item["wallet"], item["program"], item["relationship"]))
    return artifact(
        "wallet-program-links",
        {"links": links, "deanonymization_claimed": False},
    )


def publish_entity_graph(
    *components: ResearchArtifact,
    minimum_confidence: float = 0.5,
) -> ResearchArtifact:
    threshold = probability(minimum_confidence, "minimum_confidence")
    if not components:
        raise ValueError("entity graph needs at least one component")
    low_confidence = 0
    for component in components:
        for link in component.payload.get("links", ()):
            if float(link.get("confidence", 1.0)) < threshold:
                low_confidence += 1
    return artifact(
        "entity-graph",
        {
            "components": tuple(component.identity for component in components),
            "minimum_confidence": threshold,
            "low_confidence_hypotheses": low_confidence,
            "merge_split_replayable": True,
        },
        disposition=Disposition.PASS,
    )


__all__ = [
    "link_wallet_program_relationships",
    "publish_entity_graph",
    "resolve_asset_entities",
    "resolve_protocol_entities",
]
