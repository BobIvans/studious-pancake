"""MPR-CLOSE-27 real release evidence artifact gate.

This module deliberately separates *materialized evidence* from promotion. It
never creates fake soak, backup/restore or fault-injection reports. Instead, it
computes hashes from files that already exist under an approved release-artifacts
root, rejects placeholder evidence, validates the high-risk MPR-27 semantics and
keeps live trading disabled.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "mpr27.real-release-evidence.v1"

REQUIRED_RELEASE_ARTIFACTS = frozenset(
    {
        "runtime_wheel_digest",
        "runtime_image_digest",
        "sbom_digest",
        "config_generation_digest",
        "capability_manifest_digest",
        "program_idl_hashes",
        "database_schema_fingerprint",
        "shadow_campaign_report_digest",
        "fault_injection_report_digest",
        "backup_restore_report_digest",
    }
)
OPTIONAL_OPERATIONAL_ARTIFACTS = frozenset(
    {"slo_baseline_report_digest", "secret_incident_drill_report_digest"}
)
ALL_KNOWN_ARTIFACTS = REQUIRED_RELEASE_ARTIFACTS | OPTIONAL_OPERATIONAL_ARTIFACTS

REQUIRED_FAULT_CASES = frozenset(
    {
        "rpc_stale_slot",
        "provider_timeout",
        "schema_drift",
        "database_write_failure",
        "crash_during_reservation",
        "expired_quote",
        "replayed_webhook",
        "clock_rollback",
        "partial_restore",
    }
)
REQUIRED_SLO_METRICS = frozenset(
    {
        "quote_latency_p99_ms",
        "queue_lag_p99_ms",
        "reconciliation_lag_p99_ms",
        "provider_failure_rate",
        "data_loss_replay_rate",
        "memory_fd_growth",
    }
)
REQUIRED_SECRET_DRILLS = frozenset(
    {
        "missing_secret",
        "revoked_secret",
        "rotated_secret",
        "wrong_permissions",
        "leaked_env_alias_blocked",
    }
)
PLACEHOLDER_MARKERS = (
    "placeholder",
    "fake evidence",
    "unit-test fixture",
    "tmp-only",
    "one-shot smoke",
    "todo",
)


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    id: str
    path: str
    sha256: str
    size_bytes: int
    evidence_kind: str


@dataclass(frozen=True, slots=True)
class EvidenceReport:
    schema_version: str
    generated_at_unix_ns: int
    promotion_state: str
    live_trading_enabled: bool
    accepted: bool
    missing_artifacts: tuple[str, ...]
    blockers: tuple[str, ...]
    artifacts: tuple[EvidenceArtifact, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at_unix_ns": self.generated_at_unix_ns,
            "promotion_state": self.promotion_state,
            "live_trading_enabled": self.live_trading_enabled,
            "accepted": self.accepted,
            "missing_artifacts": list(self.missing_artifacts),
            "blockers": list(self.blockers),
            "artifacts": [asdict(item) for item in self.artifacts],
        }


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _resolve_child(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("artifact path must be a relative child")
    resolved_root = root.resolve()
    target = (resolved_root / relative).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("artifact escapes approved root") from exc
    if target.is_symlink() or not target.is_file():
        raise ValueError("artifact must be a regular non-symlink file")
    return target


def _load_json_object(raw: bytes, artifact_id: str) -> dict[str, Any]:
    try:
        loaded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{artifact_id} must be a JSON object") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"{artifact_id} must be a JSON object")
    return loaded


def _passed_case_ids(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    passed: set[str] = set()
    for item in value:
        if isinstance(item, dict) and item.get("passed") is True:
            case_id = item.get("id")
            if isinstance(case_id, str) and case_id:
                passed.add(case_id)
    return passed


def _validate_shadow_campaign(raw: bytes) -> tuple[str, ...]:
    data = _load_json_object(raw, "shadow_campaign_report_digest")
    blockers: list[str] = []
    if data.get("synthetic") is not False:
        blockers.append("SHADOW_CAMPAIGN_SYNTHETIC")
    if data.get("sender_enabled") is not False:
        blockers.append("SHADOW_CAMPAIGN_SENDER_ENABLED")
    if data.get("keypair_loaded") is not False:
        blockers.append("SHADOW_CAMPAIGN_KEYPAIR_LOADED")
    if data.get("provider_data_lineage") != "provider":
        blockers.append("SHADOW_CAMPAIGN_NOT_PROVIDER_LINEAGE")
    days = data.get("campaign_days")
    if not isinstance(days, (int, float)) or isinstance(days, bool) or days < 2:
        blockers.append("SHADOW_CAMPAIGN_TOO_SHORT")
    return tuple(blockers)


def _validate_fault_injection(raw: bytes) -> tuple[str, ...]:
    data = _load_json_object(raw, "fault_injection_report_digest")
    missing = REQUIRED_FAULT_CASES - _passed_case_ids(data.get("cases"))
    return tuple(f"FAULT_CASE_MISSING_{case}" for case in sorted(missing))


def _validate_backup_restore(raw: bytes) -> tuple[str, ...]:
    data = _load_json_object(raw, "backup_restore_report_digest")
    blockers: list[str] = []
    if data.get("restored_into_clean_runtime") is not True:
        blockers.append("BACKUP_RESTORE_NOT_CLEAN_RUNTIME")
    if data.get("event_chain_verified") is not True:
        blockers.append("BACKUP_RESTORE_EVENT_CHAIN_NOT_VERIFIED")
    if data.get("duplicate_decisions_after_restore") != 0:
        blockers.append("BACKUP_RESTORE_DUPLICATE_DECISIONS")
    return tuple(blockers)


def _is_non_negative_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _validate_slo_baseline(raw: bytes) -> tuple[str, ...]:
    data = _load_json_object(raw, "slo_baseline_report_digest")
    metrics = data.get("metrics")
    if not isinstance(metrics, dict):
        return ("SLO_BASELINE_METRICS_MISSING",)
    return tuple(
        f"SLO_METRIC_INVALID_{metric}"
        for metric in sorted(REQUIRED_SLO_METRICS)
        if not _is_non_negative_number(metrics.get(metric))
    )


def _validate_secret_drill(raw: bytes) -> tuple[str, ...]:
    data = _load_json_object(raw, "secret_incident_drill_report_digest")
    missing = REQUIRED_SECRET_DRILLS - _passed_case_ids(data.get("cases"))
    blockers = [f"SECRET_DRILL_MISSING_{case}" for case in sorted(missing)]
    if data.get("raw_secret_logged") is not False:
        blockers.append("SECRET_DRILL_RAW_SECRET_LOGGED")
    return tuple(blockers)


def _semantic_blockers(artifact_id: str, raw: bytes) -> tuple[str, ...]:
    text = raw[:8192].decode("utf-8", errors="ignore").lower()
    if any(marker in text for marker in PLACEHOLDER_MARKERS):
        return ("PLACEHOLDER_EVIDENCE_REJECTED",)
    validators = {
        "shadow_campaign_report_digest": _validate_shadow_campaign,
        "fault_injection_report_digest": _validate_fault_injection,
        "backup_restore_report_digest": _validate_backup_restore,
        "slo_baseline_report_digest": _validate_slo_baseline,
        "secret_incident_drill_report_digest": _validate_secret_drill,
    }
    validator = validators.get(artifact_id)
    return validator(raw) if validator is not None else ()


def _materialize_artifact(
    root: Path,
    artifact_id: str,
    relative: str,
) -> tuple[EvidenceArtifact | None, tuple[str, ...]]:
    if artifact_id not in ALL_KNOWN_ARTIFACTS:
        return None, (f"UNKNOWN_ARTIFACT_{artifact_id}",)
    try:
        target = _resolve_child(root, relative)
        raw = target.read_bytes()
    except OSError:
        return None, (f"ARTIFACT_UNREADABLE_{artifact_id}",)
    except ValueError:
        return None, (f"ARTIFACT_INVALID_PATH_{artifact_id}",)
    if not raw:
        return None, (f"ARTIFACT_EMPTY_{artifact_id}",)
    blockers = _semantic_blockers(artifact_id, raw)
    if blockers:
        return None, tuple(f"{artifact_id}:{blocker}" for blocker in blockers)
    return (
        EvidenceArtifact(
            id=artifact_id,
            path=Path(relative).as_posix(),
            sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            evidence_kind="materialized_file_sha256",
        ),
        (),
    )


def build_release_evidence_report(
    *,
    root: str | os.PathLike[str],
    artifact_paths: Mapping[str, str],
    generated_at_unix_ns: int | None = None,
) -> EvidenceReport:
    artifacts: list[EvidenceArtifact] = []
    blockers: list[str] = []
    approved_root = Path(root)
    for artifact_id, relative in sorted(artifact_paths.items()):
        artifact, artifact_blockers = _materialize_artifact(
            approved_root,
            artifact_id,
            relative,
        )
        blockers.extend(artifact_blockers)
        if artifact is not None:
            artifacts.append(artifact)

    materialized_ids = {artifact.id for artifact in artifacts}
    missing_artifacts = tuple(sorted(REQUIRED_RELEASE_ARTIFACTS - materialized_ids))
    blockers.extend(f"MISSING_{artifact.upper()}" for artifact in missing_artifacts)
    accepted = not blockers and not missing_artifacts
    return EvidenceReport(
        schema_version=SCHEMA_VERSION,
        generated_at_unix_ns=generated_at_unix_ns or time.time_ns(),
        promotion_state=(
            "review_ready_release_evidence" if accepted else "blocked_pending_evidence"
        ),
        live_trading_enabled=False,
        accepted=accepted,
        missing_artifacts=missing_artifacts,
        blockers=tuple(dict.fromkeys(blockers)),
        artifacts=tuple(artifacts),
    )


def _report_path(output: str | os.PathLike[str]) -> Path:
    target = Path(output)
    if target.suffix == ".json":
        return target
    return target / "mpr27_release_evidence_report.json"


def write_report_atomic(output: str | os.PathLike[str], report: EvidenceReport) -> Path:
    target = _report_path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_json(report.to_dict())
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return target


def _parse_artifact_arguments(values: Sequence[str] | None) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for value in values or ():
        artifact_id, separator, relative = value.partition("=")
        if not separator or not artifact_id or not relative:
            raise SystemExit("--artifact must use id=relative/path syntax")
        artifacts[artifact_id] = relative
    return artifacts


def verify_report(
    *,
    root: str | os.PathLike[str],
    report_path: str | os.PathLike[str],
) -> EvidenceReport:
    loaded = json.loads(Path(report_path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or loaded.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("MPR-27 evidence report schema is invalid")
    raw_artifacts = loaded.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise ValueError("MPR-27 evidence report artifacts must be a list")

    artifact_paths: dict[str, str] = {}
    for item in raw_artifacts:
        if not isinstance(item, dict):
            raise ValueError("MPR-27 evidence artifact entries must be objects")
        artifact_id = item.get("id")
        relative = item.get("path")
        if not isinstance(artifact_id, str) or not isinstance(relative, str):
            raise ValueError("MPR-27 evidence artifact id/path must be strings")
        artifact_paths[artifact_id] = relative

    generated_at = loaded.get("generated_at_unix_ns")
    current = build_release_evidence_report(
        root=root,
        artifact_paths=artifact_paths,
        generated_at_unix_ns=generated_at if isinstance(generated_at, int) else None,
    )
    original_sha = hashlib.sha256(_canonical_json(loaded)).hexdigest()
    current_sha = hashlib.sha256(_canonical_json(current.to_dict())).hexdigest()
    if original_sha != current_sha:
        current = EvidenceReport(
            schema_version=current.schema_version,
            generated_at_unix_ns=current.generated_at_unix_ns,
            promotion_state="blocked_pending_evidence",
            live_trading_enabled=False,
            accepted=False,
            missing_artifacts=current.missing_artifacts,
            blockers=current.blockers + ("REPORT_DIGEST_DRIFT",),
            artifacts=current.artifacts,
        )
    return current


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flashloan-release-evidence")
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate")
    generate.add_argument("--root", default=".")
    generate.add_argument("--output", required=True)
    generate.add_argument("--artifact", action="append")

    verify = commands.add_parser("verify-mpr27")
    verify.add_argument("--root", default=".")
    verify.add_argument("--report", required=True)

    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "generate":
        report = build_release_evidence_report(
            root=args.root,
            artifact_paths=_parse_artifact_arguments(args.artifact),
        )
        target = write_report_atomic(args.output, report)
        payload = report.to_dict() | {"report_path": str(target)}
        print(json.dumps(payload, sort_keys=True))
        return 0

    report = verify_report(root=args.root, report_path=args.report)
    print(json.dumps(report.to_dict(), sort_keys=True))
    return 0 if report.accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
