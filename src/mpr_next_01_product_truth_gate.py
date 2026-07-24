"""MPR-NEXT-01 product-truth, debt-closure and release-hygiene gate."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping

SCHEMA_VERSION = "mpr-next-01.product-truth-ci-release-hygiene.v1"
CLOSURE_MAP_SCHEMA = "mpr-next-01.production-debt-closure-map.v1"
REQUIRED_GATE_IDS = (
    "MPR-25",
    "MPR-26",
    "MPR-27",
    "MPR-28",
    "MPR-29",
    "MPR-30",
    "MPR-31",
    "PR-225",
    "PR-226",
    "PR-228",
)
PRODUCT_CONTRACT_PATHS = (
    "src/resources/product_contract_pr195.json",
    "config/product_contract_pr195.json",
)
FORBIDDEN_RELEASE_ARTIFACTS = (
    "logs/pm2-out.log",
    "logs/bot-start.log",
    "pr190-diagnostics.txt",
)
TARGET_WORKFLOWS = (
    ".github/workflows/mpr31-final-promotion-gate.yml",
    ".github/workflows/pr190-diagnostics.yml",
)
SUPPORTED_PYTHON_VERSION = "3.13"
_ACTION_REF = re.compile(r"uses:\s*[^@\s]+@([A-Za-z0-9_.\-/]+)")


@dataclass(frozen=True, slots=True)
class GateResult:
    accepted: bool
    blockers: tuple[str, ...]
    observed: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "accepted": self.accepted,
            "blockers": list(self.blockers),
            "observed": dict(self.observed),
            "live_enabled": False,
            "production_ready": False,
        }


def evaluate_mpr_next_01(root: str | Path = ".") -> GateResult:
    repo = Path(root)
    sections = {
        "closure_map": _closure_map(repo),
        "product_contracts": _product_contracts(repo),
        "release_hygiene": _release_hygiene(repo),
        "workflows": _workflows(repo),
    }
    blockers = [
        f"{section}:{blocker}"
        for section, payload in sections.items()
        for blocker in payload["blockers"]
    ]
    return GateResult(not blockers, tuple(blockers), sections)


def _closure_map(repo: Path) -> dict[str, Any]:
    path = repo / "src/resources/production_debt_closure_map.json"
    if not path.is_file():
        return {"present": False, "gate_ids": [], "blockers": ["missing"]}
    payload = _json(path)
    blockers: list[str] = []
    if payload.get("schema_version") != CLOSURE_MAP_SCHEMA:
        blockers.append("schema-mismatch")
    if payload.get("live_enabled") is not False or payload.get("production_ready") is not False:
        blockers.append("must-not-enable-live-or-production")
    policy = payload.get("policy")
    if not isinstance(policy, Mapping):
        blockers.append("policy-not-object")
        policy = {}
    if not policy.get("materialized_runtime_evidence_required"):
        blockers.append("missing-materialized-evidence-policy")
    if not policy.get("offline_validators_do_not_close_blockers"):
        blockers.append("missing-offline-validator-policy")
    gates = payload.get("gates")
    if not isinstance(gates, list):
        return {"present": True, "gate_ids": [], "blockers": blockers + ["gates-not-array"]}
    gate_ids: list[str] = []
    for row in gates:
        if not isinstance(row, Mapping):
            blockers.append("gate-row-not-object")
            continue
        gate_id = str(row.get("gate_id", "")).strip()
        gate_ids.append(gate_id)
        if gate_id not in REQUIRED_GATE_IDS:
            blockers.append(f"unexpected-gate:{gate_id}")
        for key in ("can_close_blocker_ids", "required_evidence"):
            values = row.get(key)
            if not isinstance(values, list) or not values:
                blockers.append(f"{gate_id}:{key}-invalid")
            elif any(not isinstance(value, str) or not value.strip() for value in values):
                blockers.append(f"{gate_id}:{key}-invalid")
        if row.get("status") == "implemented-offline-validator":
            module_path = row.get("module_path")
            if not isinstance(module_path, str) or not module_path:
                blockers.append(f"{gate_id}:module-path-missing")
    missing = sorted(set(REQUIRED_GATE_IDS) - set(gate_ids))
    duplicates = sorted({gate_id for gate_id in gate_ids if gate_ids.count(gate_id) > 1})
    blockers.extend(f"missing-gate:{gate_id}" for gate_id in missing)
    blockers.extend(f"duplicate-gate:{gate_id}" for gate_id in duplicates)
    return {
        "present": True,
        "gate_ids": sorted(gate_ids),
        "required_gate_ids": list(REQUIRED_GATE_IDS),
        "blockers": blockers,
    }


def _product_contracts(repo: Path) -> dict[str, Any]:
    blockers: list[str] = []
    paths: dict[str, list[str]] = {}
    for rel in PRODUCT_CONTRACT_PATHS:
        path = repo / rel
        if not path.is_file():
            blockers.append(f"{rel}:missing")
            continue
        text = path.read_text(encoding="utf-8")
        if "/swap/v1" in text:
            blockers.append(f"{rel}:contains-swap-v1")
        jupiter = _json(path).get("endpoints", {}).get("jupiter", {})
        contract_paths = list(jupiter.get("paths", ())) if isinstance(jupiter, Mapping) else []
        paths[rel] = contract_paths
        if "/swap/v2/build" not in contract_paths:
            blockers.append(f"{rel}:missing-swap-v2-build")
    return {"paths": paths, "blockers": blockers}


def _release_hygiene(repo: Path) -> dict[str, Any]:
    present = [rel for rel in FORBIDDEN_RELEASE_ARTIFACTS if (repo / rel).exists()]
    return {
        "forbidden_artifacts": list(FORBIDDEN_RELEASE_ARTIFACTS),
        "present_forbidden_artifacts": present,
        "blockers": [f"committed-generated-artifact:{rel}" for rel in present],
    }


def _workflows(repo: Path) -> dict[str, Any]:
    blockers: list[str] = []
    python_versions: dict[str, list[str]] = {}
    for rel in TARGET_WORKFLOWS:
        path = repo / rel
        if not path.is_file():
            blockers.append(f"{rel}:missing")
            continue
        text = path.read_text(encoding="utf-8")
        versions = re.findall(r"python-version:\s*['\"]?([^'\"\n]+)", text)
        python_versions[rel] = versions
        if any(version.strip() != SUPPORTED_PYTHON_VERSION for version in versions):
            blockers.append(f"{rel}:python-version-drift")
        if "contents: write" in text or re.search(r"\bgit\s+push\b", text):
            blockers.append(f"{rel}:branch-writing-diagnostics")
        not_pinned = [ref for ref in _ACTION_REF.findall(text) if not re.fullmatch(r"[0-9a-f]{40}", ref)]
        if not_pinned:
            blockers.append(f"{rel}:unpinned-action")
    return {
        "supported_python_version": SUPPORTED_PYTHON_VERSION,
        "checked_workflows": list(TARGET_WORKFLOWS),
        "python_versions": python_versions,
        "blockers": blockers,
    }


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = [
    "CLOSURE_MAP_SCHEMA",
    "PRODUCT_CONTRACT_PATHS",
    "REQUIRED_GATE_IDS",
    "SCHEMA_VERSION",
    "evaluate_mpr_next_01",
]
