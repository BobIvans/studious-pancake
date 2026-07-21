"""PR-104 mandatory real security/SBOM/provenance/chaos package gate.

PR-091 introduced the committed-manifest loader. PR-104 is stricter: the
repository must contain the actual reviewed release evidence package, not only
``release_artifacts/pr091/README.md`` or unit-test generated fixtures.

This module is intentionally offline and evidence-only. It never imports signer,
RPC, Jito, transaction submission, or live trading code.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Sequence

from .actual_evidence import (
    REQUIRED_ACTUAL_EVIDENCE_KINDS,
    ActualEvidenceGate,
    ActualEvidenceGateResult,
)
from .real_evidence_manifest import (
    PR091_RELEASE_ARTIFACT_ROOT,
    RealEvidenceManifestError,
    RealEvidenceManifestLoadResult,
    load_pr091_actual_evidence_manifest,
)

PR104_SCHEMA_VERSION = "pr104.actual-security-sbom-provenance-chaos-package.v1"
PR104_DEFAULT_MANIFEST_PATH = f"{PR091_RELEASE_ARTIFACT_ROOT}/manifest.json"
PR104_ARTIFACT_ROOT = f"{PR091_RELEASE_ARTIFACT_ROOT}/artifacts"
PR104_CHAOS_ROOT = f"{PR091_RELEASE_ARTIFACT_ROOT}/chaos"


@dataclass(frozen=True, slots=True)
class PR104ActualEvidencePackageResult:
    """Result for the mandatory PR-104 repository evidence package check."""

    schema_version: str
    manifest_path: str
    accepted: bool
    state: str
    artifact_count: int
    scenario_evidence_count: int
    tracked_paths: tuple[str, ...]
    pr091_result: ActualEvidenceGateResult | None
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["pr091_result"] = (
            self.pr091_result.to_dict() if self.pr091_result is not None else None
        )
        return payload


def evaluate_pr104_actual_evidence_package(
    *,
    repo_root: str | Path,
    manifest_path: str | Path = PR104_DEFAULT_MANIFEST_PATH,
    require_git_tracked: bool = True,
    evaluated_at: datetime | None = None,
) -> PR104ActualEvidencePackageResult:
    """Require the actual reviewed PR-091 release evidence package for PR-104."""

    root = Path(repo_root).resolve()
    manifest_rel = _repo_relative_manifest(manifest_path)
    blockers: list[str] = []
    warnings: list[str] = []

    if manifest_rel != PR104_DEFAULT_MANIFEST_PATH:
        blockers.append(f"PR104_MANIFEST_PATH_NOT_CANONICAL:{manifest_rel}")

    manifest_file = root / manifest_rel
    if not manifest_file.is_file():
        blockers.append(f"PR104_EVIDENCE_MANIFEST_MISSING:{manifest_rel}")
        return _result(
            manifest_path=manifest_rel,
            blockers=blockers,
            warnings=warnings,
        )

    try:
        loaded = load_pr091_actual_evidence_manifest(
            repo_root=root,
            manifest_path=manifest_rel,
            require_git_tracked=require_git_tracked,
        )
    except RealEvidenceManifestError as exc:
        blockers.append(f"PR091_MANIFEST_REJECTED:{exc}")
        return _result(
            manifest_path=manifest_rel,
            blockers=blockers,
            warnings=warnings,
        )

    pr091_result = ActualEvidenceGate(
        repo_root=root,
        evaluated_at=evaluated_at,
    ).evaluate(loaded.package)

    if not pr091_result.accepted:
        blockers.append("PR091_GATE_NOT_ACCEPTED")
        blockers.extend(f"PR091_GATE_BLOCKED:{item}" for item in pr091_result.blockers)

    artifact_paths = tuple(artifact.path for artifact in loaded.package.artifacts)
    scenario_evidence_paths = tuple(
        path
        for path in loaded.tracked_paths
        if path.startswith(f"{PR104_CHAOS_ROOT}/")
    )

    _check_complete_artifact_inventory(loaded, artifact_paths, blockers)
    _check_reviewed_artifacts(loaded, blockers)
    _check_immutable_manifest_reference(loaded, blockers)
    _check_directory_is_not_readme_only(loaded, artifact_paths, blockers)
    if not scenario_evidence_paths:
        blockers.append("PR104_CHAOS_EVIDENCE_FILES_MISSING")

    unique_blockers = tuple(dict.fromkeys(blockers))
    return _result(
        manifest_path=manifest_rel,
        accepted=not unique_blockers,
        artifact_count=len(artifact_paths),
        scenario_evidence_count=len(scenario_evidence_paths),
        tracked_paths=loaded.tracked_paths,
        pr091_result=pr091_result,
        blockers=unique_blockers,
        warnings=warnings,
    )


def _check_complete_artifact_inventory(
    loaded: RealEvidenceManifestLoadResult,
    artifact_paths: tuple[str, ...],
    blockers: list[str],
) -> None:
    observed = {artifact.kind for artifact in loaded.package.artifacts}
    missing = REQUIRED_ACTUAL_EVIDENCE_KINDS - observed
    for kind in sorted(missing, key=lambda item: item.value):
        blockers.append(f"PR104_REQUIRED_ARTIFACT_MISSING:{kind.value}")

    for path in artifact_paths:
        if not path.startswith(f"{PR104_ARTIFACT_ROOT}/"):
            blockers.append(f"PR104_ARTIFACT_OUTSIDE_ARTIFACT_ROOT:{path}")
        if path.lower().endswith((".md", "readme")):
            blockers.append(f"PR104_README_CANNOT_BE_ARTIFACT:{path}")


def _check_reviewed_artifacts(
    loaded: RealEvidenceManifestLoadResult,
    blockers: list[str],
) -> None:
    for artifact in loaded.package.artifacts:
        if not artifact.reviewed:
            blockers.append(f"PR104_ARTIFACT_NOT_REVIEWED:{artifact.kind.value}")
        if not (artifact.reviewer or "").strip():
            blockers.append(f"PR104_ARTIFACT_REVIEWER_MISSING:{artifact.kind.value}")


def _check_immutable_manifest_reference(
    loaded: RealEvidenceManifestLoadResult,
    blockers: list[str],
) -> None:
    manifest_sha = loaded.package.drill_suite.security.release_manifest_sha256
    if not manifest_sha:
        blockers.append("PR104_RELEASE_MANIFEST_HASH_MISSING")
    elif len(manifest_sha) != 64 or set(manifest_sha) == {"0"}:
        blockers.append("PR104_RELEASE_MANIFEST_HASH_INVALID")


def _check_directory_is_not_readme_only(
    loaded: RealEvidenceManifestLoadResult,
    artifact_paths: tuple[str, ...],
    blockers: list[str],
) -> None:
    tracked_evidence = tuple(
        path
        for path in loaded.tracked_paths
        if path.startswith(f"{PR091_RELEASE_ARTIFACT_ROOT}/")
    )
    non_readme_paths = tuple(
        path
        for path in tracked_evidence
        if not path.lower().endswith(("readme.md", "/readme.md"))
    )
    if not artifact_paths or not non_readme_paths:
        blockers.append("PR104_README_ONLY_EVIDENCE_DIRECTORY")


def _repo_relative_manifest(manifest_path: str | Path) -> str:
    path = Path(manifest_path)
    if path.is_absolute():
        raise ValueError("manifest_path must be repository-relative")
    normalized = str(manifest_path).replace("\\", "/")
    if not normalized or normalized.startswith(("/", "~")):
        raise ValueError("manifest_path must be repository-relative")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(
            "manifest_path must not contain empty, dot, or parent parts"
        )
    return normalized


def _result(
    *,
    manifest_path: str,
    accepted: bool = False,
    artifact_count: int = 0,
    scenario_evidence_count: int = 0,
    tracked_paths: tuple[str, ...] = (),
    pr091_result: ActualEvidenceGateResult | None = None,
    blockers: Sequence[str] = (),
    warnings: Sequence[str] = (),
) -> PR104ActualEvidencePackageResult:
    unique_blockers = tuple(dict.fromkeys(blockers))
    return PR104ActualEvidencePackageResult(
        schema_version=PR104_SCHEMA_VERSION,
        manifest_path=manifest_path,
        accepted=accepted and not unique_blockers,
        state="accepted" if accepted and not unique_blockers else "blocked",
        artifact_count=artifact_count,
        scenario_evidence_count=scenario_evidence_count,
        tracked_paths=tracked_paths,
        pr091_result=pr091_result,
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the mandatory PR-104 actual release evidence package."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--manifest-path", default=PR104_DEFAULT_MANIFEST_PATH)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        result = evaluate_pr104_actual_evidence_package(
            repo_root=args.repo_root,
            manifest_path=args.manifest_path,
        )
    except ValueError as exc:
        result = _result(
            manifest_path=str(args.manifest_path),
            blockers=(f"PR104_ARGUMENT_INVALID:{exc}",),
        )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"PR-104 evidence gate: {result.state}")
        for blocker in result.blockers:
            print(f"BLOCKER: {blocker}")
        for warning in result.warnings:
            print(f"WARNING: {warning}")

    return 0 if result.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PR104ActualEvidencePackageResult",
    "PR104_DEFAULT_MANIFEST_PATH",
    "PR104_SCHEMA_VERSION",
    "evaluate_pr104_actual_evidence_package",
    "main",
]
