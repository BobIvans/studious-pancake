"""PR-207 installed-artifact truth gate.

This module starts the Pass 6 PR-207 corrective package without enabling live
trading, signing, provider access or transaction submission.  It intentionally
inspects a built wheel artifact directly instead of trusting caller-supplied
module inventories, entrypoints or placeholder hashes.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import zipfile

SCHEMA_VERSION = "pr207.artifact-truth-gate.v1"

_REQUIRED_DIST_INFO_SUFFIXES: tuple[str, ...] = (
    ".dist-info/RECORD",
    ".dist-info/entry_points.txt",
    ".dist-info/WHEEL",
)

_FORBIDDEN_SENDER_FREE_PREFIXES: tuple[str, ...] = (
    "isolated_signer_service/",
    "src/execution/senders/",
    "src/ingest/",
    "src/live_boundary/",
    "src/live_canary/",
    "src/submission/",
)

_FORBIDDEN_SENDER_FREE_NAME_FRAGMENTS: tuple[str, ...] = (
    "jito",
    "private_key",
    "signer",
    "submit",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ENTRYPOINT_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*([A-Za-z0-9_.:]+)\s*$")


class PR207ArtifactTruthError(ValueError):
    """Stable fail-closed PR-207 validation error."""


@dataclass(frozen=True, slots=True)
class PR207WheelInspectionReport:
    """Deterministic report produced from wheel bytes, not caller claims."""

    schema_version: str
    ready_sender_free: bool
    wheel_sha256: str
    wheel_size_bytes: int
    python_module_count: int
    entrypoints: tuple[tuple[str, str], ...]
    blocked_members: tuple[str, ...]
    missing_required_members: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ready_sender_free": self.ready_sender_free,
            "wheel_sha256": self.wheel_sha256,
            "wheel_size_bytes": self.wheel_size_bytes,
            "python_module_count": self.python_module_count,
            "entrypoints": [
                {"name": name, "target": target} for name, target in self.entrypoints
            ],
            "blocked_members": list(self.blocked_members),
            "missing_required_members": list(self.missing_required_members),
            "reason_codes": list(self.reason_codes),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True, slots=True)
class PR207ReleaseSetReport:
    """Joint digest report for main runtime and isolated signer artifacts."""

    schema_version: str
    ready: bool
    main_wheel_sha256: str
    signer_wheel_sha256: str
    ipc_schema_sha256: str
    policy_bundle_sha256: str
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ready": self.ready,
            "main_wheel_sha256": self.main_wheel_sha256,
            "signer_wheel_sha256": self.signer_wheel_sha256,
            "ipc_schema_sha256": self.ipc_schema_sha256,
            "policy_bundle_sha256": self.policy_bundle_sha256,
            "reason_codes": list(self.reason_codes),
        }


def inspect_sender_free_wheel_artifact(
    wheel_path: str | Path,
    *,
    expected_entrypoints: dict[str, str] | None = None,
    expected_wheel_sha256: str | None = None,
) -> PR207WheelInspectionReport:
    """Inspect a built sender-free wheel and return a fail-closed report.

    The caller supplies only an artifact path and optional expected digest.  The
    inventory, entrypoints and blocked surfaces are derived from the wheel bytes.
    """

    path = Path(wheel_path)
    if not path.is_file():
        raise PR207ArtifactTruthError("PR207_WHEEL_ARTIFACT_NOT_FOUND")
    if path.suffix != ".whl":
        raise PR207ArtifactTruthError("PR207_ARTIFACT_MUST_BE_WHEEL")

    wheel_bytes = path.read_bytes()
    wheel_sha256 = _sha256_bytes(wheel_bytes)
    _require_real_sha256(wheel_sha256, "wheel_sha256")
    if expected_wheel_sha256 is not None:
        _require_real_sha256(expected_wheel_sha256, "expected_wheel_sha256")
        if expected_wheel_sha256 != wheel_sha256:
            raise PR207ArtifactTruthError("PR207_WHEEL_DIGEST_MISMATCH")

    with zipfile.ZipFile(path) as archive:
        names = tuple(sorted(item.filename for item in archive.infolist()))
        missing = tuple(
            suffix
            for suffix in _REQUIRED_DIST_INFO_SUFFIXES
            if not any(name.endswith(suffix) for name in names)
        )
        entrypoints = _read_entrypoints(archive)
        modules = tuple(name for name in names if name.endswith(".py"))
        blocked = tuple(name for name in modules if _is_forbidden_sender_free_member(name))
        record_errors = _validate_record_members(archive, names)

    reason_codes: list[str] = []
    if missing:
        reason_codes.append("PR207_WHEEL_REQUIRED_METADATA_MISSING")
    if blocked:
        reason_codes.append("PR207_SENDER_FREE_WHEEL_CONTAINS_FORBIDDEN_SURFACE")
    if record_errors:
        reason_codes.extend(record_errors)
    if expected_entrypoints is not None:
        reason_codes.extend(_entrypoint_mismatches(entrypoints, expected_entrypoints))

    return PR207WheelInspectionReport(
        schema_version=SCHEMA_VERSION,
        ready_sender_free=not reason_codes,
        wheel_sha256=wheel_sha256,
        wheel_size_bytes=len(wheel_bytes),
        python_module_count=len(modules),
        entrypoints=tuple(sorted(entrypoints.items())),
        blocked_members=blocked,
        missing_required_members=missing,
        reason_codes=tuple(reason_codes),
    )


def validate_release_set_digests(
    *,
    main_wheel_sha256: str,
    signer_wheel_sha256: str,
    ipc_schema_sha256: str,
    policy_bundle_sha256: str,
) -> PR207ReleaseSetReport:
    """Validate immutable release-set digest shape for main+signer packages."""

    reason_codes: list[str] = []
    values = {
        "main_wheel_sha256": main_wheel_sha256,
        "signer_wheel_sha256": signer_wheel_sha256,
        "ipc_schema_sha256": ipc_schema_sha256,
        "policy_bundle_sha256": policy_bundle_sha256,
    }
    for field_name, value in values.items():
        try:
            _require_real_sha256(value, field_name)
        except PR207ArtifactTruthError as exc:
            reason_codes.append(str(exc))

    if main_wheel_sha256 == signer_wheel_sha256:
        reason_codes.append("PR207_MAIN_AND_SIGNER_WHEELS_MUST_BE_DISTINCT")

    return PR207ReleaseSetReport(
        schema_version=SCHEMA_VERSION,
        ready=not reason_codes,
        main_wheel_sha256=main_wheel_sha256,
        signer_wheel_sha256=signer_wheel_sha256,
        ipc_schema_sha256=ipc_schema_sha256,
        policy_bundle_sha256=policy_bundle_sha256,
        reason_codes=tuple(reason_codes),
    )


def _read_entrypoints(archive: zipfile.ZipFile) -> dict[str, str]:
    entrypoint_names = sorted(
        name for name in archive.namelist() if name.endswith(".dist-info/entry_points.txt")
    )
    if len(entrypoint_names) != 1:
        return {}
    entrypoints: dict[str, str] = {}
    in_console_scripts = False
    for raw_line in archive.read(entrypoint_names[0]).decode("utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_console_scripts = line == "[console_scripts]"
            continue
        if not in_console_scripts:
            continue
        match = _ENTRYPOINT_RE.match(line)
        if match:
            entrypoints[match.group(1)] = match.group(2)
    return entrypoints


def _entrypoint_mismatches(
    actual: dict[str, str], expected: dict[str, str]
) -> list[str]:
    reason_codes: list[str] = []
    for name, target in expected.items():
        if actual.get(name) != target:
            reason_codes.append("PR207_ENTRYPOINT_TARGET_MISMATCH")
    return reason_codes


def _validate_record_members(
    archive: zipfile.ZipFile,
    names: tuple[str, ...],
) -> tuple[str, ...]:
    record_names = sorted(name for name in names if name.endswith(".dist-info/RECORD"))
    if len(record_names) != 1:
        return ("PR207_WHEEL_RECORD_NOT_UNIQUE",)
    record_text = archive.read(record_names[0]).decode("utf-8")
    recorded = {
        row.split(",", 1)[0]
        for row in record_text.splitlines()
        if row and "," in row
    }
    missing_from_record = [name for name in names if name not in recorded]
    if missing_from_record:
        return ("PR207_WHEEL_RECORD_INCOMPLETE",)
    return ()


def _is_forbidden_sender_free_member(name: str) -> bool:
    lowered = name.lower()
    if name.startswith(_FORBIDDEN_SENDER_FREE_PREFIXES):
        return True
    if not name.startswith("src/"):
        return False
    stem = name.rsplit("/", 1)[-1].removesuffix(".py").lower()
    return any(fragment in stem for fragment in _FORBIDDEN_SENDER_FREE_NAME_FRAGMENTS)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_real_sha256(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise PR207ArtifactTruthError(f"PR207_INVALID_{field_name.upper()}")
    if value in {"0" * 64, "f" * 64}:
        raise PR207ArtifactTruthError(f"PR207_PLACEHOLDER_{field_name.upper()}")
