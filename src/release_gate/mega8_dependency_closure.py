"""Current-head MEGA8 dependency reconciliation.

Historical merge-order inversions remain immutable audit facts.  This module
proves that the prerequisite contracts are now present together on one closure
baseline and that stale dependency blockers are not reused as current truth.

It is an evidence consumer only: no network, signer, sender, wallet, capital, or
release-promotion authority is introduced here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping

SCHEMA = "mega8.dependency-reconciliation.v1"
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")

EXPECTED_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "MEGA8-01": (),
    "MEGA8-02": ("MEGA8-01",),
    "MEGA8-03": ("MEGA8-01", "MEGA8-02"),
    "MEGA8-04": ("MEGA8-01", "MEGA8-02", "MEGA8-03"),
    "MEGA8-05": ("MEGA8-01", "MEGA8-02", "MEGA8-03", "MEGA8-04"),
    "MEGA8-06": (
        "MEGA8-01",
        "MEGA8-02",
        "MEGA8-03",
        "MEGA8-04",
        "MEGA8-05",
    ),
    "MEGA8-07": (
        "MEGA8-01",
        "MEGA8-02",
        "MEGA8-03",
        "MEGA8-04",
        "MEGA8-05",
        "MEGA8-06",
    ),
}

STALE_DEPENDENCY_TOKENS = (
    "MEGA8_01_FULL_EIGHT_PACK_PREREQUISITE_NOT_CLAIMED_CLOSED",
    "MEGA8_01_EXACT_PREREQUISITE_NOT_MERGED",
    "MEGA8_02_PR_523_OPEN_NOT_MERGED",
    "MEGA8_03_PR_521_OPEN_NOT_MERGED",
    "MEGA8_04_PR_522_OPEN_NOT_MERGED",
    "MEGA8_04_NOT_MERGED",
    "MEGA8-04/#522 and MEGA8-05/#524 remain open",
    "AGG04_REQUALIFICATION_REQUIRED_ON_EXACT_LENDER_PROFILE_GENERATION",
)


@dataclass(frozen=True, slots=True)
class MegaReceipt:
    mega_id: str
    pr: int
    merge_commit: str
    merged_at: str
    dependencies: tuple[str, ...]
    followup_merge_commits: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MegaDependencyAudit:
    schema: str
    closure_base_sha: str
    package_count: int
    all_dependencies_present: bool
    unresolved_dependencies: tuple[str, ...]
    historical_order_inversions: tuple[str, ...]
    merge_commits: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _require_sha(value: object, name: str) -> str:
    if not isinstance(value, str) or not _GIT_SHA.fullmatch(value):
        raise ValueError(f"{name} must be a full lowercase git SHA")
    return value


def load_receipts(
    path: str | Path,
) -> tuple[str, tuple[MegaReceipt, ...], Mapping[str, Any]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or raw.get("schema") != SCHEMA:
        raise ValueError("MEGA8_DEBT_SCHEMA_MISMATCH")

    closure_base = _require_sha(raw.get("closure_base_sha"), "closure_base_sha")
    packages = raw.get("packages")
    if not isinstance(packages, list):
        raise ValueError("MEGA8_DEBT_PACKAGES_REQUIRED")

    receipts: list[MegaReceipt] = []
    for item in packages:
        if not isinstance(item, Mapping):
            raise ValueError("MEGA8_DEBT_RECEIPT_OBJECT_REQUIRED")
        mega_id = str(item.get("mega_id", ""))
        if mega_id not in EXPECTED_DEPENDENCIES:
            raise ValueError(f"MEGA8_DEBT_UNKNOWN_PACKAGE:{mega_id}")
        deps = item.get("dependencies")
        followups = item.get("followup_merge_commits", [])
        if not isinstance(deps, list) or any(not isinstance(x, str) for x in deps):
            raise ValueError(f"MEGA8_DEBT_DEPENDENCIES_INVALID:{mega_id}")
        if not isinstance(followups, list):
            raise ValueError(f"MEGA8_DEBT_FOLLOWUPS_INVALID:{mega_id}")
        receipt = MegaReceipt(
            mega_id=mega_id,
            pr=int(item.get("pr", 0)),
            merge_commit=_require_sha(
                item.get("merge_commit"), f"{mega_id}.merge_commit"
            ),
            merged_at=str(item.get("merged_at", "")),
            dependencies=tuple(deps),
            followup_merge_commits=tuple(
                _require_sha(value, f"{mega_id}.followup") for value in followups
            ),
        )
        if receipt.pr <= 0:
            raise ValueError(f"MEGA8_DEBT_PR_INVALID:{mega_id}")
        datetime.fromisoformat(receipt.merged_at.replace("Z", "+00:00"))
        receipts.append(receipt)

    requalification = raw.get("requalification")
    if not isinstance(requalification, Mapping):
        raise ValueError("MEGA8_DEBT_REQUALIFICATION_REQUIRED")
    return closure_base, tuple(receipts), requalification


def audit_receipts(path: str | Path) -> MegaDependencyAudit:
    closure_base, receipts, _ = load_receipts(path)
    by_id: dict[str, MegaReceipt] = {}
    for item in receipts:
        if item.mega_id in by_id:
            raise ValueError(f"MEGA8_DEBT_DUPLICATE_PACKAGE:{item.mega_id}")
        by_id[item.mega_id] = item

    missing = sorted(set(EXPECTED_DEPENDENCIES).difference(by_id))
    if missing:
        raise ValueError("MEGA8_DEBT_MISSING_PACKAGES:" + ",".join(missing))

    unresolved: list[str] = []
    inversions: list[str] = []
    for mega_id, expected in EXPECTED_DEPENDENCIES.items():
        receipt = by_id[mega_id]
        if receipt.dependencies != expected:
            raise ValueError(f"MEGA8_DEBT_DEPENDENCY_MAP_MISMATCH:{mega_id}")
        current_time = datetime.fromisoformat(receipt.merged_at.replace("Z", "+00:00"))
        for dependency in expected:
            parent = by_id.get(dependency)
            if parent is None:
                unresolved.append(f"{mega_id}:{dependency}")
                continue
            parent_time = datetime.fromisoformat(
                parent.merged_at.replace("Z", "+00:00")
            )
            if parent_time > current_time:
                inversions.append(f"{mega_id}:before:{dependency}")

    return MegaDependencyAudit(
        schema=SCHEMA,
        closure_base_sha=closure_base,
        package_count=len(by_id),
        all_dependencies_present=not unresolved,
        unresolved_dependencies=tuple(sorted(unresolved)),
        historical_order_inversions=tuple(sorted(inversions)),
        merge_commits=tuple(by_id[key].merge_commit for key in sorted(by_id)),
    )


def verify_current_manifests(
    root: str | Path, receipt_path: str | Path
) -> dict[str, Any]:
    root_path = Path(root)
    audit = audit_receipts(receipt_path)
    _, _, requalification = load_receipts(receipt_path)
    errors: list[str] = []

    expected_inversions = {
        "MEGA8-02:before:MEGA8-01",
        "MEGA8-05:before:MEGA8-04",
        "MEGA8-06:before:MEGA8-04",
    }
    if set(audit.historical_order_inversions) != expected_inversions:
        errors.append("MEGA8_HISTORICAL_INVERSION_SET_MISMATCH")

    manifest_paths = (
        "config/mega8_02_coverage.json",
        "release_artifacts/mega8/MEGA8-05/coverage.json",
        "config/mega8_06_coverage.json",
        "release_artifacts/mega8/MEGA8-06/coverage.json",
        "release_artifacts/mega8/MEGA8-07/coverage.json",
        "release_artifacts/super/SUPER-02/coverage.json",
    )
    payloads: dict[str, Mapping[str, Any]] = {}
    for relative in manifest_paths:
        path = root_path / relative
        if not path.is_file():
            errors.append(f"MEGA8_MANIFEST_MISSING:{relative}")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            errors.append(f"MEGA8_MANIFEST_NOT_OBJECT:{relative}")
            continue
        payloads[relative] = payload
        text = json.dumps(payload, sort_keys=True)
        for token in STALE_DEPENDENCY_TOKENS:
            if token in text:
                errors.append(f"MEGA8_STALE_DEPENDENCY_TOKEN:{relative}:{token}")

    mega02 = payloads.get("config/mega8_02_coverage.json", {})
    dependency02 = mega02.get("dependency_status")
    if not isinstance(dependency02, Mapping) or not isinstance(
        dependency02.get("MEGA8-01"), Mapping
    ):
        errors.append("MEGA8_02_DEPENDENCY_STATUS_MISSING")
    elif dependency02["MEGA8-01"].get("status") != "MERGED_REQUALIFIED":
        errors.append("MEGA8_02_NOT_REQUALIFIED_AFTER_MEGA8_01")

    mega05 = payloads.get("release_artifacts/mega8/MEGA8-05/coverage.json", {})
    if mega05.get("operational_status") != "BLOCKED_EXTERNAL_EVIDENCE":
        errors.append("MEGA8_05_DEPENDENCY_BLOCK_NOT_RETIRED")

    for relative in (
        "config/mega8_06_coverage.json",
        "release_artifacts/mega8/MEGA8-06/coverage.json",
    ):
        payload = payloads.get(relative, {})
        if payload.get("operational_status") != "BLOCKED_EXTERNAL_EVIDENCE":
            errors.append(f"MEGA8_06_DEPENDENCY_BLOCK_NOT_RETIRED:{relative}")

    mega07 = payloads.get("release_artifacts/mega8/MEGA8-07/coverage.json", {})
    if mega07.get("operational_status") != "BLOCKED_EXTERNAL_AND_PROMOTION_EVIDENCE":
        errors.append("MEGA8_07_DEPENDENCY_BLOCK_NOT_RETIRED")

    super02 = payloads.get("release_artifacts/super/SUPER-02/coverage.json", {})
    current_requalification = super02.get("current_head_requalification")
    if not isinstance(current_requalification, Mapping):
        errors.append("SUPER02_CURRENT_HEAD_REQUALIFICATION_MISSING")
    else:
        if current_requalification.get("status") != "CODE_CONTRACT_REQUALIFIED":
            errors.append("SUPER02_AGG04_CODE_REQUALIFICATION_MISSING")
        if current_requalification.get("closure_base_sha") != audit.closure_base_sha:
            errors.append("SUPER02_REQUALIFICATION_BASE_MISMATCH")

    super02_receipt = requalification.get("SUPER02_AGG04")
    if not isinstance(super02_receipt, Mapping):
        errors.append("SUPER02_AGG04_RECEIPT_MISSING")
    elif super02_receipt.get("status") != "CODE_CONTRACT_REQUALIFIED":
        errors.append("SUPER02_AGG04_RECEIPT_NOT_REQUALIFIED")

    safety_fields = (
        "live_enabled",
        "signing_enabled",
        "submission_enabled",
        "automatic_capital_increase",
        "automatic_capital_increase_allowed",
    )
    for relative, payload in payloads.items():
        for field in safety_fields:
            if field in payload and payload.get(field) is not False:
                errors.append(f"MEGA8_UNSAFE_FLAG:{relative}:{field}")

    return {
        "schema": SCHEMA,
        "accepted": not errors,
        "closure_base_sha": audit.closure_base_sha,
        "package_count": audit.package_count,
        "historical_order_inversions": list(audit.historical_order_inversions),
        "all_dependencies_present": audit.all_dependencies_present,
        "errors": errors,
        "production_ready": False,
        "live_enabled": False,
        "automatic_capital_increase_allowed": False,
    }


__all__ = [
    "EXPECTED_DEPENDENCIES",
    "MegaDependencyAudit",
    "MegaReceipt",
    "SCHEMA",
    "STALE_DEPENDENCY_TOKENS",
    "audit_receipts",
    "load_receipts",
    "verify_current_manifests",
]
