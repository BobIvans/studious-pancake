"""Static Python source analysis; unsupported languages are explicit gaps."""

from __future__ import annotations

import ast
import hashlib
from pathlib import PurePosixPath


def analyze_source(path: str, data: bytes) -> dict:
    result = {
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "symbols": [],
        "imports": [],
    }
    if not path.endswith(".py"):
        return {**result, "status": "UNSUPPORTED_LANGUAGE"}
    try:
        tree = ast.parse(data, filename=path)
    except (SyntaxError, ValueError) as exc:
        return {**result, "status": "PARSE_ERROR", "reason": str(exc)}
    offsets = [0]
    for line in data.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            result["symbols"].append(
                {
                    "name": node.name,
                    "kind": type(node).__name__,
                    "start_byte": offsets[node.lineno - 1] + node.col_offset,
                    "end_byte": offsets[node.end_lineno - 1] + node.end_col_offset,
                }
            )
        elif isinstance(node, ast.Import):
            result["imports"].extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            parts = list(PurePosixPath(path).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            else:
                parts = parts[:-1]
            if node.level:
                base = parts[: len(parts) - node.level + 1]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            result["imports"].append(module)
            result["imports"].extend(
                f"{module}.{alias.name}".strip(".")
                for alias in node.names
                if alias.name != "*"
            )
    result["imports"] = sorted(set(result["imports"]))
    result["symbols"].sort(key=lambda s: (s["start_byte"], s["name"]))
    return {**result, "status": "ANALYZED"}


def partition_source(path: str, data: bytes, *, max_bytes: int = 32_768) -> list[dict]:
    if max_bytes < 1:
        raise ValueError("positive part budget required")
    sha = hashlib.sha256(data).hexdigest()
    return [
        {
            "path": path,
            "sha256": sha,
            "start_byte": i,
            "end_byte": min(i + max_bytes, len(data)),
            "part_sha256": hashlib.sha256(data[i : i + max_bytes]).hexdigest(),
        }
        for i in range(0, len(data), max_bytes)
    ]


def build_import_graph(analyses: list[dict]) -> dict[str, list[str]]:
    modules = {}
    for item in analyses:
        if item["path"].endswith(".py"):
            name = item["path"][:-3].replace("/", ".")
            if name.endswith(".__init__"):
                name = name[:-9]
            modules[name] = item["path"]
    graph = {}
    for item in analyses:
        dependencies = set()
        for name in item["imports"]:
            while name:
                if name in modules:
                    dependencies.add(modules[name])
                    break
                name = name.rpartition(".")[0]
        graph[item["path"]] = sorted(dependencies)
    return graph


def resolve_reverse_imports(graph: dict[str, list[str]]) -> dict[str, list[str]]:
    reverse = {key: [] for key in graph}
    for source, targets in graph.items():
        for target in targets:
            reverse.setdefault(target, []).append(source)
    return {key: sorted(value) for key, value in sorted(reverse.items())}
