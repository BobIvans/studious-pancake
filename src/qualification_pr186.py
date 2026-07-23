"""PR-186 executed qualification verdict and release-claim attestation.

A qualification plan is descriptive only.  A release claim is possible only from
an executed, complete, cryptographically attested verdict bound to the exact
source tree, interpreter, installed distributions, commands, and outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
from pathlib import Path
import site
import sys
from typing import Any, Iterable, Mapping

from src.qualification_pr176 import DependencyClosure, QualificationPlan, canonical_hash

PR186_PLAN_SCHEMA = "pr186.qualification-plan.v1"
PR186_RUN_SCHEMA = "pr186.qualification-run.v1"
PR186_VERDICT_SCHEMA = "pr186.qualification-verdict.v1"

_EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".runtime",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "node_modules",
        "venv",
    }
)
_EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo", ".sqlite", ".sqlite3", ".db"})


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class SourceFileIdentity:
    path: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class SourceTreeIdentity:
    root_name: str
    files: tuple[SourceFileIdentity, ...]
    digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_name": self.root_name,
            "file_count": len(self.files),
            "files": [item.to_dict() for item in self.files],
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class InterpreterIdentity:
    executable: str
    version: str
    implementation: str
    prefix: str
    base_prefix: str
    isolated_environment: bool
    global_site_packages_enabled: bool
    sys_path: tuple[str, ...]
    site_packages: tuple[str, ...]
    identity_hash: str

    @classmethod
    def capture(cls) -> "InterpreterIdentity":
        executable = str(Path(sys.executable).resolve())
        payload: dict[str, Any] = {
            "executable": executable,
            "version": sys.version,
            "implementation": sys.implementation.name,
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
            "isolated_environment": sys.prefix != sys.base_prefix,
            "global_site_packages_enabled": bool(
                getattr(sys, "real_prefix", None)
                or (sys.prefix == sys.base_prefix and site.ENABLE_USER_SITE)
            ),
            "sys_path": list(map(str, sys.path)),
            "site_packages": list(map(str, site.getsitepackages())),
        }
        return cls(
            executable=payload["executable"],
            version=payload["version"],
            implementation=payload["implementation"],
            prefix=payload["prefix"],
            base_prefix=payload["base_prefix"],
            isolated_environment=payload["isolated_environment"],
            global_site_packages_enabled=payload["global_site_packages_enabled"],
            sys_path=tuple(payload["sys_path"]),
            site_packages=tuple(payload["site_packages"]),
            identity_hash=_hash_bytes(_canonical_bytes(payload)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "executable": self.executable,
            "version": self.version,
            "implementation": self.implementation,
            "prefix": self.prefix,
            "base_prefix": self.base_prefix,
            "isolated_environment": self.isolated_environment,
            "global_site_packages_enabled": self.global_site_packages_enabled,
            "sys_path": list(self.sys_path),
            "site_packages": list(self.site_packages),
            "identity_hash": self.identity_hash,
        }


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    filename: str
    sha256: str
    size_bytes: int

    @classmethod
    def from_path(cls, path: Path) -> "ArtifactIdentity":
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError(f"qualification artifact is not a file: {resolved}")
        data = resolved.read_bytes()
        return cls(resolved.name, _hash_bytes(data), len(data))

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class ProfileExecutionResult:
    name: str
    command: tuple[str, ...]
    started_at: str
    finished_at: str
    duration_ns: int
    exit_code: int
    stdout_sha256: str
    stderr_sha256: str
    stdout_bytes: int
    stderr_bytes: int
    junit_sha256: str | None = None
    collected: int | None = None
    passed: int | None = None
    failed: int | None = None
    skipped: int | None = None
    xfailed: int | None = None

    @property
    def passed_profile(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": list(self.command),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ns": self.duration_ns,
            "exit_code": self.exit_code,
            "passed": self.passed_profile,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "junit_sha256": self.junit_sha256,
            "counts": {
                "collected": self.collected,
                "passed": self.passed,
                "failed": self.failed,
                "skipped": self.skipped,
                "xfailed": self.xfailed,
            },
        }


@dataclass(frozen=True, slots=True)
class QualificationRun:
    run_id: str
    plan_hash: str
    source: SourceTreeIdentity
    interpreter: InterpreterIdentity
    dependency_closure: DependencyClosure
    wheel: ArtifactIdentity | None
    wheelhouse_manifest_hash: str | None
    profiles: tuple[ProfileExecutionResult, ...]
    selected_profiles: tuple[str, ...]
    started_at: str
    finished_at: str
    environment_id: str
    network_disabled_after_bootstrap: bool
    source_import_leakage_detected: bool
    schema_version: str = PR186_RUN_SCHEMA

    @property
    def completed(self) -> bool:
        names = {item.name for item in self.profiles}
        return set(self.selected_profiles).issubset(names)

    @property
    def profiles_passed(self) -> bool:
        return self.completed and all(item.passed_profile for item in self.profiles)

    @property
    def release_prerequisites_satisfied(self) -> bool:
        return bool(
            self.completed
            and self.profiles_passed
            and self.dependency_closure.complete
            and self.interpreter.isolated_environment
            and not self.interpreter.global_site_packages_enabled
            and self.wheel is not None
            and self.wheelhouse_manifest_hash
            and self.network_disabled_after_bootstrap
            and not self.source_import_leakage_detected
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "plan_hash": self.plan_hash,
            "source": self.source.to_dict(),
            "interpreter": self.interpreter.to_dict(),
            "dependency_closure": self.dependency_closure.to_dict(),
            "wheel": None if self.wheel is None else self.wheel.to_dict(),
            "wheelhouse_manifest_hash": self.wheelhouse_manifest_hash,
            "profiles": [item.to_dict() for item in self.profiles],
            "selected_profiles": list(self.selected_profiles),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "environment_id": self.environment_id,
            "network_disabled_after_bootstrap": self.network_disabled_after_bootstrap,
            "source_import_leakage_detected": self.source_import_leakage_detected,
            "completed": self.completed,
            "profiles_passed": self.profiles_passed,
            "release_prerequisites_satisfied": self.release_prerequisites_satisfied,
        }
        payload["run_hash"] = canonical_hash(payload)
        return payload

    @property
    def run_hash(self) -> str:
        return str(self.to_dict()["run_hash"])


@dataclass(frozen=True, slots=True)
class QualificationVerdict:
    run_hash: str
    source_digest: str
    wheel_sha256: str
    qualified: bool
    reason_codes: tuple[str, ...]
    repeated_clean_run_match: bool
    signer_key_id: str
    signature_algorithm: str
    signature: str
    issued_at: str
    schema_version: str = PR186_VERDICT_SCHEMA

    @property
    def release_claim_allowed(self) -> bool:
        """Legacy HMAC verdicts are CI evidence, not release authority."""

        return False

    def unsigned_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_hash": self.run_hash,
            "source_digest": self.source_digest,
            "wheel_sha256": self.wheel_sha256,
            "qualified": self.qualified,
            "reason_codes": list(self.reason_codes),
            "repeated_clean_run_match": self.repeated_clean_run_match,
            "signer_key_id": self.signer_key_id,
            "signature_algorithm": self.signature_algorithm,
            "issued_at": self.issued_at,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.unsigned_payload()
        payload["signature"] = self.signature
        payload["release_claim_allowed"] = self.release_claim_allowed
        payload["verdict_hash"] = canonical_hash(payload)
        return payload


def source_tree_identity(root: Path) -> SourceTreeIdentity:
    root = root.resolve(strict=True)
    identities: list[SourceFileIdentity] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in _EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.suffix.lower() in _EXCLUDED_SUFFIXES:
            continue
        data = path.read_bytes()
        identities.append(
            SourceFileIdentity(
                path=relative.as_posix(),
                size_bytes=len(data),
                sha256=_hash_bytes(data),
            )
        )
    manifest = {"files": [item.to_dict() for item in identities]}
    return SourceTreeIdentity(
        root.name, tuple(identities), _hash_bytes(_canonical_bytes(manifest))
    )


def qualification_plan_document(
    plan: QualificationPlan, source: SourceTreeIdentity
) -> dict[str, Any]:
    payload = plan.to_manifest(source_digest=source.digest, execution_mode="planned")
    payload["schema_version"] = PR186_PLAN_SCHEMA
    payload["qualification_state"] = "planned_not_executed"
    payload["release_claim_allowed"] = False
    payload["source_tree"] = source.to_dict()
    payload["manifest_hash"] = canonical_hash(payload)
    return payload


def create_signed_verdict(
    run: QualificationRun,
    *,
    repeated_clean_run_match: bool,
    signer_key_id: str,
    signing_key: bytes,
    issued_at: str | None = None,
) -> QualificationVerdict:
    if not signer_key_id.strip():
        raise ValueError("signer_key_id is required")
    if len(signing_key) < 32:
        raise ValueError("qualification signing key must contain at least 32 bytes")
    reasons: list[str] = []
    if not run.completed:
        reasons.append("qualification_run_incomplete")
    if not run.profiles_passed:
        reasons.append("mandatory_profile_failed")
    if not run.dependency_closure.complete:
        reasons.append("installed_dependency_closure_incomplete")
    if not run.interpreter.isolated_environment:
        reasons.append("interpreter_not_isolated")
    if run.interpreter.global_site_packages_enabled:
        reasons.append("global_site_packages_enabled")
    if run.wheel is None:
        reasons.append("production_wheel_missing")
    if not run.wheelhouse_manifest_hash:
        reasons.append("wheelhouse_not_hash_verified")
    if not run.network_disabled_after_bootstrap:
        reasons.append("network_not_disabled_after_bootstrap")
    if run.source_import_leakage_detected:
        reasons.append("source_import_leakage_detected")
    if not repeated_clean_run_match:
        reasons.append("repeated_clean_run_mismatch")
    qualified = not reasons
    issued = issued_at or utc_now()
    unsigned = {
        "schema_version": PR186_VERDICT_SCHEMA,
        "run_hash": run.run_hash,
        "source_digest": run.source.digest,
        "wheel_sha256": "" if run.wheel is None else run.wheel.sha256,
        "qualified": qualified,
        "reason_codes": reasons,
        "repeated_clean_run_match": repeated_clean_run_match,
        "signer_key_id": signer_key_id,
        "signature_algorithm": "hmac-sha256",
        "issued_at": issued,
    }
    signature = hmac.new(
        signing_key, _canonical_bytes(unsigned), hashlib.sha256
    ).hexdigest()
    return QualificationVerdict(
        run_hash=run.run_hash,
        source_digest=run.source.digest,
        wheel_sha256=str(unsigned["wheel_sha256"]),
        qualified=qualified,
        reason_codes=tuple(reasons),
        repeated_clean_run_match=repeated_clean_run_match,
        signer_key_id=signer_key_id,
        signature_algorithm="hmac-sha256",
        signature=signature,
        issued_at=issued,
    )


def verify_signed_verdict(verdict: QualificationVerdict, signing_key: bytes) -> bool:
    expected = hmac.new(
        signing_key,
        _canonical_bytes(verdict.unsigned_payload()),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, verdict.signature)


def wheelhouse_manifest_hash(artifacts: Iterable[ArtifactIdentity]) -> str:
    payload = {
        "artifacts": [
            item.to_dict()
            for item in sorted(artifacts, key=lambda value: value.filename)
        ]
    }
    return _hash_bytes(_canonical_bytes(payload))


__all__ = [
    "ArtifactIdentity",
    "InterpreterIdentity",
    "PR186_PLAN_SCHEMA",
    "PR186_RUN_SCHEMA",
    "PR186_VERDICT_SCHEMA",
    "ProfileExecutionResult",
    "QualificationRun",
    "QualificationVerdict",
    "SourceFileIdentity",
    "SourceTreeIdentity",
    "create_signed_verdict",
    "qualification_plan_document",
    "source_tree_identity",
    "utc_now",
    "verify_signed_verdict",
    "wheelhouse_manifest_hash",
]
