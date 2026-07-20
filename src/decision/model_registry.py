"""Reproducible advisory-model registry for PR-051.

The registry is an offline manifest of already-created artifacts. It is not a
runtime loader and it cannot promote a model into live policy. Its job is to
make provenance, hashes, feature spec compatibility, and advisory-only status
machine-checkable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .contracts import FEATURE_SPEC_VERSION, MODEL_ARTIFACT_VERSION, ModelStatus
from .dataset import _canon, sha256_text
from .model import load_artifact

MODEL_REGISTRY_VERSION = "pr051.model-registry.v1"


@dataclass(frozen=True, slots=True)
class ModelRegistryEntry:
    artifact_path: str
    artifact_checksum: str
    artifact_version: str
    feature_spec_version: str
    model_status: str
    advisory_only: bool
    source_dataset_hash: str | None
    evaluation_report_hash: str | None
    created_at: str | None


@dataclass(frozen=True, slots=True)
class ModelRegistryManifest:
    schema_version: str
    entries: tuple[ModelRegistryEntry, ...]
    registry_hash: str
    live_policy_schema_changed: bool = False
    runtime_promotion_allowed: bool = False


def _entry_from_artifact(path: str | Path) -> ModelRegistryEntry:
    artifact = load_artifact(path)
    artifact_version = str(artifact.get("artifact_version", ""))
    feature_spec_version = str(artifact.get("feature_spec_version", ""))
    status = str(artifact.get("model_status", ""))
    checksum = str(artifact.get("checksum", ""))
    if artifact_version != MODEL_ARTIFACT_VERSION:
        raise ValueError(f"unsupported artifact version: {artifact_version}")
    if feature_spec_version != FEATURE_SPEC_VERSION:
        raise ValueError(f"feature spec mismatch: {feature_spec_version}")
    if status not in {item.value for item in ModelStatus}:
        raise ValueError(f"unknown model status: {status}")
    if artifact.get("live_policy_schema") or artifact.get("permit"):
        raise ValueError("model artifacts must not contain live policy controls")
    return ModelRegistryEntry(
        artifact_path=str(path),
        artifact_checksum=checksum,
        artifact_version=artifact_version,
        feature_spec_version=feature_spec_version,
        model_status=status,
        advisory_only=True,
        source_dataset_hash=artifact.get("source_dataset_hash"),
        evaluation_report_hash=artifact.get("evaluation_report_hash"),
        created_at=artifact.get("created_at"),
    )


def build_model_registry(paths: Iterable[str | Path]) -> ModelRegistryManifest:
    entries = tuple(_entry_from_artifact(path) for path in sorted(map(str, paths)))
    body: dict[str, Any] = {
        "schema_version": MODEL_REGISTRY_VERSION,
        "entries": [asdict(entry) for entry in entries],
        "live_policy_schema_changed": False,
        "runtime_promotion_allowed": False,
    }
    registry_hash = sha256_text(_canon(body))
    return ModelRegistryManifest(
        schema_version=MODEL_REGISTRY_VERSION,
        entries=entries,
        registry_hash=registry_hash,
    )


def write_model_registry(
    paths: Iterable[str | Path], out_path: str | Path
) -> ModelRegistryManifest:
    manifest = build_model_registry(paths)
    serializable = asdict(manifest) | {
        "entries": [asdict(entry) for entry in manifest.entries]
    }
    Path(out_path).write_text(_canon(serializable) + "\n", encoding="utf-8")
    return manifest
