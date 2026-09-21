"""PR-243 / SEMANTICS-01: offline protocol-semantics hypothesis inference."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from .base import Disposition, ResearchArtifact, artifact, nonempty_text


def reconstruct_cpi_call_graph(
    invocations: Iterable[Mapping[str, Any]],
) -> ResearchArtifact:
    edges = set()
    for invocation in invocations:
        parent = nonempty_text(invocation.get("parent"), "parent")
        child = nonempty_text(invocation.get("child"), "child")
        depth = int(invocation.get("depth", 0))
        if depth < 0:
            raise ValueError("depth cannot be negative")
        edges.add((parent, child, depth))
    return artifact("cpi-call-graph", {"edges": tuple(sorted(edges))})


def infer_account_relationships(
    observations: Iterable[Mapping[str, Any]],
) -> ResearchArtifact:
    roles: dict[str, set[str]] = defaultdict(set)
    for item in observations:
        account = nonempty_text(item.get("account"), "account")
        role = nonempty_text(item.get("candidate_role"), "candidate_role")
        roles[account].add(role)
    payload = {
        "hypotheses": {
            account: tuple(sorted(values)) for account, values in sorted(roles.items())
        },
        "executable": False,
    }
    return artifact("account-role-hypotheses", payload)


def infer_shared_resource_dependencies(
    observations: Iterable[Mapping[str, Any]],
) -> ResearchArtifact:
    resources: dict[str, set[str]] = defaultdict(set)
    for item in observations:
        operation = nonempty_text(item.get("operation"), "operation")
        for resource in item.get("resources", ()):
            resources[nonempty_text(resource, "resource")].add(operation)
    shared = {
        resource: tuple(sorted(operations))
        for resource, operations in sorted(resources.items())
        if len(operations) > 1
    }
    return artifact(
        "shared-resource-hypotheses",
        {"shared": shared, "validated": False, "executable": False},
    )


def validate_inferred_semantics(
    inferred: ResearchArtifact,
    *,
    fixture_match: bool,
    invariant_match: bool,
) -> ResearchArtifact:
    passed = bool(fixture_match and invariant_match)
    return artifact(
        "semantics-validation",
        {
            "inferred": inferred.identity,
            "fixture_match": bool(fixture_match),
            "invariant_match": bool(invariant_match),
            "execution_promotion": False,
        },
        disposition=Disposition.PASS if passed else Disposition.REJECT,
        reason="validated-hypothesis" if passed else "semantic-hypothesis-rejected",
    )


__all__ = [
    "infer_account_relationships",
    "infer_shared_resource_dependencies",
    "reconstruct_cpi_call_graph",
    "validate_inferred_semantics",
]
