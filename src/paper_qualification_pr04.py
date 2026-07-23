"""NEW-MEGA-PR-04 paper qualification and hermetic-release gate.

This module does not enable live trading.  It validates the evidence that would
be needed to promote a sender-free runtime to production-paper-ready: hermetic
release artifacts, clean wheel/container test evidence, data-lineage quarantine,
and a non-synthetic 72-hour paper soak with unique durable cycles.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

QUALIFICATION_SCHEMA = "new-mega-pr-04.paper-qualification.v1"
SOAK_SCHEMA = "new-mega-pr-04.shadow-soak-report.v1"
MIN_SOAK_SECONDS = 72 * 60 * 60
_SHA256 = re.compile(r"^(sha256:)?[0-9a-f]{64}$")

REQUIRED_RELEASE_ARTIFACTS: tuple[str, ...] = (
    "wheel_digest",
    "container_image_digest",
    "sbom_digest",
    "provenance_attestation",
    "release_signature",
    "clean_wheel_test_report",
    "sandbox_policy_report",
    "data_lineage_quarantine_report",
    "backup_restore_report",
    "security_scan_report",
    "python_optimized_test_report",
    "paper_soak_report",
)

REAL_EVIDENCE_KINDS = frozenset({"real-provider-paper", "materialized-release"})
FORBIDDEN_EVIDENCE_KINDS = frozenset({"synthetic", "recorded", "fixture", "placeholder"})


@dataclass(frozen=True, slots=True)
class PaperQualificationReport:
    accepted: bool
    schema_version: str
    promotion_state: str
    paper_ready: bool
    live_ready: bool
    blockers: tuple[str, ...]
    release_artifacts_required: tuple[str, ...]
    evidence_digest: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _bool(row: Mapping[str, Any], key: str) -> bool:
    value = row.get(key)
    if type(value) is not bool:
        raise ValueError(f"{key} must be boolean")
    return value


def _number(row: Mapping[str, Any], key: str) -> int | float:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    return value


def _artifact_rows(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = manifest.get("release_artifacts")
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError("release_artifacts must be a list of objects")
    return value


def _validate_release_manifest(manifest: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if manifest.get("schema_version") != QUALIFICATION_SCHEMA:
        blockers.append("QUALIFICATION_SCHEMA_INVALID")
    for key in (
        "sender_free_release",
        "live_enabled",
        "offline_build",
        "no_network_release_install",
        "actions_pinned_to_full_sha",
        "images_pinned_by_digest",
        "clean_wheel_tests_passed",
        "container_sandbox_enforced",
        "python_optimized_tests_passed",
        "data_lineage_quarantined",
        "solders_in_test_toolchain",
    ):
        try:
            value = _bool(manifest, key)
        except ValueError:
            blockers.append(f"{key.upper()}_MISSING")
            continue
        if key == "live_enabled":
            if value is not False:
                blockers.append("LIVE_MUST_REMAIN_DISABLED")
        elif value is not True:
            blockers.append(f"{key.upper()}_REQUIRED")

    try:
        artifacts = _artifact_rows(manifest)
    except ValueError:
        return blockers + ["RELEASE_ARTIFACTS_INVALID"]

    by_id = {str(item.get("id")): item for item in artifacts}
    for artifact_id in REQUIRED_RELEASE_ARTIFACTS:
        item = by_id.get(artifact_id)
        if item is None:
            blockers.append(f"MISSING_ARTIFACT:{artifact_id}")
            continue
        digest = str(item.get("sha256", ""))
        if not _SHA256.fullmatch(digest):
            blockers.append(f"ARTIFACT_DIGEST_INVALID:{artifact_id}")
        kind = str(item.get("evidence_kind", ""))
        if kind in FORBIDDEN_EVIDENCE_KINDS:
            blockers.append(f"ARTIFACT_SYNTHETIC_OR_PLACEHOLDER:{artifact_id}")
        if artifact_id != "paper_soak_report" and kind not in REAL_EVIDENCE_KINDS:
            blockers.append(f"ARTIFACT_KIND_NOT_MATERIALIZED:{artifact_id}")
        if item.get("required_before_paper_ready") is not True:
            blockers.append(f"ARTIFACT_NOT_BLOCKING:{artifact_id}")
    return blockers


def _validate_soak_report(report: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if report.get("schema_version") != SOAK_SCHEMA:
        blockers.append("SOAK_SCHEMA_INVALID")
    try:
        duration = _number(report, "duration_seconds")
    except ValueError:
        duration = 0
        blockers.append("SOAK_DURATION_MISSING")
    if duration < MIN_SOAK_SECONDS:
        blockers.append("SOAK_DURATION_LT_72H")
    if str(report.get("evidence_kind", "")) != "real-provider-paper":
        blockers.append("SOAK_NOT_REAL_PROVIDER_PAPER")
    if report.get("live_enabled") is not False:
        blockers.append("SOAK_LIVE_MUST_BE_FALSE")
    if report.get("sender_free") is not True:
        blockers.append("SOAK_MUST_BE_SENDER_FREE")
    if report.get("provider_evidence_present") is not True:
        blockers.append("PROVIDER_EVIDENCE_MISSING")
    if report.get("data_lineage_quarantined") is not True:
        blockers.append("DATA_LINEAGE_NOT_QUARANTINED")
    if int(report.get("unresolved_p0_incidents", -1)) != 0:
        blockers.append("UNRESOLVED_P0_INCIDENTS")
    if int(report.get("duplicate_or_replayed_cycles", -1)) != 0:
        blockers.append("REPLAYED_CYCLES_PRESENT")
    cycle_ids = report.get("unique_cycle_ids")
    if not isinstance(cycle_ids, list) or any(not isinstance(item, str) or not item for item in cycle_ids):
        blockers.append("UNIQUE_CYCLE_IDS_INVALID")
    elif len(cycle_ids) != len(set(cycle_ids)):
        blockers.append("DUPLICATE_CYCLE_IDS")
    elif int(report.get("unique_cycle_count", -1)) != len(cycle_ids):
        blockers.append("UNIQUE_CYCLE_COUNT_MISMATCH")
    for key in ("gross_pnl_paper", "net_pnl_paper", "fee_rent_repayment_impact"):
        try:
            _number(report, key)
        except ValueError:
            blockers.append(f"{key.upper()}_MISSING")
    return blockers


def evaluate_paper_qualification(
    manifest: Mapping[str, Any],
    soak_report: Mapping[str, Any],
) -> PaperQualificationReport:
    blockers = _validate_release_manifest(manifest) + _validate_soak_report(soak_report)
    evidence_digest = None if blockers else _digest({"manifest": manifest, "soak": soak_report})
    accepted = not blockers
    return PaperQualificationReport(
        accepted=accepted,
        schema_version=QUALIFICATION_SCHEMA,
        promotion_state="paper-ready" if accepted else "blocked_pending_real_evidence",
        paper_ready=accepted,
        live_ready=False,
        blockers=tuple(dict.fromkeys(blockers)),
        release_artifacts_required=REQUIRED_RELEASE_ARTIFACTS,
        evidence_digest=evidence_digest,
    )


def load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON value must be an object")
    return payload


def evaluate_paths(manifest_path: str | Path, soak_report_path: str | Path) -> PaperQualificationReport:
    return evaluate_paper_qualification(load_json(manifest_path), load_json(soak_report_path))
