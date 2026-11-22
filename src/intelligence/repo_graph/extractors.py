"""Structured extractors for docs/configs/schemas/tests/workflows/build files.

Stdlib-only deterministic extraction (OCA-W0B2 §2.3). Config keys, flags and
env-var NAMES are extracted — values never are (secret-exclusion rule).
"""

from __future__ import annotations

import configparser
import json
import re
import tomllib
from pathlib import PurePosixPath
from typing import Any

from .schema import stable_node_id

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_ADR_RE = re.compile(r"(ADR[-_ ]?\d+)", re.IGNORECASE)
_ENV_NAME_RE = re.compile(r"^([A-Z][A-Z0-9_]+)=", re.MULTILINE)
_DEP_PIN_RE = re.compile(r"^([A-Za-z0-9_.\[\]-]+)==([^\s\\]+)", re.MULTILINE)


def classify_artifact(path: str, snapshot_status: str) -> dict[str, str]:
    """Deterministic artifact-class + language classification for one path."""
    lowered = path.lower()
    name = PurePosixPath(path).name.lower()
    suffix = lowered.rsplit(".", 1)[-1] if "." in lowered else ""
    first_party = not (
        lowered.startswith(("docs/vendor", "vendor-docs"))
        or "/contracts/" in lowered
        and suffix == "rs"
    )
    language = {
        "py": "python",
        "rs": "rust",
        "sh": "bash",
        "yaml": "yaml",
        "yml": "yaml",
        "json": "json",
        "toml": "toml",
        "md": "markdown",
        "ini": "ini",
        "cfg": "ini",
        "txt": "text",
        "lock": "text",
    }.get(suffix, "other")
    if snapshot_status in {"SECRET_METADATA_ONLY", "OVERSIZED", "SUBMODULE", "SYMLINK"}:
        artifact_class = (
            "secret_excluded"
            if snapshot_status == "SECRET_METADATA_ONLY"
            else "other_tracked"
        )
    elif lowered.startswith(".github/workflows/") and suffix in {"yml", "yaml"}:
        artifact_class = "workflow"
    elif lowered.startswith("tests/"):
        artifact_class = (
            "data_fixture"
            if suffix == "json"
            else ("test_code" if suffix == "py" else "config")
        )
    elif "schema" in name and suffix == "json":
        artifact_class = "schema"
    elif lowered.startswith("src/resources/") and suffix in {"rs", "json"}:
        artifact_class = "vendor_reference" if suffix == "rs" else "schema"
    elif lowered.startswith("docs/") and suffix == "md":
        artifact_class = "doc"
    elif suffix == "py":
        artifact_class = "script" if lowered.startswith("scripts/") else "python_source"
    elif name in {"pyproject.toml"} or lowered == "pyproject.toml":
        artifact_class = "build_definition"
    elif "requirements" in name and (suffix == "lock" or "requirements" in name):
        artifact_class = "dependency_lock"
    elif suffix in {"yml", "yaml", "json", "toml", "ini", "cfg"}:
        artifact_class = "config"
    elif suffix == "md":
        artifact_class = "doc"
    elif suffix == "sh":
        artifact_class = "script"
    elif suffix in {"txt"}:
        artifact_class = "doc" if lowered.startswith("docs/") else "other_tracked"
    else:
        artifact_class = "other_tracked"
    return {
        "artifact_class": artifact_class,
        "language": language,
        "first_party": str(first_party),
    }


def extract_structured(path: str, data: bytes) -> dict[str, Any] | None:
    """Extract typed nodes for non-Python structured artifacts.

    Returns {"nodes": [...], "parser": <identity>} or None when no extractor
    applies (caller assigns the explicit coverage status).
    """
    lowered = path.lower()
    suffix = lowered.rsplit(".", 1)[-1] if "." in lowered else ""
    if suffix == "json":
        return _extract_json(path, data)
    if suffix == "toml":
        return _extract_toml(path, data)
    if suffix in {"ini", "cfg"}:
        return _extract_ini(path, data)
    if suffix == "lock" or "requirements" in lowered:
        return _extract_dependency_pins(path, data)
    if suffix in {"yml", "yaml"} and lowered.startswith(".github/workflows/"):
        return _extract_workflow_fallback(path, data)
    if suffix == "md":
        return _extract_markdown(path, data)
    return None


def _extract_json(path: str, data: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return {"nodes": [], "parser": "stdlib-json:PARSE_ERROR"}
    nodes: list[dict[str, Any]] = []

    def walk(value: Any, prefix: str, depth: int) -> None:
        if depth > 6 or len(nodes) > 400:
            return
        if isinstance(value, dict):
            for key in sorted(value):
                qualified = f"{prefix}.{key}" if prefix else key
                nodes.append(
                    {
                        "symbol_id": stable_node_id("json", path, qualified),
                        "path": path,
                        "language": "json",
                        "kind": (
                            "schema_field" if "schema" in path.lower() else "config_key"
                        ),
                        "name": key,
                        "qualified_name": qualified,
                        "start_byte": 0,
                        "end_byte": len(data),
                    }
                )
                walk(value[key], qualified, depth + 1)

    walk(payload, "", 0)
    return {"nodes": nodes, "parser": "stdlib-json"}


def _extract_toml(path: str, data: bytes) -> dict[str, Any] | None:
    try:
        payload = tomllib.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"nodes": [], "parser": "stdlib-tomllib:PARSE_ERROR"}
    nodes: list[dict[str, Any]] = []

    def walk(value: dict[str, Any], prefix: str, depth: int) -> None:
        if depth > 6 or len(nodes) > 400:
            return
        for key in sorted(value):
            qualified = f"{prefix}.{key}" if prefix else key
            nodes.append(
                {
                    "symbol_id": stable_node_id("toml", path, qualified),
                    "path": path,
                    "language": "toml",
                    "kind": "config_key",
                    "name": key,
                    "qualified_name": qualified,
                    "start_byte": 0,
                    "end_byte": len(data),
                }
            )
            if isinstance(value[key], dict):
                walk(value[key], qualified, depth + 1)

    walk(payload, "", 0)
    return {"nodes": nodes, "parser": "stdlib-tomllib"}


