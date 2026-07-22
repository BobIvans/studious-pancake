import os

import pytest

from src.decision.contracts import (
    FEATURE_SPEC_VERSION,
    MODEL_ARTIFACT_VERSION,
    ModelStatus,
)
from src.decision.model import (
    CATEGORICAL,
    NUMERIC,
    _artifact_checksum,
    _model_canon,
    load_artifact,
)


def _chmod_private(path):
    os.chmod(path, 0o600)


def _challenger_artifact(**updates):
    categories = {name: ["unknown"] for name in CATEGORICAL}
    means = {name: 0 for name in NUMERIC}
    stds = {name: 1 for name in NUMERIC}
    feature_order = NUMERIC + [
        f"{key}={value}" for key in CATEGORICAL for value in categories[key]
    ]
    artifact = {
        "artifact_version": MODEL_ARTIFACT_VERSION,
        "feature_spec_version": FEATURE_SPEC_VERSION,
        "created_at": "2026-07-22T00:00:00+00:00",
        "model_status": ModelStatus.SHADOW_CHALLENGER.value,
        "reason": None,
        "split_manifest": {},
        "dependency_versions": {},
        "class_counts": {"total": 12, "positive": 6, "negative": 6},
        "feature_order": feature_order,
        "categories": categories,
        "means": means,
        "stds": stds,
        "coefficients": [0.0 for _ in feature_order],
        "intercept": 0.0,
    }
    artifact.update(updates)
    artifact["checksum"] = _artifact_checksum(artifact)
    return artifact


def _write_artifact(directory, artifact, pointer_checksum=None, name=None):
    name = name or f"artifact-{artifact['checksum'][:12]}.json"
    artifact_path = directory / name
    artifact_path.write_text(_model_canon(artifact) + "\n", encoding="utf-8")
    _chmod_private(artifact_path)
    latest = {
        "artifact": name,
        "checksum": pointer_checksum or artifact["checksum"],
    }
    latest_path = directory / "latest.json"
    latest_path.write_text(_model_canon(latest) + "\n", encoding="utf-8")
    _chmod_private(latest_path)
    return artifact_path


def test_latest_pointer_rejects_absolute_path_escape(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    outside = tmp_path / "outside.json"
    artifact = _challenger_artifact()
    outside.write_text(_model_canon(artifact) + "\n", encoding="utf-8")
    _chmod_private(outside)
    latest = root / "latest.json"
    latest.write_text(
        _model_canon({"artifact": str(outside), "checksum": artifact["checksum"]})
        + "\n",
        encoding="utf-8",
    )
    _chmod_private(latest)

    with pytest.raises(ValueError, match="absolute path"):
        load_artifact(root)


def test_pointer_checksum_is_enforced(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    artifact = _challenger_artifact()
    _write_artifact(root, artifact, pointer_checksum="0" * 64)

    with pytest.raises(ValueError, match="pointer checksum"):
        load_artifact(root)


def test_non_finite_json_artifact_is_rejected_before_checksum_trust(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    raw = (
        '{"artifact_version":"decision-linear/v1",'
        '"feature_spec_version":"pre_quote/v1",'
        '"created_at":"2026-07-22T00:00:00+00:00",'
        '"model_status":"SHADOW_CHALLENGER",'
        '"reason":null,"split_manifest":{},"dependency_versions":{},'
        '"class_counts":{"total":12,"positive":6,"negative":6},'
        '"feature_order":["candidate_age_ms"],'
        '"categories":{},"means":{},"stds":{},'
        '"coefficients":[NaN],"intercept":0,'
        '"checksum":"%s"}'
    ) % ("0" * 64)
    artifact_path = root / "artifact-nan.json"
    artifact_path.write_text(raw + "\n", encoding="utf-8")
    _chmod_private(artifact_path)
    latest = root / "latest.json"
    latest.write_text(
        _model_canon({"artifact": artifact_path.name, "checksum": "0" * 64}) + "\n",
        encoding="utf-8",
    )
    _chmod_private(latest)

    with pytest.raises(ValueError, match="non-finite"):
        load_artifact(root)


def test_feature_and_coefficient_count_must_match(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    artifact = _challenger_artifact(coefficients=[0.25])
    artifact["checksum"] = _artifact_checksum(artifact)
    _write_artifact(root, artifact)

    with pytest.raises(ValueError, match="coefficient count"):
        load_artifact(root)


def test_world_readable_artifact_permissions_fail_closed(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    artifact = _challenger_artifact()
    artifact_path = _write_artifact(root, artifact)
    os.chmod(artifact_path, 0o644)

    with pytest.raises(ValueError, match="permissions"):
        load_artifact(root)
