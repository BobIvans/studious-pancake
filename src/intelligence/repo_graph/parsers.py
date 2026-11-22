"""Tree-sitter structural parser adapters (OCA-W0B2).

Import-guarded: grammars are an optional pinned dependency
(dev profile pins). When absent, callers must record explicit
PARTIAL/UNSUPPORTED states with reasons — never a silent fallback. Python
keeps the native stdlib-AST pipeline as primary (contract §4).
"""

from __future__ import annotations

from typing import Any

# Pinned grammar set for detected first-party languages beyond Python's
# native AST. Versions are recorded in the build receipt.
GRAMMAR_PACKS: dict[str, str] = {
    "bash": "tree-sitter-bash==0.25.1",
    "yaml": "tree-sitter-yaml==0.7.2",
    "markdown": "tree-sitter-markdown==0.5.4",
}
CORE_PACKAGE = "tree-sitter==0.25.2"

# Structural node types collected per grammar (deterministic extraction spec).
STRUCTURAL_NODE_SPEC: dict[str, dict[str, str]] = {
    "bash": {"function_definition": "function"},
    "yaml": {"block_mapping_pair": "mapping_key"},
    "markdown": {"atx_heading": "heading", "link_text": "link"},
}


def available_languages() -> dict[str, str]:
    """Return {language: grammar version} for importable grammars."""
    from importlib import import_module
    from importlib.metadata import version

    modules = {
        "bash": "tree_sitter_bash",
        "yaml": "tree_sitter_yaml",
        "markdown": "tree_sitter_markdown",
    }
    available: dict[str, str] = {}
    for language, module_name in modules.items():
        try:
            import_module(module_name)
            available[language] = version(module_name.replace("_", "-"))
        except Exception:  # noqa: BLE001 - optional-grammar absence is expected
            continue
    return available


def capability_report() -> dict[str, Any]:
    """Deterministic capability report for receipts (installed vs pinned)."""
    available = available_languages()
    return {
        "core": {
            "package": CORE_PACKAGE,
            "installed": _core_installed(),
        },
        "grammars": {
            language: {
                "pinned": GRAMMAR_PACKS[language],
                "installed_version": available.get(language),
                "available": language in available,
            }
            for language in sorted(GRAMMAR_PACKS)
        },
    }


def _core_installed() -> bool:
    try:
        import tree_sitter  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def parse_structural(language: str, data: bytes) -> dict[str, Any] | None:
    """Parse with the tree-sitter grammar for ``language``.

    Returns {"declarations": [...], "grammar_version": ...} or None when the
    grammar is unavailable (caller records the explicit gap).
    """
    if language not in GRAMMAR_PACKS:
        return None
    try:
        from importlib import import_module

        from tree_sitter import Language, Parser
    except Exception:  # noqa: BLE001 - optional dependency absent
        return None
    module_map = {
        "bash": "tree_sitter_bash",
        "yaml": "tree_sitter_yaml",
        "markdown": "tree_sitter_markdown",
    }
    try:
        module = import_module(module_map[language])
        parser = Parser(Language(module.language()))
        tree = parser.parse(data)
    except Exception:  # noqa: BLE001 - parse failure stays explicit
        return None
    spec = STRUCTURAL_NODE_SPEC.get(language, {})
    declarations: list[dict[str, Any]] = []
    _collect(tree.root_node, data, spec, [], declarations)
    declarations.sort(key=lambda item: (item["start_byte"], item["qualified_name"]))
    from importlib.metadata import version

    return {
        "declarations": declarations,
        "grammar_version": version(module_map[language].replace("_", "-")),
    }


def _collect(
    node: Any,
    data: bytes,
    spec: dict[str, str],
    stack: list[str],
    out: list[dict[str, Any]],
) -> None:
    kind = spec.get(node.type)
    if kind is not None:
        text = data[node.start_byte : node.end_byte].decode("utf-8", "replace")
        name = _node_name(node, data, kind)
        qualified = ".".join([*stack, name]) if stack else name
        out.append(
            {
                "kind": kind,
                "name": name,
                "qualified_name": qualified,
                "start_byte": node.start_byte,
                "end_byte": node.end_byte,
                "preview": text[:120],
            }
        )
        stack = [*stack, name]
    for child in node.children:
        _collect(child, data, spec, stack, out)


def _node_name(node: Any, data: bytes, kind: str) -> str:
    if kind == "heading":
        text = data[node.start_byte : node.end_byte].decode("utf-8", "replace")
        return text.lstrip("#").strip()[:80] or "heading"
    if kind == "mapping_key":
        for child in node.children:
            if child.type == "block_node" or child.type.endswith("key"):
                return (
                    data[child.start_byte : child.end_byte]
                    .decode("utf-8", "replace")
                    .strip()[:80]
                )
        return "key"
    for child in node.children:
        if child.type == "word" or child.type == "name" or child.type == "command_name":
            return data[child.start_byte : child.end_byte].decode("utf-8", "replace")[
                :80
            ]
    return "anonymous"
