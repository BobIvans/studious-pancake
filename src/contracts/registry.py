"""Installed canonical schema registry."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
import json
from typing import Any


class SchemaRegistryError(ValueError):
    """Raised when the installed registry is malformed or ambiguous."""


@dataclass(frozen=True)
class SchemaRecord:
    schema_id: str
    owner_module: str
    boundary_class: str
    compatibility: str
    unknown_fields: str
    canonical_encoding: str
    max_bytes: int
    max_depth: int
    max_nodes: int
    status: str


@dataclass(frozen=True)
class SchemaRegistry:
    records: tuple[SchemaRecord, ...]

    @classmethod
    def load_default(cls) -> "SchemaRegistry":
        raw = files("src.resources").joinpath("schema_registry.json").read_text(
            encoding="utf-8"
        )
        payload = json.loads(raw)
        if payload.get("schema_id") != "canonical.schema-registry.v1":
            raise SchemaRegistryError("unexpected registry schema_id")
        entries = payload.get("schemas")
        if not isinstance(entries, list) or not entries:
            raise SchemaRegistryError("registry must contain schemas")
        records: list[SchemaRecord] = []
        seen: set[str] = set()
        for item in entries:
            if not isinstance(item, dict):
                raise SchemaRegistryError("schema entries must be objects")
            record = _record(item)
            if record.schema_id in seen:
                raise SchemaRegistryError(f"duplicate schema_id: {record.schema_id}")
            seen.add(record.schema_id)
            records.append(record)
        return cls(tuple(records))

    def require(self, schema_id: str) -> SchemaRecord:
        for record in self.records:
            if record.schema_id == schema_id:
                return record
        raise SchemaRegistryError(f"unregistered schema_id: {schema_id}")

    @property
    def active_ids(self) -> frozenset[str]:
        return frozenset(
            record.schema_id for record in self.records if record.status == "active"
        )


def _record(item: dict[str, Any]) -> SchemaRecord:
    required = {
        "schema_id",
        "owner_module",
        "boundary_class",
        "compatibility",
        "unknown_fields",
        "canonical_encoding",
        "max_bytes",
        "max_depth",
        "max_nodes",
        "status",
    }
    missing = required - item.keys()
    if missing:
        raise SchemaRegistryError(f"schema entry missing fields: {sorted(missing)!r}")
    schema_id = str(item["schema_id"])
    version_suffixes = tuple(f".v{i}" for i in range(1, 100))
    if (
        not schema_id
        or schema_id.strip() != schema_id
        or not schema_id.endswith(version_suffixes)
    ):
        raise SchemaRegistryError(f"invalid schema_id: {schema_id!r}")
    values = {
        name: int(item[name]) for name in ("max_bytes", "max_depth", "max_nodes")
    }
    if any(value <= 0 for value in values.values()):
        raise SchemaRegistryError(f"schema limits must be positive: {schema_id}")
    status = str(item["status"])
    if status not in {"active", "supported", "retired"}:
        raise SchemaRegistryError(f"invalid status for {schema_id}: {status}")
    return SchemaRecord(
        schema_id=schema_id,
        owner_module=str(item["owner_module"]),
        boundary_class=str(item["boundary_class"]),
        compatibility=str(item["compatibility"]),
        unknown_fields=str(item["unknown_fields"]),
        canonical_encoding=str(item["canonical_encoding"]),
        max_bytes=values["max_bytes"],
        max_depth=values["max_depth"],
        max_nodes=values["max_nodes"],
        status=status,
    )
