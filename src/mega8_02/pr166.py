"""PR-166 / GRAPH-04: generation-bound incremental route index."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Sequence
from .core import Mega802Error, require_text, stable_hash


@dataclass(frozen=True, slots=True)
class IncrementalGraphIndex:
    generation: str
    routes_by_resource: Mapping[str, tuple[str, ...]]
    proof_generation: Mapping[str, str]


def update_incremental_graph_index(
    *, generation: str, routes: Mapping[str, Sequence[str]]
) -> IncrementalGraphIndex:
    require_text(generation, "generation")
    by_resource: dict[str, list[str]] = {}
    proofs: dict[str, str] = {}
    for route_id, resources in sorted(routes.items()):
        require_text(route_id, "route_id")
        proofs[route_id] = generation
        for resource in sorted(set(resources)):
            require_text(resource, "resource")
            by_resource.setdefault(resource, []).append(route_id)
    return IncrementalGraphIndex(
        generation=generation,
        routes_by_resource={k: tuple(sorted(v)) for k, v in by_resource.items()},
        proof_generation=proofs,
    )


def maintain_scc_cycle_cache(
    adjacency: Mapping[str, Sequence[str]],
) -> tuple[tuple[str, ...], ...]:
    nodes = sorted(
        set(adjacency) | {n for values in adjacency.values() for n in values}
    )
    reach = {node: set() for node in nodes}
    for node in nodes:
        stack = [node]
        while stack:
            current = stack.pop()
            for nxt in adjacency.get(current, ()):
                if nxt not in reach[node]:
                    reach[node].add(nxt)
                    stack.append(nxt)
    groups: list[tuple[str, ...]] = []
    unseen = set(nodes)
    while unseen:
        node = min(unseen)
        group = tuple(sorted(n for n in unseen if n == node or (
            n in reach[node] and node in reach[n]
        )))
        groups.append(group)
        unseen.difference_update(group)
    return tuple(groups)


def identify_affected_routes(
    index: IncrementalGraphIndex, changed_resources: Sequence[str]
) -> tuple[str, ...]:
    return tuple(sorted({
        route for resource in changed_resources
        for route in index.routes_by_resource.get(resource, ())
    }))


def invalidate_stale_route_proofs(
    index: IncrementalGraphIndex, *, new_generation: str
) -> tuple[str, ...]:
    require_text(new_generation, "new_generation")
    if new_generation == index.generation:
        return ()
    return tuple(sorted(index.proof_generation))
