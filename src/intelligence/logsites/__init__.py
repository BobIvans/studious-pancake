"""Stable, rename-safe callsite IDs (OCA-W3). Static scanner only; no LLM."""

from .scanner import MANIFEST_SCHEMA, build_manifest, scan_module

__all__ = ["MANIFEST_SCHEMA", "build_manifest", "scan_module"]
