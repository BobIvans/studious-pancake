"""Python AST symbol extraction with qualified names, scopes and call sites.

Pure stdlib ``ast`` (no tree-sitter, no model APIs). Other languages are
explicit coverage gaps handled by the inventory, never silently skipped.
"""

from __future__ import annotations

import ast
import tokenize
import io
from pathlib import PurePosixPath
from typing import Any, cast

from .schema import KIND_CLASS, KIND_FUNCTION, KIND_MODULE, stable_symbol_id


class _ScopeVisitor(ast.NodeVisitor):
    def __init__(self, path: str, offsets: list[int]) -> None:
        self._path = path
        self._offsets = offsets
        self.symbols: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self._stack: list[str] = []

    # -- helpers ---------------------------------------------------------
    def _byte_range(self, node: ast.AST) -> tuple[int, int]:
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        start = self._offsets[node.lineno - 1] + node.col_offset
        assert node.end_lineno is not None and node.end_col_offset is not None
        end = self._offsets[node.end_lineno - 1] + node.end_col_offset
        return start, end

    def _signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        names = [arg.arg for arg in node.args.args]
        if node.args.vararg is not None:
            names.append(f"*{node.args.vararg.arg}")
        elif node.args.kwonlyargs:
            names.append("*")
        names.extend(arg.arg for arg in node.args.kwonlyargs)
        if node.args.kwarg is not None:
            names.append(f"**{node.args.kwarg.arg}")
        return f"{node.name}({', '.join(names)})"

    def _emit(self, node: ast.AST, kind: str) -> str:
        name = getattr(node, "name")
        qualified = ".".join([*self._stack, name])
        start, end = self._byte_range(node)
        symbol_id = stable_symbol_id(self._path, qualified)
        signature = (
            self._signature(cast(ast.FunctionDef, node))
            if kind == KIND_FUNCTION
            else None
        )
        record: dict[str, Any] = {
            "symbol_id": symbol_id,
            "path": self._path,
            "kind": kind,
            "name": name,
            "qualified_name": qualified,
            "parent_qualified": ".".join(self._stack) if self._stack else None,
            "signature": signature,
            "start_byte": start,
            "end_byte": end,
            "docstring": bool(ast.get_docstring(cast(ast.ClassDef, node))),
        }
        self.symbols.append(record)
        return qualified

    # -- visitors --------------------------------------------------------
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._emit(node, KIND_FUNCTION)
        # The stack holds bare name components; qualified names are rebuilt at
        # emit time, so nested scopes join correctly.
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._emit(node, KIND_FUNCTION)
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._emit(node, KIND_CLASS)
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if self._stack:
            caller = ".".join(self._stack)
        else:
            caller = ""
        self.calls.append(
            {
                "caller_qualified": caller,
                "target_expr": ast.unparse(node.func),
                "lineno": node.lineno,
            }
        )
        self.generic_visit(node)


def module_name(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else path


def parse_python_module(path: str, data: bytes) -> dict[str, Any]:
    """Parse one Python module into deterministic symbol/call/import records."""
    offsets = [0]
    for line in data.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    if data.startswith(b"\xef\xbb\xbf"):
        offsets[0] = 3
    tree = ast.parse(data, filename=path)
    visitor = _ScopeVisitor(path, offsets)
    visitor.visit(tree)

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # Relative-import base computation mirrors repo_source.build_import
            # resolution exactly (the proven CTX-02 primitive).
            parts = list(PurePosixPath(path).with_suffix("").parts)
            if parts and parts[-1] == "__init__":
                parts.pop()
            else:
                parts = parts[:-1]
            if node.level:
                base = parts[: len(parts) - node.level + 1]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            imports.append(module)
            imports.extend(
                f"{module}.{alias.name}".strip(".")
                for alias in node.names
                if alias.name != "*"
            )

    module_symbol = {
        "symbol_id": stable_symbol_id(path, module_name(path)),
        "path": path,
        "kind": KIND_MODULE,
        "name": module_name(path),
        "qualified_name": module_name(path),
        "parent_qualified": None,
        "signature": None,
        "start_byte": 0,
        "end_byte": len(data),
        "docstring": bool(ast.get_docstring(tree)),
    }
    symbols = [module_symbol] + sorted(
        visitor.symbols, key=lambda item: (item["start_byte"], item["qualified_name"])
    )
    # Conditional redefinitions can repeat a qualified name inside one module;
    # disambiguate deterministically by source order (contract 2.2: stable ID).
    seen_ids: dict[str, int] = {}
    for symbol in symbols:
        base = symbol["symbol_id"]
        occurrence = seen_ids.get(base, 0)
        seen_ids[base] = occurrence + 1
        if occurrence:
            symbol["symbol_id"] = f"{base}#{occurrence}"
    calls = sorted(
        visitor.calls, key=lambda item: (item["lineno"], item["target_expr"])
    )
    return {
        "path": path,
        "module": module_name(path),
        "symbols": symbols,
        "imports": sorted(set(imports)),
        "calls": calls,
        "defines": [symbol["symbol_id"] for symbol in symbols],
    }


def detect_encoding(data: bytes) -> str | None:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return None
    return encoding if encoding in {"utf-8", "utf-8-sig", "ascii"} else encoding
