"""Canonical structured-boundary contracts."""

from .registry import (
    PayloadLimits,
    PayloadValidationError,
    SchemaNotRegisteredError,
    SchemaRecord,
    SchemaRegistry,
    SchemaRegistryError,
    get_schema_registry,
)

__all__ = [
    "PayloadLimits",
    "PayloadValidationError",
    "SchemaNotRegisteredError",
    "SchemaRecord",
    "SchemaRegistry",
    "SchemaRegistryError",
    "get_schema_registry",
]
