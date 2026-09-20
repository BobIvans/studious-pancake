"""Installed canonical schema, compatibility, and digest authority."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
import json
from typing import Any, Final

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from src.kernel import CanonicalJsonError, canonical_json_bytes, domain_sha256

_REGISTRY_RESOURCE: Final = "schema_registry.json"
_REGISTRY_SCHEMA_ID: Final = "canonical.schema-registry.v1"
_DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"
_ALLOWED_COMPATIBILITY: Final = {
    "exact-byte-identity",
    "backward-readable",
    "forward-tolerant",
    "migration-required",
    "forbidden-to-mix",
}
_ALLOWED_UNKNOWN_FIELDS: Final = {"reject", "allow-namespaced-extensions"}
_ALLOWED_STATUS: Final = {"active", "supported", "retired"}
_ALLOWED_VALIDATION_MODE: Final = {"metadata-only", "json-schema"}


class SchemaRegistryError(ValueError):
    """Raised when the installed registry is malformed or ambiguous."""


class SchemaNotRegisteredError(SchemaRegistryError):
    """Raised when a payload refers to an unknown schema identity."""


class PayloadValidationError(SchemaRegistryError):
    """Raised when a payload violates its registered contract or limits."""


@dataclass(frozen=True, slots=True)
class PayloadLimits:
    max_bytes: int
    max_depth: int
    max_nodes: int
    max_list_items: int
    max_string_length: int
    max_integer_abs: int


@dataclass(frozen=True, slots=True)
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
    max_list_items: int
    max_string_length: int
    max_integer_abs: int
    status: str
    validation_mode: str
    schema: Mapping[str, Any] | None

    @property
    def limits(self) -> PayloadLimits:
        return PayloadLimits(
            max_bytes=self.max_bytes,
            max_depth=self.max_depth,
            max_nodes=self.max_nodes,
            max_list_items=self.max_list_items,
            max_string_length=self.max_string_length,
            max_integer_abs=self.max_integer_abs,
        )


def _object_without_duplicate_keys(
    pairs: Sequence[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise SchemaRegistryError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load_json(text: str) -> dict[str, object]:
    try:
        value = json.loads(text, object_pairs_hook=_object_without_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise SchemaRegistryError("schema registry is not valid JSON") from exc
    if not isinstance(value, dict):
        raise SchemaRegistryError("schema registry root must be an object")
    return value


def _required_text(value: Mapping[str, object], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise SchemaRegistryError(f"{name} must be non-empty text")
    return item


def _positive_int(
    value: Mapping[str, object],
    name: str,
    *,
    default: int | None = None,
) -> int:
    item = value.get(name, default)
    if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
        raise SchemaRegistryError(f"{name} must be a positive integer")
    return item


def _walk_limits(value: object, limits: PayloadLimits) -> None:
    nodes = 0

    def visit(item: object, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > limits.max_nodes:
            raise PayloadValidationError("payload node count exceeds registered limit")
        if depth > limits.max_depth:
            raise PayloadValidationError("payload nesting exceeds registered limit")
        if isinstance(item, str):
            if len(item) > limits.max_string_length:
                raise PayloadValidationError("payload string exceeds registered limit")
            return
        if isinstance(item, bool) or item is None:
            return
        if isinstance(item, int):
            if abs(item) > limits.max_integer_abs:
                raise PayloadValidationError("payload integer exceeds registered limit")
            return
        if isinstance(item, Mapping):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise PayloadValidationError("payload object keys must be strings")
                visit(key, depth + 1)
                visit(child, depth + 1)
            return
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            if len(item) > limits.max_list_items:
                raise PayloadValidationError("payload list exceeds registered limit")
            for child in item:
                visit(child, depth + 1)
            return
        raise PayloadValidationError(
            f"payload contains unsupported type: {type(item).__name__}"
        )

    visit(value, 0)


@dataclass(frozen=True, slots=True)
class SchemaRegistry:
    records: tuple[SchemaRecord, ...]
    raw_registry: Mapping[str, object]

    @classmethod
    def from_json_text(cls, text: str) -> "SchemaRegistry":
        payload = _load_json(text)
        if payload.get("schema_id") != _REGISTRY_SCHEMA_ID:
            raise SchemaRegistryError("unexpected registry schema_id")
        if payload.get("dialect") != _DIALECT:
            raise SchemaRegistryError("unsupported schema registry dialect")
        expected_authority = {
            "module": "src.contracts.registry",
            "resource": "src/resources/schema_registry.json",
            "canonical_json_module": "src.kernel.canonical_json",
            "hash_module": "src.kernel.hashing",
        }
        if payload.get("authority") != expected_authority:
            raise SchemaRegistryError(
                "schema registry authority declaration is not canonical"
            )
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
        return cls(tuple(records), payload)

    @classmethod
    def load_default(cls) -> "SchemaRegistry":
        raw = (
            files("src.resources")
            .joinpath(_REGISTRY_RESOURCE)
            .read_text(encoding="utf-8")
        )
        return cls.from_json_text(raw)

    def require(self, schema_id: str) -> SchemaRecord:
        for record in self.records:
            if record.schema_id == schema_id:
                return record
        raise SchemaNotRegisteredError(f"unregistered schema_id: {schema_id}")

    @property
    def active_ids(self) -> frozenset[str]:
        return frozenset(
            record.schema_id for record in self.records if record.status == "active"
        )

    @property
    def registry_digest(self) -> str:
        return domain_sha256(
            domain="schema-registry",
            schema_id=_REGISTRY_SCHEMA_ID,
            payload=canonical_json_bytes(self.raw_registry),
        )

    def validate_payload(self, schema_id: str, payload: object) -> bytes:
        record = self.require(schema_id)
        _walk_limits(payload, record.limits)
        try:
            encoded = canonical_json_bytes(payload)
        except CanonicalJsonError as exc:
            raise PayloadValidationError(str(exc)) from exc
        if len(encoded) > record.max_bytes:
            raise PayloadValidationError("payload bytes exceed registered limit")
        if record.validation_mode == "json-schema":
            if record.schema is None:
                raise SchemaRegistryError(f"JSON schema missing for {schema_id}")
            try:
                Draft202012Validator(record.schema).validate(payload)
            except ValidationError as exc:
                path = ".".join(str(part) for part in exc.absolute_path) or "<root>"
                raise PayloadValidationError(
                    f"payload does not match {schema_id} at {path}: {exc.message}"
                ) from exc
        return encoded

    def payload_digest(
        self,
        *,
        schema_id: str,
        payload: object,
        domain: str | None = None,
    ) -> str:
        encoded = self.validate_payload(schema_id, payload)
        return domain_sha256(
            domain=domain or f"schema-payload:{schema_id}",
            schema_id=schema_id,
            payload=encoded,
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
    schema_id = _required_text(item, "schema_id")
    version_suffixes = tuple(f".v{i}" for i in range(1, 100))
    if schema_id.strip() != schema_id or not schema_id.endswith(version_suffixes):
        raise SchemaRegistryError(f"invalid schema_id: {schema_id!r}")
    compatibility = _required_text(item, "compatibility")
    if compatibility not in _ALLOWED_COMPATIBILITY:
        raise SchemaRegistryError(
            f"invalid compatibility for {schema_id}: {compatibility}"
        )
    unknown_fields = _required_text(item, "unknown_fields")
    if unknown_fields not in _ALLOWED_UNKNOWN_FIELDS:
        raise SchemaRegistryError(
            f"invalid unknown-field policy for {schema_id}: {unknown_fields}"
        )
    status = _required_text(item, "status")
    if status not in _ALLOWED_STATUS:
        raise SchemaRegistryError(f"invalid status for {schema_id}: {status}")
    validation_mode = item.get("validation_mode", "metadata-only")
    if not isinstance(validation_mode, str) or not validation_mode:
        raise SchemaRegistryError(
            f"validation_mode must be non-empty text for {schema_id}"
        )
    if validation_mode not in _ALLOWED_VALIDATION_MODE:
        raise SchemaRegistryError(
            f"invalid validation mode for {schema_id}: {validation_mode}"
        )
    schema = item.get("schema")
    if validation_mode == "json-schema":
        if not isinstance(schema, dict):
            raise SchemaRegistryError(f"JSON schema missing for {schema_id}")
        if schema.get("$schema") != _DIALECT:
            raise SchemaRegistryError(f"schema dialect mismatch for {schema_id}")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise SchemaRegistryError(f"invalid JSON schema for {schema_id}") from exc
    elif schema is not None:
        raise SchemaRegistryError(
            f"metadata-only schema {schema_id} embeds a JSON schema"
        )
    return SchemaRecord(
        schema_id=schema_id,
        owner_module=_required_text(item, "owner_module"),
        boundary_class=_required_text(item, "boundary_class"),
        compatibility=compatibility,
        unknown_fields=unknown_fields,
        canonical_encoding=_required_text(item, "canonical_encoding"),
        max_bytes=_positive_int(item, "max_bytes"),
        max_depth=_positive_int(item, "max_depth"),
        max_nodes=_positive_int(item, "max_nodes"),
        max_list_items=_positive_int(item, "max_list_items", default=100_000),
        max_string_length=_positive_int(item, "max_string_length", default=1_048_576),
        max_integer_abs=_positive_int(
            item, "max_integer_abs", default=9_223_372_036_854_775_807
        ),
        status=status,
        validation_mode=validation_mode,
        schema=schema,
    )


@lru_cache(maxsize=1)
def get_schema_registry() -> SchemaRegistry:
    """Load and cache the installed canonical registry."""

    return SchemaRegistry.load_default()