def _extract_ini(path: str, data: bytes) -> dict[str, Any] | None:
    parser = configparser.ConfigParser()
    try:
        parser.read_string(data.decode("utf-8", "replace"))
    except configparser.Error:
        return {"nodes": [], "parser": "configparser:PARSE_ERROR"}
    nodes: list[dict[str, Any]] = []
    for section in parser.sections():
        for key in parser.options(section):
            qualified = f"{section}.{key}"
            nodes.append(
                {
                    "symbol_id": stable_node_id("ini", path, qualified),
                    "path": path,
                    "language": "ini",
                    "kind": "config_key",
                    "name": key,
                    "qualified_name": qualified,
                    "start_byte": 0,
                    "end_byte": len(data),
                }
            )
    return {"nodes": nodes, "parser": "configparser"}


def _extract_dependency_pins(path: str, data: bytes) -> dict[str, Any] | None:
    """Dependency pins with UTF-8 BYTE offsets (P2-6 class fix).

    Character indices from the decoded-text regex are mapped back to byte
    space so expand_context byte-range slicing returns the exact original
    source bytes even when non-ASCII content precedes a pin.
    """
    text = data.decode("utf-8", "replace")

    def byte_offset(char_index: int) -> int:
        return len(text[:char_index].encode("utf-8"))

    nodes = []
    for match in _DEP_PIN_RE.finditer(text):
        package, pin = match.group(1), match.group(2)
        qualified = f"{package}=={pin}"
        nodes.append(
            {
                "symbol_id": stable_node_id("dep", path, qualified),
                "path": path,
                "language": "dep",
                "kind": "dependency_pin",
                "name": package,
                "qualified_name": qualified,
                "start_byte": byte_offset(match.start()),
                "end_byte": byte_offset(match.end()),
            }
        )
    nodes.sort(key=lambda item: item["start_byte"])
    return {"nodes": nodes, "parser": "regex-dependency-pins-utf8-bytes"}


def _extract_markdown(path: str, data: bytes) -> dict[str, Any] | None:
    """Markdown headings/links with UTF-8 BYTE offsets (P2-6).

    The regexes run on the decoded string for Unicode-safe matching, but every
    recorded start_byte/end_byte is mapped back to byte space so expand_context
    byte-range slicing stays exact.
    """
    text = data.decode("utf-8", "replace")

    def byte_offset(char_index: int) -> int:
        return len(text[:char_index].encode("utf-8"))

    nodes: list[dict[str, Any]] = []
    for match in _HEADING_RE.finditer(text):
        level = len(match.group(1))
        title = match.group(2).strip()
        qualified = f"h{level}:{title[:80]}"
        nodes.append(
            {
                "symbol_id": stable_node_id("md", path, qualified),
                "path": path,
                "language": "markdown",
                "kind": "doc_heading",
                "name": title[:80],
                "qualified_name": qualified,
                "start_byte": byte_offset(match.start()),
                "end_byte": byte_offset(match.end()),
            }
        )
    for match in _MD_LINK_RE.finditer(text):
        target = match.group(2)
        nodes.append(
            {
                "symbol_id": stable_node_id("md", path, f"link:{target[:80]}"),
                "path": path,
                "language": "markdown",
                "kind": "doc_link",
                "name": target[:80],
                "qualified_name": f"link:{target[:80]}",
                "start_byte": byte_offset(match.start()),
                "end_byte": byte_offset(match.end()),
            }
        )
    nodes.sort(key=lambda item: item["start_byte"])
    return {"nodes": nodes, "parser": "regex-markdown-utf8-bytes"}


def _extract_workflow_fallback(path: str, data: bytes) -> dict[str, Any] | None:
    """Line-based workflow job extraction (fallback when yaml grammar absent)."""
    text = data.decode("utf-8", "replace")

    def byte_offset(char_index: int) -> int:
        return len(text[:char_index].encode("utf-8"))

    nodes = []
    for match in re.finditer(r"^  ([A-Za-z0-9_-]+):\s*$", text, re.MULTILINE):
        job = match.group(1)
        nodes.append(
            {
                "symbol_id": stable_node_id("yaml", path, f"job:{job}"),
                "path": path,
                "language": "yaml",
                "kind": "workflow_job",
                "name": job,
                "qualified_name": f"job:{job}",
                "start_byte": byte_offset(match.start()),
                "end_byte": byte_offset(match.end()),
            }
        )
    return {"nodes": nodes, "parser": "line-based-workflow"}
