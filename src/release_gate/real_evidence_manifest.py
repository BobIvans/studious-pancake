"""PR-091 committed real evidence manifest loader.

PR-091 must not be satisfied by pytest ``tmp_path`` fixtures or by ad-hoc
files that merely satisfy the PR-078 dataclasses. This module loads a
repository-owned JSON manifest from ``release_artifacts/pr091/``, verifies that
all referenced artifact files are also inside that release-artifact directory,
and, by default, asks Git whether every referenced file is tracked before the
package is handed to :class:`ActualEvidenceGate`.

The loader remains evidence-only: it never imports signer, RPC, Jito or live
submission code and it does not generate evidence by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence

from .actual_evidence import (
    ActualEvidenceArtifact,
    ActualEvidenceGate,
    ActualEvidenceGateResult,
    ActualEvidenceKind,
    ActualEvidencePackage,
)
from .operational_drills import (
    FailureInjectionScenario,
    OperationalDrillSuite,
    OperationalFailureArea,
    SecurityOperationalEvidence,
)
from src.security.supply_chain import SupplyChainDecision

SCHEMA_VERSION = "pr091.real-security-sbom-chaos-evidence-manifest.v1"
PR091_RELEASE_ARTIFACT_ROOT = "release_artifacts/pr091"


class RealEvidenceManifestError(ValueError):
    """Raised when a PR-091 manifest cannot be trusted as release evidence."""


@dataclass(frozen=True, slots=True)
class RealEvidenceManifestLoadResult:
    """A parsed PR-091 package plus the Git-tracked files it depends on."""

    schema_version: str
    manifest_path: str
    package: ActualEvidencePackage
    tracked_paths: tuple[str, ...]


def load_pr091_actual_evidence_manifest(
    *,
    repo_root: str | Path,
    manifest_path: str | Path,
    require_git_tracked: bool = True,
) -> RealEvidenceManifestLoadResult:
    """Load a committed PR-091 manifest and convert it to gate dataclasses.

    ``manifest_path`` and every ``artifact.path`` must be under
    ``release_artifacts/pr091/``. When ``require_git_tracked`` is true, the
    manifest and all artifact files must already be present in ``git ls-files``.
    That is the key PR-091 distinction from synthetic tmp-path unit fixtures.
    """

    root = Path(repo_root).resolve()
    manifest_rel = _repo_relative_path(root, manifest_path, "manifest_path")
    _require_pr091_artifact_path(manifest_rel, "manifest_path")

    manifest_file = root / manifest_rel
    if not manifest_file.is_file():
        raise RealEvidenceManifestError(f"MANIFEST_FILE_MISSING:{manifest_rel}")

    payload = _read_json_object(manifest_file)
    schema_version = _string(payload, "schema_version")
    if schema_version != SCHEMA_VERSION:
        raise RealEvidenceManifestError(f"MANIFEST_SCHEMA_UNSUPPORTED:{schema_version}")

    artifacts = tuple(
        _parse_actual_artifact(root, _mapping(item, "artifacts[]"))
        for item in _sequence(payload, "artifacts")
    )
    drill_suite_payload = _mapping(
        payload.get("operational_drill_suite"),
        "operational_drill_suite",
    )
    scenario_evidence_paths = _validate_scenario_evidence_paths(
        root,
        drill_suite_payload,
    )
    package = ActualEvidencePackage(
        package_id=_string(payload, "package_id"),
        generated_at=_datetime(payload, "generated_at"),
        artifacts=artifacts,
        drill_suite=_parse_drill_suite(drill_suite_payload),
        notes=str(payload.get("notes", "")),
    )

    tracked_paths = (
        (manifest_rel,)
        + tuple(artifact.path for artifact in artifacts)
        + scenario_evidence_paths
    )
    if require_git_tracked:
        _require_git_tracked(root, tracked_paths)

    return RealEvidenceManifestLoadResult(
        schema_version=schema_version,
        manifest_path=manifest_rel,
        package=package,
        tracked_paths=tracked_paths,
    )


def load_pr091_actual_evidence_package(
    *,
    repo_root: str | Path,
    manifest_path: str | Path,
    require_git_tracked: bool = True,
) -> ActualEvidencePackage:
    """Return only the :class:`ActualEvidencePackage` from a PR-091 manifest."""

    return load_pr091_actual_evidence_manifest(
        repo_root=repo_root,
        manifest_path=manifest_path,
        require_git_tracked=require_git_tracked,
    ).package


def evaluate_pr091_actual_evidence_manifest(
    *,
    repo_root: str | Path,
    manifest_path: str | Path,
    require_git_tracked: bool = True,
    evaluated_at: datetime | None = None,
) -> ActualEvidenceGateResult:
    """Evaluate a committed PR-091 evidence manifest with ``ActualEvidenceGate``."""

    loaded = load_pr091_actual_evidence_manifest(
        repo_root=repo_root,
        manifest_path=manifest_path,
        require_git_tracked=require_git_tracked,
    )
    return ActualEvidenceGate(
        repo_root=repo_root,
        evaluated_at=evaluated_at,
    ).evaluate(loaded.package)


def _validate_scenario_evidence_paths(
    root: Path,
    drill_suite_payload: Mapping[str, Any],
) -> tuple[str, ...]:
    paths: list[str] = []
    for index, item in enumerate(_sequence(drill_suite_payload, "scenarios")):
        scenario = _mapping(item, f"operational_drill_suite.scenarios[{index}]")
        relative_path = _repo_relative_path(
            root,
            _string(scenario, "evidence_path"),
            f"scenario.evidence_path[{index}]",
        )
        _require_pr091_artifact_path(
            relative_path,
            f"scenario.evidence_path[{index}]",
        )
        evidence_file = root / relative_path
        if not evidence_file.is_file():
            raise RealEvidenceManifestError(
                f"SCENARIO_EVIDENCE_FILE_MISSING:{relative_path}"
            )
        observed_sha256 = _sha256_file(evidence_file)
        expected_sha256 = _string(scenario, "evidence_sha256")
        if observed_sha256 != expected_sha256:
            raise RealEvidenceManifestError(
                f"SCENARIO_EVIDENCE_HASH_MISMATCH:{relative_path}"
            )
        paths.append(relative_path)
    return tuple(paths)


def _parse_actual_artifact(
    root: Path,
    payload: Mapping[str, Any],
) -> ActualEvidenceArtifact:
    relative_path = _repo_relative_path(
        root,
        _string(payload, "path"),
        "artifact.path",
    )
    _require_pr091_artifact_path(relative_path, "artifact.path")
    return ActualEvidenceArtifact(
        kind=ActualEvidenceKind(_string(payload, "kind")),
        path=relative_path,
        sha256=_string(payload, "sha256"),
        generated_at=_datetime(payload, "generated_at"),
        source=_string(payload, "source"),
        policy_enforced=_bool(payload, "policy_enforced", default=True),
        reviewed=_bool(payload, "reviewed", default=False),
        reviewer=_optional_string(payload, "reviewer"),
        critical_findings=_int(payload, "critical_findings", default=0),
        placeholder=_bool(payload, "placeholder", default=False),
        notes=str(payload.get("notes", "")),
    )


def _parse_drill_suite(payload: Mapping[str, Any]) -> OperationalDrillSuite:
    return OperationalDrillSuite(
        suite_id=_string(payload, "suite_id"),
        run_started_at=_datetime(payload, "run_started_at"),
        run_finished_at=_datetime(payload, "run_finished_at"),
        operator=_string(payload, "operator"),
        environment=_string(payload, "environment"),
        security=_parse_security(
            _mapping(payload.get("security"), "operational_drill_suite.security")
        ),
        scenarios=tuple(
            _parse_scenario(_mapping(item, "operational_drill_suite.scenarios[]"))
            for item in _sequence(payload, "scenarios")
        ),
        manual_rollback_rehearsed=_bool(payload, "manual_rollback_rehearsed"),
        kill_switch_rehearsed=_bool(payload, "kill_switch_rehearsed"),
        no_live_submission=_bool(payload, "no_live_submission", default=True),
        notes=str(payload.get("notes", "")),
    )


def _parse_security(payload: Mapping[str, Any]) -> SecurityOperationalEvidence:
    decision = _mapping(payload.get("dependency_decision"), "dependency_decision")
    release_manifest_sha256 = payload.get("release_manifest_sha256")
    if release_manifest_sha256 is not None:
        if not isinstance(release_manifest_sha256, str):
            raise RealEvidenceManifestError(
                "FIELD_NOT_STRING:security.release_manifest_sha256"
            )
    return SecurityOperationalEvidence(
        generated_at=_datetime(payload, "generated_at"),
        secret_scan_passed=_bool(payload, "secret_scan_passed"),
        plaintext_key_findings=tuple(
            _strings(
                _sequence(payload, "plaintext_key_findings"),
                "plaintext_key_findings",
            )
        ),
        dependency_decision=SupplyChainDecision(
            allowed=_bool(decision, "allowed"),
            reason=_string(decision, "reason"),
            blockers=tuple(_strings(_sequence(decision, "blockers"), "blockers")),
        ),
        sbom_sha256=_string(payload, "sbom_sha256"),
        image_digest=_string(payload, "image_digest"),
        signer_policy_enforced=_bool(payload, "signer_policy_enforced"),
        isolated_signer_reference=_string(payload, "isolated_signer_reference"),
        release_manifest_sha256=release_manifest_sha256,
    )


def _parse_scenario(payload: Mapping[str, Any]) -> FailureInjectionScenario:
    return FailureInjectionScenario(
        area=OperationalFailureArea(_string(payload, "area")),
        scenario_id=_string(payload, "scenario_id"),
        injected_failure=_string(payload, "injected_failure"),
        expected_safe_state=_string(payload, "expected_safe_state"),
        passed=_bool(payload, "passed"),
        safe_state_proven=_bool(payload, "safe_state_proven"),
        evidence_sha256=_string(payload, "evidence_sha256"),
        max_retry_attempts=_int(payload, "max_retry_attempts"),
        observed_retry_attempts=_int(payload, "observed_retry_attempts"),
        max_queue_depth=_int(payload, "max_queue_depth"),
        observed_queue_depth=_int(payload, "observed_queue_depth"),
        max_rto_seconds=_optional_int(payload, "max_rto_seconds"),
        observed_rto_seconds=_optional_int(payload, "observed_rto_seconds"),
        automatic_resubmission_attempted=_bool(
            payload,
            "automatic_resubmission_attempted",
            default=False,
        ),
        residual_task_count=_int(payload, "residual_task_count", default=0),
        notes=str(payload.get("notes", "")),
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json_object(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RealEvidenceManifestError(f"MANIFEST_JSON_INVALID:{exc}") from exc
    return _mapping(payload, "manifest")


def _repo_relative_path(root: Path, raw_path: str | Path, field: str) -> str:
    path = Path(raw_path)
    if path.is_absolute():
        resolved = path.resolve()
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise RealEvidenceManifestError(f"PATH_OUTSIDE_REPO:{field}") from exc

    normalized = str(raw_path).replace("\\", "/")
    if not normalized or normalized.startswith(("/", "~")):
        raise RealEvidenceManifestError(f"PATH_NOT_REPO_RELATIVE:{field}")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise RealEvidenceManifestError(f"PATH_UNSAFE:{field}")
    return normalized


def _require_pr091_artifact_path(relative_path: str, field: str) -> None:
    if not relative_path.startswith(f"{PR091_RELEASE_ARTIFACT_ROOT}/"):
        raise RealEvidenceManifestError(
            f"PATH_NOT_UNDER_PR091_RELEASE_ARTIFACTS:{field}:{relative_path}"
        )


def _require_git_tracked(root: Path, paths: tuple[str, ...]) -> None:
    command = [
        "git",
        "-C",
        str(root),
        "ls-files",
        "--error-unmatch",
        "--",
        *paths,
    ]
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell.
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RealEvidenceManifestError(
            "GIT_TRACKING_REQUIRED_FOR_PR091_EVIDENCE:" + detail
        )


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RealEvidenceManifestError(f"FIELD_NOT_OBJECT:{field}")
    return value


def _sequence(payload: Mapping[str, Any], field: str) -> Sequence[object]:
    value = payload.get(field)
    if not isinstance(value, (list, tuple)):
        raise RealEvidenceManifestError(f"FIELD_NOT_LIST:{field}")
    return value


def _strings(values: Sequence[object], field: str) -> tuple[str, ...]:
    result: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str):
            raise RealEvidenceManifestError(f"FIELD_NOT_STRING:{field}[{index}]")
        result.append(value)
    return tuple(result)


def _string(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise RealEvidenceManifestError(f"FIELD_NOT_STRING:{field}")
    return value


def _optional_string(payload: Mapping[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RealEvidenceManifestError(f"FIELD_NOT_STRING:{field}")
    return value


def _bool(
    payload: Mapping[str, Any],
    field: str,
    *,
    default: bool | None = None,
) -> bool:
    value = payload.get(field, default)
    if not isinstance(value, bool):
        raise RealEvidenceManifestError(f"FIELD_NOT_BOOL:{field}")
    return value


def _int(
    payload: Mapping[str, Any],
    field: str,
    *,
    default: int | None = None,
) -> int:
    value = payload.get(field, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise RealEvidenceManifestError(f"FIELD_NOT_INT:{field}")
    return value


def _optional_int(payload: Mapping[str, Any], field: str) -> int | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise RealEvidenceManifestError(f"FIELD_NOT_INT:{field}")
    return value


def _datetime(payload: Mapping[str, Any], field: str) -> datetime:
    value = _string(payload, field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RealEvidenceManifestError(f"FIELD_NOT_ISO_DATETIME:{field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RealEvidenceManifestError(f"FIELD_DATETIME_NOT_TIMEZONE_AWARE:{field}")
    return parsed


__all__ = [
    "PR091_RELEASE_ARTIFACT_ROOT",
    "RealEvidenceManifestError",
    "RealEvidenceManifestLoadResult",
    "SCHEMA_VERSION",
    "evaluate_pr091_actual_evidence_manifest",
    "load_pr091_actual_evidence_manifest",
    "load_pr091_actual_evidence_package",
]
