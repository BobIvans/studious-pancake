"""PR-165 / ROUTE-01: canonical economic route identities."""

from __future__ import annotations
from typing import Iterable
from .core import RouteVariant, canonicalize_routes_core, stable_hash


def canonicalize_route(route: RouteVariant) -> RouteVariant:
    return RouteVariant(
        route_id=stable_hash(
            {"economic": route.economic_identity, "resource": route.resource_identity}
        ),
        legs=tuple(route.legs),
        input_amount=route.input_amount,
        guaranteed_output=route.guaranteed_output,
        state_generation=route.state_generation,
        writable_resources=tuple(sorted(route.writable_resources)),
        financing_resources=tuple(sorted(route.financing_resources)),
    )


def hash_economic_equivalence_class(route: RouteVariant) -> str:
    return route.economic_identity


def deduplicate_route_variants(
    routes: Iterable[RouteVariant],
) -> tuple[RouteVariant, ...]:
    return canonicalize_routes_core(routes)


def preserve_distinct_resource_profiles(
    routes: Iterable[RouteVariant],
) -> dict[str, tuple[str, ...]]:
    groups: dict[str, set[str]] = {}
    for route in routes:
        groups.setdefault(route.economic_identity, set()).add(route.resource_identity)
    return {key: tuple(sorted(value)) for key, value in sorted(groups.items())}
