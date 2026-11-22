"""Task-conditioned personalized PageRank over the typed graph (OCA-W4B).

Pure-Python deterministic power iteration. Personalization comes from the
lexical/exact-match seeds for the current task, so raw call frequency can
never dominate: PageRank contributes only as a bounded multiplier on the
existing retrieval score, and only through task-conditioned seeds.
"""

from __future__ import annotations

from typing import Any

DAMPING = 0.85
MAX_ITERATIONS = 30
TOLERANCE = 1e-8
# PageRank re-ranks task-relevant candidates; it never outranks exact matches.
PAGERANK_WEIGHT_CAP = 0.35


def personalized_pagerank(
    edges: list[tuple[str, str]],
    seeds: dict[str, float],
    *,
    damping: float = DAMPING,
    max_iterations: int = MAX_ITERATIONS,
    tolerance: float = TOLERANCE,
) -> dict[str, float]:
    """Deterministic personalized PageRank.

    ``seeds`` maps node IDs to non-negative personalization weights (need not
    sum to 1; normalized internally). Nodes not in ``edges`` but present in
    ``seeds`` participate as dangling nodes.
    """
    if not seeds:
        return {}
    outgoing: dict[str, list[str]] = {}
    nodes: set[str] = set(seeds)
    for source, target in edges:
        outgoing.setdefault(source, []).append(target)
        nodes.add(source)
        nodes.add(target)
    total_seed = sum(seeds.values())
    if total_seed <= 0:
        return {}
    ranks = {node: 1.0 / len(nodes) for node in nodes}
    for _ in range(max_iterations):
        next_ranks: dict[str, float] = {}
        dangling_mass = sum(ranks[node] for node in nodes if node not in outgoing)
        for node in nodes:
            rank = (1.0 - damping) * (seeds.get(node, 0.0) / total_seed)
            rank += damping * dangling_mass / len(nodes)
            next_ranks[node] = rank
        for source, targets in outgoing.items():
            share = ranks[source] / len(targets)
            for target in targets:
                next_ranks[target] += damping * share
        delta = sum(abs(next_ranks[node] - ranks[node]) for node in nodes)
        ranks = next_ranks
        if delta < tolerance:
            break
    return ranks


def conditioned_boost(
    graph_scores: dict[str, float],
    seed_nodes: dict[str, float],
    edges: list[tuple[str, str]],
) -> dict[str, float]:
    """Bounded per-path boost from task-conditioned PageRank (normalized)."""
    if not seed_nodes:
        return {}
    ranks = personalized_pagerank(edges, seed_nodes)
    if not ranks:
        return {}
    max_rank = max(ranks.values())
    if max_rank <= 0:
        return {}
    # Boost applies to paths that host a high-rank node; scaled to the cap so
    # graph position can reorder relevant candidates but never outrank an
    # exact-ID match (which carries a 1000.0 base score upstream).
    boosts: dict[str, float] = {}
    for path, score_seed in seed_nodes.items():
        rank = ranks.get(path, 0.0)
        boosts[path] = PAGERANK_WEIGHT_CAP * score_seed * (rank / max_rank)
    return boosts
