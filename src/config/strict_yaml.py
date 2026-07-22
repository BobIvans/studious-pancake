"""Strict, bounded YAML ingestion for security-sensitive configuration.

PR-190 deliberately supports only a small YAML subset: mappings with string keys,
sequences and JSON-like scalar values. Anchors, aliases, merge keys, duplicate
keys, custom tags and implicit timestamps are rejected before construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from yaml.events import AliasEvent, CollectionEndEvent, CollectionStartEvent
from yaml.nodes import MappingNode, ScalarNode


class StrictYamlError(ValueError):
    """Raised when configuration bytes are ambiguous or exceed safety limits."""


@dataclass(frozen=True, slots=True)
class StrictYamlLimits:
    max_bytes: int = 1_048_576
    max_depth: int = 64
    max_nodes: int = 100_000


class _StrictLoader(yaml.SafeLoader):
    pass


for first_char, resolvers in list(_StrictLoader.yaml_implicit_resolvers.items()):
    _StrictLoader.yaml_implicit_resolvers[first_char] = [
        resolver
        for resolver in resolvers
        if resolver[0] != "tag:yaml.org,2002:timestamp"
    ]


def _construct_mapping(
    loader: _StrictLoader, node: MappingNode, deep: bool = False
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key_node, value_node in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            raise StrictYamlError("YAML merge keys are forbidden")
        if (
            not isinstance(key_node, ScalarNode)
            or key_node.tag != "tag:yaml.org,2002:str"
        ):
            raise StrictYamlError("configuration mapping keys must be explicit strings")
        key = loader.construct_scalar(key_node)
        if key == "<<":
            raise StrictYamlError("YAML merge keys are forbidden")
        if key in result:
            mark = getattr(key_node, "start_mark", None)
            location = (
                ""
                if mark is None
                else f" at line {mark.line + 1}, column {mark.column + 1}"
            )
            raise StrictYamlError(f"duplicate YAML key {key!r}{location}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _preflight(text: str, *, limits: StrictYamlLimits) -> None:
    raw_size = len(text.encode("utf-8"))
    if raw_size > limits.max_bytes:
        raise StrictYamlError(
            f"configuration exceeds {limits.max_bytes} byte limit: {raw_size}"
        )

    depth = 0
    nodes = 0
    try:
        for event in yaml.parse(text, Loader=_StrictLoader):
            nodes += 1
            if nodes > limits.max_nodes:
                raise StrictYamlError(
                    f"configuration exceeds {limits.max_nodes} YAML event limit"
                )
            if isinstance(event, AliasEvent):
                raise StrictYamlError("YAML aliases are forbidden")
            if getattr(event, "anchor", None) is not None:
                raise StrictYamlError("YAML anchors are forbidden")
            if isinstance(event, CollectionStartEvent):
                depth += 1
                if depth > limits.max_depth:
                    raise StrictYamlError(
                        f"configuration exceeds depth limit {limits.max_depth}"
                    )
            elif isinstance(event, CollectionEndEvent):
                depth -= 1
    except yaml.YAMLError as exc:
        raise StrictYamlError(f"invalid YAML: {exc}") from exc


def loads_strict_yaml(
    text: str,
    *,
    limits: StrictYamlLimits | None = None,
    require_mapping: bool = True,
) -> Any:
    """Parse a bounded unambiguous YAML document."""

    selected_limits = limits or StrictYamlLimits()
    _preflight(text, limits=selected_limits)
    try:
        value = yaml.load(text, Loader=_StrictLoader)
    except (yaml.YAMLError, StrictYamlError) as exc:
        if isinstance(exc, StrictYamlError):
            raise
        raise StrictYamlError(f"invalid YAML: {exc}") from exc
    if value is None:
        value = {}
    if require_mapping and not isinstance(value, dict):
        raise StrictYamlError("configuration root must be a mapping")
    return value


def load_strict_yaml(
    path: str | Path,
    *,
    limits: StrictYamlLimits | None = None,
    require_mapping: bool = True,
) -> Any:
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise StrictYamlError(f"cannot read configuration file {source}: {exc}") from exc
    return loads_strict_yaml(text, limits=limits, require_mapping=require_mapping)


__all__ = [
    "StrictYamlError",
    "StrictYamlLimits",
    "load_strict_yaml",
    "loads_strict_yaml",
]
