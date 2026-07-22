"""Fail-closed production-debt inventory and external-review evaluator."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from importlib import resources
import hashlib
import json
from pathlib import Path
import tomllib
from typing import Any
from urllib.parse import urlparse

from src.capabilities import CapabilityMatrix
from src.external_contracts.registry import ExternalContractRegistry

INVENTORY_SCHEMA = "production-readiness.debt-inventory.v1"
REPORT_SCHEMA = "production-readiness.debt-report.v1"
EXTERNAL_REVIEW_SCHEMA = "production-readiness.external-review-manifest.v1"


class DebtStatus(StrEnum):
    IMPLEMENTATION_PENDING = "implementation-pending"
    EVIDENCE_PENDING = "evidence-pending"
    QUARANTINED = "quarantined"
    BLOCKED_BY_DESIGN = "blocked-by-design"
    REVIEW_REQUIRED = "review-required"
    RESOLVED = "resolved"


class ProductionDebtError(ValueError):
    """Raised when reviewed debt or external-review data is malformed."""


@dataclass(frozen=True, slots=True)
class DebtBatch:
    id: str
    title: str
    objective: str
    item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DebtItem:
    id: str
    batch: str
    severity: str
    status: str
    title: str
    surface: str
    blocks_paper: bool
    blocks_live: bool
    required_actions: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    observed_contract_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProductionDebtInventory:
    schema_version: str
    reviewed_at: str
    batches: tuple[DebtBatch, ...]
    items: tuple[DebtItem, ...]

    @classmethod
    def load_default(cls) -> "ProductionDebtInventory":
        path = resources.files("src.resources").joinpath("production_debt.json")
        return cls.from_payload(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_payload(cls, payload: Any) -> "ProductionDebtInventory":
        if not isinstance(payload, dict) or payload.get("schema_version") != INVENTORY_SCHEMA:
            raise ProductionDebtError("unsupported production-debt inventory")
        raw_batches = payload.get("batches")
        raw_items = payload.get("items")
        if not isinstance(raw_batches, list) or not isinstance(raw_items, list):
            raise ProductionDebtError("batches and items must be arrays")
        inventory = cls(
            INVENTORY_SCHEMA,
            _text(payload, "reviewed_at"),
            tuple(
                DebtBatch(
                    _text(row, "id"),
                    _text(row, "title"),
                    _text(row, "objective"),
                    _strings(row, "item_ids"),
                )
                for row in raw_batches
            ),
            tuple(
                DebtItem(
                    _text(row, "id"),
                    _text(row, "batch"),
                    _text(row, "severity"),
                    _text(row, "status"),
                    _text(row, "title"),
                    _text(row, "surface"),
                    _boolean(row, "blocks_paper"),
                    _boolean(row, "blocks_live"),
                    _strings(row, "required_actions"),
                    _strings(row, "evidence_refs"),
                    _optional_text(row, "observed_contract_id"),
                )
                for row in raw_items
            ),
        )
        inventory.validate()
        return inventory

    def validate(self) -> None:
        batches = {batch.id: batch for batch in self.batches}
        items = {item.id: item for item in self.items}
        if len(batches) != len(self.batches) or len(items) != len(self.items):
            raise ProductionDebtError("batch and item ids must be unique")
        for item in self.items:
            if item.batch not in batches or not item.required_actions or not item.evidence_refs:
                raise ProductionDebtError(f"invalid debt item: {item.id}")
            if item.severity not in {"P0", "P1", "P2"}:
                raise ProductionDebtError(f"invalid severity: {item.id}")
        flattened = [item_id for batch in self.batches for item_id in batch.item_ids]
        if len(flattened) != len(set(flattened)) or set(flattened) != set(items):
            raise ProductionDebtError("every debt item must appear in exactly one batch")
        if any(items[item_id].batch != batch.id for batch in self.batches for item_id in batch.item_ids):
            raise ProductionDebtError("cross-batch item")


@dataclass(frozen=True, slots=True)
class ProductionDebtReport:
    inventory_schema_version: str
    schema_version: str
    production_ready: bool
    paper_ready: bool
    live_ready: bool
    blockers: tuple[dict[str, Any], ...]
    consistency_errors: tuple[str, ...]
    observed: dict[str, Any]
    batches: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_production_debt(
    *,
    repo_root: str | Path | None = None,
    inventory: ProductionDebtInventory | None = None,
    capability_matrix: CapabilityMatrix | None = None,
    external_registry: ExternalContractRegistry | None = None,
) -> ProductionDebtReport:
    root = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[1]
    reviewed = inventory or ProductionDebtInventory.load_default()
    matrix = capability_matrix or CapabilityMatrix.load_default()
    registry = external_registry or ExternalContractRegistry.load_default()
    pyproject = root / "pyproject.toml"
    excludes = _package_excludes(pyproject)
    parity = _source_wheel_parity(root, excludes, pyproject.is_file())
    kamino_count = _kamino_count(root)
    contracts = _contract_facts(registry)

    observed = {
        "product_state": matrix.product_state,
        "live_mode_available": bool(matrix.runtime_modes["live"].get("available")),
        "package_metadata_available": pyproject.is_file(),
        "package_excludes": list(excludes),
        "source_wheel_parity": parity,
        "kamino_supported_combinations": kamino_count,
        "external_contracts": contracts,
        "quarantined_components": sorted(c.id for c in matrix.components if c.quarantined),
    }
    mandatory = {
        "runtime.product-state",
        "runtime.live-entrypoint",
        "packaging.source-wheel-parity",
        "lending.kamino-supported-combinations",
    }
    item_ids = {item.id for item in reviewed.items}
    errors = [] if mandatory <= item_ids else ["missing mandatory debt items"]
    errors.extend(
        f"missing external review: {item.observed_contract_id}"
        for item in reviewed.items
        if item.observed_contract_id and item.observed_contract_id not in contracts
    )

    blockers = tuple(
        {
            "id": item.id,
            "batch": item.batch,
            "severity": item.severity,
            "status": item.status,
            "title": item.title,
            "surface": item.surface,
            "blocks_paper": item.blocks_paper,
            "blocks_live": item.blocks_live,
            "observed_reason": _reason(item, matrix, parity, excludes, kamino_count, contracts),
            "required_actions": list(item.required_actions),
            "evidence_refs": list(item.evidence_refs),
        }
        for item in reviewed.items
        if item.status != "resolved"
        or _reason(item, matrix, parity, excludes, kamino_count, contracts) is not None
    )
    paper_ready = not errors and not any(row["blocks_paper"] for row in blockers)
    live_ready = not errors and not any(row["blocks_live"] for row in blockers)
    production_ready = (
        paper_ready
        and live_ready
        and matrix.product_state == "production-ready"
        and observed["live_mode_available"]
    )
    batches = tuple(
        {
            "id": batch.id,
            "title": batch.title,
            "objective": batch.objective,
            "open_items": sum(row["batch"] == batch.id for row in blockers),
            "p0_items": sum(
                row["batch"] == batch.id and row["severity"] == "P0" for row in blockers
            ),
        }
        for batch in reviewed.batches
    )
    return ProductionDebtReport(
        reviewed.schema_version,
        REPORT_SCHEMA,
        production_ready,
        paper_ready,
        live_ready,
        blockers,
        tuple(errors),
        observed,
        batches,
    )


def _contract_facts(registry: ExternalContractRegistry) -> dict[str, dict[str, Any]]:
    facts = {
        c.id: {
            "provider": c.provider,
            "status": c.status.value,
            "promotion_state": c.promotion_state.value,
            "execution_allowed": c.execution_allowed,
            "source": "canonical-external-contract-registry",
        }
        for c in registry.contracts
    }
    root = Path(str(resources.files("src.resources"))).resolve()
    payload = json.loads((root / "production_external_contracts.json").read_text(encoding="utf-8"))
    if payload.get("schema_version") != EXTERNAL_REVIEW_SCHEMA:
        raise ProductionDebtError("unsupported external-review manifest")
    seen: set[str] = set()
    for row in payload.get("contracts", []):
        contract_id = _text(row, "id")
        if contract_id in seen or _boolean(row, "execution_allowed"):
            raise ProductionDebtError("review manifest ids must be unique and execution-blocked")
        seen.add(contract_id)
        snapshot = (root / _text(row, "snapshot_path")).resolve()
        try:
            snapshot.relative_to(root)
        except ValueError as exc:
            raise ProductionDebtError("external snapshot escapes resource root") from exc
        if hashlib.sha256(snapshot.read_bytes()).hexdigest() != _text(row, "snapshot_sha256"):
            raise ProductionDebtError(f"external snapshot drift: {contract_id}")
        sources = _strings(row, "official_sources")
        if any(urlparse(url).scheme != "https" for url in sources):
            raise ProductionDebtError(f"non-HTTPS official source: {contract_id}")
        facts[contract_id] = {
            "provider": _text(row, "provider"),
            "status": _text(row, "review_state"),
            "promotion_state": "review-only-execution-blocked",
            "execution_allowed": False,
            "source": "production-external-review-manifest",
        }
    return dict(sorted(facts.items()))


def _reason(
    item: DebtItem,
    matrix: CapabilityMatrix,
    parity: bool,
    excludes: tuple[str, ...],
    kamino_count: int,
    contracts: dict[str, dict[str, Any]],
) -> str:
    if item.id == "runtime.product-state":
        return f"product_state={matrix.product_state}"
    if item.id == "runtime.live-entrypoint":
        return f"runtime_modes.live.available={bool(matrix.runtime_modes['live'].get('available'))}"
    if item.id == "packaging.source-wheel-parity" and not parity:
        return "source package excludes ingest/sender surfaces" if excludes else "installed wheel lacks safe ingest/sender surfaces"
    if item.id == "lending.kamino-supported-combinations" and not kamino_count:
        return "kamino supported combinations registry is empty"
    if item.observed_contract_id:
        contract = contracts.get(item.observed_contract_id)
        if contract is None:
            return f"missing contract={item.observed_contract_id}"
        if not contract["execution_allowed"]:
            return (
                f"contract={item.observed_contract_id};status={contract['status']};"
                f"promotion={contract['promotion_state']};execution_allowed=false"
            )
    return "inventory-not-resolved"


def _package_excludes(path: Path) -> tuple[str, ...]:
    if not path.is_file():
        return ()
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    values = payload["tool"]["setuptools"]["packages"]["find"].get("exclude", [])
    return tuple(str(value) for value in values)


def _source_wheel_parity(root: Path, excludes: tuple[str, ...], metadata: bool) -> bool:
    if metadata:
        return not any(value in excludes for value in ("src.ingest*", "src.execution.senders*"))
    return (root / "src" / "ingest").is_dir() and (root / "src" / "execution" / "senders").is_dir()


def _kamino_count(root: Path) -> int:
    path = root / "src" / "resources" / "kamino_supported_combinations.json"
    if not path.is_file():
        path = Path(str(resources.files("src.resources"))).resolve() / path.name
    combinations = json.loads(path.read_text(encoding="utf-8")).get("combinations")
    if not isinstance(combinations, list):
        raise ProductionDebtError("Kamino combinations must be an array")
    return len(combinations)


def _text(row: Any, key: str) -> str:
    if not isinstance(row, dict):
        raise ProductionDebtError("entries must be objects")
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProductionDebtError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_text(row: dict[str, Any], key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ProductionDebtError(f"{key} must be null or non-empty string")
    return value.strip()


def _strings(row: dict[str, Any], key: str) -> tuple[str, ...]:
    value = row.get(key)
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise ProductionDebtError(f"{key} must contain non-empty strings")
    return tuple(v.strip() for v in value)


def _boolean(row: dict[str, Any], key: str) -> bool:
    value = row.get(key)
    if type(value) is not bool:
        raise ProductionDebtError(f"{key} must be boolean")
    return value