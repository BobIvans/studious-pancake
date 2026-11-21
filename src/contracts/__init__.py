"""Canonical structured-boundary contracts."""

from .registry import (
    PayloadLimits,
    PayloadValidationError,
    SchemaNotRegisteredError,
    SchemaCompatibilityReport,
    SchemaRecord,
    SchemaRegistry,
    SchemaRegistryError,
    get_schema_registry,
)

__all__ = [
    "PayloadLimits",
    "PayloadValidationError",
    "SchemaNotRegisteredError",
    "SchemaCompatibilityReport",
    "SchemaRecord",
    "SchemaRegistry",
    "SchemaRegistryError",
    "get_schema_registry",
]
