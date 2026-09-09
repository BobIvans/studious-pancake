"""MPR-44 enforced deployment, secrets, egress and supply-chain guard.

This module is deliberately side-effect free: it does not build images, read secrets,
submit transactions, or enable live mode.  It validates a materialized deployment
policy/evidence manifest so release qualification can fail closed until the real
Docker, workflow, seccomp, AppArmor, egress, secret, and artifact evidence exists.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

MPR44_SCHEMA = "mpr44.enforced-deployment-supply-chain.v1"
_SHA256 = re.compile(r"^(sha256:)?[0-9a-f]{64}$")
_FULL_GITHUB_SHA = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")

REQUIRED_RELEASE_ARTIFACTS: tuple[str, ...] = (
    "source_tree_digest",
    "wheel_digest",
    "wheelhouse_lock_digest",
    "container_image_digest",
    "sbom_digest",
    "provenance_digest",
    "signature_digest",
    "capability_manifest_digest",
    "config_generation_digest",
    "schema_fingerprint_digest",
    "deployment_policy_report",
    "seccomp_profile_digest",
    "apparmor_profile_digest",
    "egress_policy_digest",
)

REQUIRED_DEPLOYMENT_CONTROLS: tuple[str, ...] = (
    "digest_pinned_base_image",
    "offline_wheelhouse_install",
    "no_bind_mounted_source_tree",
    "read_only_root_filesystem",
    "non_root_user",
    "dropped_capabilities",
    "no_new_privileges",
    "deny_by_default_egress",
    "private_management_plane",
    "readiness_probe_uses_ready",
    "startup_probe_declared",
    "liveness_probe_declared",
    "seccomp_profile_present",
    "apparmor_profile_present",
    "explicit_writable_state_mount",
    "source_launchers_absent_from_image",
)

REQUIRED_SECRET_CONTROLS: tuple[str, ...] = (
    "secret_references_only",
    "no_plaintext_secret_environment",
    "mounted_secrets_consumed_by_entrypoint",
    "secret_rotation_drill_artifact",
    "secret_redaction_scan_artifact",
)


@dataclass(frozen=True, slots=True)
class MPR44Report:
    accepted: bool
    schema_version: str
    live_ready: bool
    paper_release_ready: bool
    blockers: tuple[str, ...]
    evidence_digest: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _bool(manifest: Mapping[str, Any], key: str) -> bool:
    value = manifest.get(key)
    if type(value) is not bool:
        raise ValueError(f"{key} must be boolean")
    return value


def _str(manifest: Mapping[str, Any], key: str) -> str:
    value = manifest.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _mapping(value: Any, key: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be an object")
    return value


def _list(value: Any, key: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return value


def _artifact_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    artifacts: dict[str, Mapping[str, Any]] = {}
    for item in _list(manifest.get("release_artifacts"), "release_artifacts"):
        row = _mapping(item, "release_artifact")
        artifact_id = _str(row, "id")
        if artifact_id in artifacts:
            raise ValueError(f"duplicate artifact id: {artifact_id}")
        artifacts[artifact_id] = row
    return artifacts


def _require_artifact(blockers: list[str], artifacts: Mapping[str, Mapping[str, Any]], artifact_id: str) -> None:
    row = artifacts.get(artifact_id)
    if row is None:
        blockers.append(f"MISSING_RELEASE_ARTIFACT:{artifact_id}")
        return
    digest = _str(row, "digest")
    if not _SHA256.fullmatch(digest):
        blockers.append(f"INVALID_ARTIFACT_DIGEST:{artifact_id}")
    if not _bool(row, "materialized"):
        blockers.append(f"ARTIFACT_NOT_MATERIALIZED:{artifact_id}")
    if not _bool(row, "independently_verified"):
        blockers.append(f"ARTIFACT_NOT_INDEPENDENTLY_VERIFIED:{artifact_id}")


def _check_actions(blockers: list[str], manifest: Mapping[str, Any]) -> None:
    actions = _list(manifest.get("github_actions_uses"), "github_actions_uses")
    if not actions:
        blockers.append("NO_GITHUB_ACTIONS_RECORDED")
        return
    for action in actions:
        if not isinstance(action, str) or not _FULL_GITHUB_SHA.fullmatch(action):
            blockers.append(f"FLOATING_GITHUB_ACTION:{action}")


def _check_control_group(blockers: list[str], manifest: Mapping[str, Any], key: str, required: Sequence[str]) -> None:
    controls = _mapping(manifest.get(key), key)
    for control in required:
        if controls.get(control) is not True:
            blockers.append(f"CONTROL_NOT_PROVEN:{key}.{control}")


def evaluate_deployment_supply_chain(manifest: Mapping[str, Any]) -> MPR44Report:
    blockers: list[str] = []
    if _str(manifest, "schema_version") != MPR44_SCHEMA:
        blockers.append("SCHEMA_VERSION_MISMATCH")

    if _bool(manifest, "live_enabled"):
        blockers.append("LIVE_MUST_REMAIN_DISABLED")
    if _bool(manifest, "source_checkout_production_allowed"):
        blockers.append("SOURCE_CHECKOUT_PRODUCTION_FORBIDDEN")
    if _bool(manifest, "raw_secret_environment_allowed"):
        blockers.append("RAW_SECRET_ENVIRONMENT_FORBIDDEN")
    if _bool(manifest, "network_install_allowed"):
        blockers.append("NETWORK_INSTALL_FORBIDDEN")
    if _bool(manifest, "untrusted_pr_code_can_access_secrets"):
        blockers.append("UNTRUSTED_PR_SECRET_ACCESS_FORBIDDEN")

    _check_actions(blockers, manifest)
    _check_control_group(blockers, manifest, "deployment_controls", REQUIRED_DEPLOYMENT_CONTROLS)
    _check_control_group(blockers, manifest, "secret_controls", REQUIRED_SECRET_CONTROLS)

    artifacts = _artifact_map(manifest)
    for artifact_id in REQUIRED_RELEASE_ARTIFACTS:
        _require_artifact(blockers, artifacts, artifact_id)

    egress = _mapping(manifest.get("egress_policy"), "egress_policy")
    if egress.get("mode") != "deny-by-default":
        blockers.append("EGRESS_NOT_DENY_BY_DEFAULT")
    allowed = egress.get("allowed_endpoints")
    if not isinstance(allowed, list) or not allowed:
        blockers.append("EGRESS_ALLOWED_ENDPOINTS_MISSING")

    probes = _mapping(manifest.get("probes"), "probes")
    if probes.get("readiness_endpoint") != "/ready":
        blockers.append("READINESS_PROBE_NOT_READY_ENDPOINT")
    if probes.get("liveness_endpoint") != "/health":
        blockers.append("LIVENESS_PROBE_NOT_HEALTH_ENDPOINT")

    paper_ready = not blockers and _bool(manifest, "paper_release_candidate")
    return MPR44Report(
        accepted=not blockers,
        schema_version=MPR44_SCHEMA,
        live_ready=False,
        paper_release_ready=paper_ready,
        blockers=tuple(blockers),
        evidence_digest=None if blockers else _digest(manifest),
    )


def load_manifest(path: str | Path) -> Mapping[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("manifest must be a JSON object")
    return value


def evaluate_manifest_path(path: str | Path) -> MPR44Report:
    return evaluate_deployment_supply_chain(load_manifest(path))
