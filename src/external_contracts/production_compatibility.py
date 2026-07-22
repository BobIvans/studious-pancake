"""Deterministic production-debt and external-contract compatibility gate."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "pr149.production-compatibility.v1"


class ProductionCompatibilityError(ValueError):
    """Raised when the production-debt manifest is malformed."""


@dataclass(frozen=True, slots=True)
class CompatibilityFinding:
    finding_id: str
    severity: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class ProductionCompatibilityReport:
    schema_version: str
    ready: bool
    live_trading_allowed: bool
    blockers: tuple[CompatibilityFinding, ...]
    warnings: tuple[CompatibilityFinding, ...]
    debt_item_count: int
    epic_count: int
    report_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ready": self.ready,
            "live_trading_allowed": self.live_trading_allowed,
            "blockers": [asdict(item) for item in self.blockers],
            "warnings": [asdict(item) for item in self.warnings],
            "debt_item_count": self.debt_item_count,
            "epic_count": self.epic_count,
            "report_sha256": self.report_sha256,
        }


def evaluate_production_compatibility(
    repository_root: str | Path,
    manifest_path: str | Path,
) -> ProductionCompatibilityReport:
    """Evaluate pinned source-contract rules without network access."""

    root = Path(repository_root).resolve()
    manifest_file = Path(manifest_path).resolve()
    payload = _load_manifest(manifest_file)
    blockers: list[CompatibilityFinding] = []
    warnings: list[CompatibilityFinding] = []

    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ProductionCompatibilityError(
            f"schema_version must equal {SCHEMA_VERSION}"
        )
    live_trading_allowed = bool(payload.get("live_trading_allowed", False))
    if live_trading_allowed:
        blockers.append(
            CompatibilityFinding(
                "LIVE_MODE_MUST_REMAIN_DISABLED",
                "blocker",
                manifest_file.name,
                "The convergence roadmap must not enable live trading.",
            )
        )

    epics = _require_object_list(payload.get("epics"), "epics")
    debt_ids: set[str] = set()
    for epic in epics:
        epic_id = _require_nonempty_string(epic.get("id"), "epic.id")
        items = _require_object_list(epic.get("items"), f"{epic_id}.items")
        if not items:
            raise ProductionCompatibilityError(f"{epic_id} has no debt items")
        for item in items:
            debt_id = _require_nonempty_string(item.get("id"), "debt.id")
            if debt_id in debt_ids:
                raise ProductionCompatibilityError(
                    f"duplicate production debt id: {debt_id}"
                )
            debt_ids.add(debt_id)
            _require_nonempty_string(item.get("title"), f"{debt_id}.title")
            _require_nonempty_string(
                item.get("acceptance"), f"{debt_id}.acceptance"
            )
            paths = item.get("paths")
            if not isinstance(paths, list) or not paths:
                raise ProductionCompatibilityError(
                    f"{debt_id}.paths must be a non-empty list"
                )

    rules = _require_object_list(payload.get("source_contract_rules"), "rules")
    for rule in rules:
        finding = _evaluate_source_rule(root, rule)
        if finding is None:
            continue
        if finding.severity == "blocker":
            blockers.append(finding)
        else:
            warnings.append(finding)

    report_payload = {
        "schema_version": SCHEMA_VERSION,
        "live_trading_allowed": live_trading_allowed,
        "blockers": [asdict(item) for item in blockers],
        "warnings": [asdict(item) for item in warnings],
        "debt_item_count": len(debt_ids),
        "epic_count": len(epics),
    }
    report_hash = hashlib.sha256(_canonical_json(report_payload)).hexdigest()
    return ProductionCompatibilityReport(
        schema_version=SCHEMA_VERSION,
        ready=not blockers,
        live_trading_allowed=live_trading_allowed,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        debt_item_count=len(debt_ids),
        epic_count=len(epics),
        report_sha256=report_hash,
    )


def _evaluate_source_rule(
    root: Path, rule: dict[str, Any]
) -> CompatibilityFinding | None:
    rule_id = _require_nonempty_string(rule.get("id"), "rule.id")
    relative_path = _require_nonempty_string(rule.get("path"), f"{rule_id}.path")
    severity = _require_nonempty_string(
        rule.get("severity"), f"{rule_id}.severity"
    )
    if severity not in {"blocker", "warning"}:
        raise ProductionCompatibilityError(
            f"{rule_id}.severity must be blocker or warning"
        )
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ProductionCompatibilityError(
            f"source rule escapes repository: {relative_path}"
        ) from exc
    if not path.is_file():
        return CompatibilityFinding(
            rule_id,
            "blocker",
            relative_path,
            "Required source path is missing.",
        )

    text = path.read_text(encoding="utf-8")
    required = rule.get("required_substrings", [])
    forbidden = rule.get("forbidden_substrings", [])
    if not isinstance(required, list) or not isinstance(forbidden, list):
        raise ProductionCompatibilityError(
            f"{rule_id} substring lists must be arrays"
        )
    missing = [item for item in required if isinstance(item, str) and item not in text]
    present = [item for item in forbidden if isinstance(item, str) and item in text]
    if not missing and not present:
        return None
    details: list[str] = []
    if missing:
        details.append(f"missing required contract pins: {missing}")
    if present:
        details.append(f"contains stale or forbidden contract pins: {present}")
    return CompatibilityFinding(rule_id, severity, relative_path, "; ".join(details))


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionCompatibilityError(
            f"invalid production debt manifest: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ProductionCompatibilityError("production debt manifest must be an object")
    return payload


def _require_object_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ProductionCompatibilityError(f"{label} must be an array of objects")
    return value


def _require_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProductionCompatibilityError(f"{label} must be a non-empty string")
    return value.strip()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


__all__ = [
    "SCHEMA_VERSION",
    "CompatibilityFinding",
    "ProductionCompatibilityError",
    "ProductionCompatibilityReport",
    "evaluate_production_compatibility",
]
