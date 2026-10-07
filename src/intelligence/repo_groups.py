"""Iterative SCC decomposition and bounded exact logical segments."""

from .repo_source import resolve_reverse_imports


def build_scc_groups(graph: dict[str, list[str]]) -> list[list[str]]:
    seen, order = set(), []
    for root in sorted(graph):
        stack = [(root, False)]
        while stack:
            node, done = stack.pop()
            if done:
                order.append(node)
            elif node not in seen:
                seen.add(node)
                stack.append((node, True))
                stack.extend(
                    (n, False) for n in reversed(graph.get(node, [])) if n not in seen
                )
    reverse = resolve_reverse_imports(graph)
    seen, groups = set(), []
    for root in reversed(order):
        if root in seen:
            continue
        group, stack = [], [root]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            group.append(node)
            stack.extend(reverse.get(node, []))
        groups.append(sorted(group))
    return sorted(groups)


def build_logical_segments(
    groups: list[list[str]], analyses: list[dict], *, max_bytes: int = 128_000
) -> list[dict]:
    if max_bytes < 1:
        raise ValueError("positive segment budget required")
    by_path = {a["path"]: a for a in analyses}
    return [
        {
            "paths": group,
            "bytes": sum(by_path[p]["bytes"] for p in group),
            "status": (
                "OVERSIZED"
                if sum(by_path[p]["bytes"] for p in group) > max_bytes
                else "BOUNDED"
            ),
            "source_refs": [{"path": p, "sha256": by_path[p]["sha256"]} for p in group],
        }
        for group in groups
    ]


def attach_tests_and_contracts(groups: list[dict], paths: list[str]) -> list[dict]:
    for group in groups:
        stems = {p.rsplit("/", 1)[-1].removesuffix(".py") for p in group["paths"]}
        group["related_paths"] = sorted(
            p for p in paths if any(s in p for s in stems) and p not in group["paths"]
        )
        group["relation_basis"] = "filename heuristic; imports remain authoritative"
    return groups


def report_oversized_groups(groups: list[dict]) -> list[dict]:
    return [g for g in groups if g["status"] == "OVERSIZED"]
