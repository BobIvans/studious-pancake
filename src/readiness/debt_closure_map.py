"""Fail-closed debt closure authority for staged production readiness.

MPR-NEXT-07 deliberately separates *gate success* from *production-debt
closure*.  Offline gate modules can prove useful properties, but they must not
mark production debt as resolved unless their evidence is bound to the installed
artifact, the active runtime command surface, a fresh/replayable evidence bundle,
and a CI-authoritative run.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
import hashlib
import json
import re
import zipfile

SCHEMA_VERSION = "mpr-next-07.debt-closure-authority.v1"
ARCHIVE_DIFF_SCHEMA_VERSION = "mpr-next-07.archive-diff-sanity.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

MPR31_REQUIRED_UPSTREAMS = frozenset(
    {"MPR-25", "MPR-26", "MPR-27", "MPR-28", "MPR-29", "MPR-30"}
)


@dataclass(frozen=True, slots=True)
class GateDebtMapping:
    """Stable mapping from a reviewed evidence producer to debt IDs."""

    gate_id: str
    evidence_kind: str
    debt_ids: tuple[str, ...]


GATE_DEBT_MAP: dict[str, GateDebtMapping] = {
    "PR-225": GateDebtMapping(
        gate_id="PR-225",
        evidence_kind="secure-provider-plane",
        debt_ids=(
            "external.jupiter-swap-v2",
            "evidence.provider-drift-probes",
        ),
    ),
    "PR-226": GateDebtMapping(
        gate_id="PR-226",
        evidence_kind="deterministic-runtime-dataset-shadow",
        debt_ids=(
            "evidence.real-shadow-soak",
            "data.lineage-quarantine",
            "operations.slo-readiness",
        ),
    ),
    "PR-228": GateDebtMapping(
        gate_id="PR-228",
        evidence_kind="secret-trust-release",
        debt_ids=(
            "security.secret-incident-drill",
            "security.signer-isolation",
        ),
    ),
    "MPR-31": GateDebtMapping(
        gate_id="MPR-31",
        evidence_kind="final-production-promotion",
        debt_ids=(
            "runtime.product-state",
            "runtime.live-entrypoint",
            "deployment.image-provenance",
            "canary.permit-budget-latches",
            "canary.second-human-approval",
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class DebtClosureViolation:
    code: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DebtClosureDecision:
    schema_version: str
    gate_id: str
    evidence_kind: str | None
    ok: bool
    resolved_debt_ids: tuple[str, ...]
    blocked_debt_ids: tuple[str, ...]
    violations: tuple[DebtClosureViolation, ...]
    closure_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "gate_id": self.gate_id,
            "evidence_kind": self.evidence_kind,
            "ok": self.ok,
            "resolved_debt_ids": list(self.resolved_debt_ids),
            "blocked_debt_ids": list(self.blocked_debt_ids),
            "violations": [item.to_dict() for item in self.violations],
            "closure_digest": self.closure_digest,
            "production_ready": False,
            "paper_ready": False,
            "live_ready": False,
        }


def evaluate_debt_closure_evidence(payload: Mapping[str, Any]) -> DebtClosureDecision:
    """Evaluate one gate output as production-debt closure evidence.

    The function is intentionally conservative.  A successful offline gate only
    resolves mapped debt when every runtime/evidence binding is present.  Unknown
    gates, source-only fixtures, synthetic evidence, stale evidence, or unbound
    installed-artifact claims all fail closed.
    """

    violations: list[DebtClosureViolation] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        violations.append(
            DebtClosureViolation(
                "DEBT_CLOSURE_SCHEMA_VERSION",
                f"expected schema_version={SCHEMA_VERSION}",
            )
        )

    gate_id = _text(payload.get("gate_id"), "gate_id", violations)
    mapping = GATE_DEBT_MAP.get(gate_id)
    evidence_kind: str | None = None
    stable_ids: tuple[str, ...] = ()
    if mapping is None:
        violations.append(
            DebtClosureViolation(
                "DEBT_CLOSURE_UNKNOWN_GATE",
                f"unknown gate_id={gate_id!r}",
            )
        )
    else:
        evidence_kind = mapping.evidence_kind
        stable_ids = mapping.debt_ids
        if payload.get("evidence_kind") != mapping.evidence_kind:
            violations.append(
                DebtClosureViolation(
                    "DEBT_CLOSURE_EVIDENCE_KIND_DRIFT",
                    f"{gate_id} must produce {mapping.evidence_kind}",
                )
            )

    claimed_ids = _string_sequence(payload.get("debt_ids"), "debt_ids", violations)
    if not claimed_ids and stable_ids:
        claimed_ids = stable_ids
    unknown_claims = sorted(set(claimed_ids) - set(stable_ids))
    if unknown_claims:
        violations.append(
            DebtClosureViolation(
                "DEBT_CLOSURE_UNMAPPED_DEBT_ID",
                f"{gate_id} cannot close {','.join(unknown_claims)}",
            )
        )
    closeable_ids = tuple(sorted(set(claimed_ids) & set(stable_ids)))
    if not closeable_ids:
        violations.append(
            DebtClosureViolation(
                "DEBT_CLOSURE_NO_MAPPED_DEBT",
                "no stable mapped debt ids were requested",
            )
        )

    _require_true(payload, "gate_ok", "DEBT_CLOSURE_GATE_NOT_OK", violations)
    _require_true(
        payload,
        "runtime_bound",
        "DEBT_CLOSURE_RUNTIME_BINDING_REQUIRED",
        violations,
    )
    _require_true(
        payload,
        "installed_artifact_bound",
        "DEBT_CLOSURE_INSTALLED_ARTIFACT_REQUIRED",
        violations,
    )
    _require_true(
        payload,
        "evidence_fresh",
        "DEBT_CLOSURE_FRESH_EVIDENCE_REQUIRED",
        violations,
    )
    _require_true(
        payload,
        "replayable",
        "DEBT_CLOSURE_REPLAY_REQUIRED",
        violations,
    )
    _require_true(
        payload,
        "ci_authoritative",
        "DEBT_CLOSURE_CI_AUTHORITY_REQUIRED",
        violations,
    )

    _require_false(payload, "source_only", "DEBT_CLOSURE_SOURCE_ONLY", violations)
    _require_false(payload, "synthetic", "DEBT_CLOSURE_SYNTHETIC_EVIDENCE", violations)

    for key in (
        "artifact_sha256",
        "runtime_command_surface_sha256",
        "evidence_sha256",
        "freshness_proof_sha256",
    ):
        _require_digest(payload.get(key), key, violations)

    if gate_id == "MPR-31":
        upstreams = set(
            _string_sequence(payload.get("upstream_mprs"), "upstream_mprs", violations)
        )
        missing = sorted(MPR31_REQUIRED_UPSTREAMS - upstreams)
        if missing:
            violations.append(
                DebtClosureViolation(
                    "DEBT_CLOSURE_MPR31_UPSTREAMS_MISSING",
                    f"missing upstream MPR evidence: {','.join(missing)}",
                )
            )

    ok = not violations
    resolved = closeable_ids if ok else ()
    blocked = () if ok else closeable_ids
    digest = _hash_json(
        {
            "schema_version": SCHEMA_VERSION,
            "gate_id": gate_id,
            "evidence_kind": evidence_kind,
            "resolved": resolved,
            "blocked": blocked,
            "violations": [item.to_dict() for item in violations],
        }
    )
    return DebtClosureDecision(
        schema_version=SCHEMA_VERSION,
        gate_id=gate_id,
        evidence_kind=evidence_kind,
        ok=ok,
        resolved_debt_ids=resolved,
        blocked_debt_ids=blocked,
        violations=tuple(violations),
        closure_digest=digest,
    )


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    path: str
    size: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ArchiveDiffReport:
    schema_version: str
    previous_archive: str
    current_archive: str
    identical: bool
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]
    file_count_previous: int
    file_count_current: int
    manifest_digest_previous: str
    manifest_digest_current: str

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "previous_archive": self.previous_archive,
            "current_archive": self.current_archive,
            "identical": self.identical,
            "has_changes": self.has_changes,
            "added": list(self.added),
            "removed": list(self.removed),
            "changed": list(self.changed),
            "file_count_previous": self.file_count_previous,
            "file_count_current": self.file_count_current,
            "manifest_digest_previous": self.manifest_digest_previous,
            "manifest_digest_current": self.manifest_digest_current,
        }


def compare_archives(previous_archive: str | Path, current_archive: str | Path) -> ArchiveDiffReport:
    """Compare two ZIP archives by path, size and SHA-256 content hash."""

    previous_path = Path(previous_archive)
    current_path = Path(current_archive)
    previous = _zip_manifest(previous_path)
    current = _zip_manifest(current_path)
    previous_paths = set(previous)
    current_paths = set(current)
    added = tuple(sorted(current_paths - previous_paths))
    removed = tuple(sorted(previous_paths - current_paths))
    changed = tuple(
        sorted(
            path
            for path in previous_paths & current_paths
            if previous[path].sha256 != current[path].sha256
            or previous[path].size != current[path].size
        )
    )
    previous_digest = _hash_json(
        {path: previous[path].to_dict() for path in sorted(previous)}
    )
    current_digest = _hash_json({path: current[path].to_dict() for path in sorted(current)})
    return ArchiveDiffReport(
        schema_version=ARCHIVE_DIFF_SCHEMA_VERSION,
        previous_archive=str(previous_path),
        current_archive=str(current_path),
        identical=previous_digest == current_digest,
        added=added,
        removed=removed,
        changed=changed,
        file_count_previous=len(previous),
        file_count_current=len(current),
        manifest_digest_previous=previous_digest,
        manifest_digest_current=current_digest,
    )


def closure_map_digest() -> str:
    return _hash_json(
        {
            gate_id: {
                "evidence_kind": mapping.evidence_kind,
                "debt_ids": list(mapping.debt_ids),
            }
            for gate_id, mapping in sorted(GATE_DEBT_MAP.items())
        }
    )


def _zip_manifest(path: Path) -> dict[str, ArchiveEntry]:
    if not path.is_file():
        raise FileNotFoundError(path)
    entries: dict[str, ArchiveEntry] = {}
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            data = archive.read(info.filename)
            entries[info.filename] = ArchiveEntry(
                path=info.filename,
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
    return entries


def _require_true(
    payload: Mapping[str, Any],
    key: str,
    code: str,
    violations: list[DebtClosureViolation],
) -> None:
    if payload.get(key) is not True:
        violations.append(DebtClosureViolation(code, f"{key} must be true"))


def _require_false(
    payload: Mapping[str, Any],
    key: str,
    code: str,
    violations: list[DebtClosureViolation],
) -> None:
    if payload.get(key) is True:
        violations.append(DebtClosureViolation(code, f"{key} must not be true"))


def _require_digest(
    value: Any,
    key: str,
    violations: list[DebtClosureViolation],
) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        violations.append(
            DebtClosureViolation(
                "DEBT_CLOSURE_DIGEST_REQUIRED",
                f"{key} must be a lowercase sha256 digest",
            )
        )


def _text(
    value: Any,
    key: str,
    violations: list[DebtClosureViolation],
) -> str:
    if not isinstance(value, str) or not value.strip():
        violations.append(
            DebtClosureViolation("DEBT_CLOSURE_TEXT_REQUIRED", f"{key} is required")
        )
        return ""
    return value.strip()


def _string_sequence(
    value: Any,
    key: str,
    violations: list[DebtClosureViolation],
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        violations.append(
            DebtClosureViolation(
                "DEBT_CLOSURE_LIST_REQUIRED",
                f"{key} must be a sequence of strings",
            )
        )
        return ()
    items = tuple(str(item).strip() for item in value if str(item).strip())
    if len(items) != len(value):
        violations.append(
            DebtClosureViolation(
                "DEBT_CLOSURE_LIST_REQUIRED",
                f"{key} must contain non-empty strings",
            )
        )
    return items


def _hash_json(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ARCHIVE_DIFF_SCHEMA_VERSION",
    "ArchiveDiffReport",
    "ArchiveEntry",
    "DebtClosureDecision",
    "DebtClosureViolation",
    "GATE_DEBT_MAP",
    "GateDebtMapping",
    "SCHEMA_VERSION",
    "closure_map_digest",
    "compare_archives",
    "evaluate_debt_closure_evidence",
]
