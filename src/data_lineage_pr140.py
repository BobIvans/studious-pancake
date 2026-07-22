"""PR-140 data-lineage and generated-artifact quarantine helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import csv
import hashlib
import json
from pathlib import Path
import re

PR140_SCHEMA_VERSION = "pr140.data-lineage.v1"
PR140_POLICY_SCHEMA_VERSION = "pr140.data-lineage-policy.v1"

PR140_FORBIDDEN_ROOT_ARTIFACTS: tuple[str, ...] = (
    "ai_training_data.csv",
    "trade_history.csv",
    "bot_health.json",
    "helius-sanctum-lst-webhook.json",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PR140SourceKind(str, Enum):
    SYNTHETIC = "synthetic"
    RECORDED = "recorded"
    LIVE = "live"


class PR140LineageError(ValueError):
    """Raised when lineage or artifact quarantine evidence is invalid."""


@dataclass(frozen=True, slots=True)
class PR140DatasetLineage:
    artifact_path: str
    artifact_sha256: str
    source_kind: PR140SourceKind
    synthetic: bool
    exclude_from_financial_performance: bool
    finalized_settlement_evidence_sha256: str | None = None
    generator_version: str | None = None
    seed: str | None = None
    source: str | None = None
    time_range: tuple[str, str] | None = None
    contract_pins: tuple[str, ...] = ()
    config_pins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _non_empty(self.artifact_path, "artifact_path")
        _sha256(self.artifact_sha256, "artifact_sha256")
        if type(self.synthetic) is not bool:
            raise PR140LineageError("synthetic must be boolean")
        if type(self.exclude_from_financial_performance) is not bool:
            raise PR140LineageError(
                "exclude_from_financial_performance must be boolean"
            )
        if self.finalized_settlement_evidence_sha256 is not None:
            _sha256(
                self.finalized_settlement_evidence_sha256,
                "finalized_settlement_evidence_sha256",
            )
        if self.source_kind is PR140SourceKind.SYNTHETIC:
            if not self.synthetic or not self.exclude_from_financial_performance:
                raise PR140LineageError(
                    "synthetic data must be labeled and excluded from performance"
                )
            if not self.generator_version or not self.seed:
                raise PR140LineageError("synthetic data requires generator and seed")
        else:
            if self.synthetic:
                raise PR140LineageError("recorded/live data cannot be synthetic")
            if not self.source or self.time_range is None:
                raise PR140LineageError("recorded/live data requires source/time range")
            if not self.contract_pins or not self.config_pins:
                raise PR140LineageError("recorded/live data requires pins")

    @property
    def eligible_for_financial_performance(self) -> bool:
        return (
            self.source_kind is not PR140SourceKind.SYNTHETIC
            and not self.exclude_from_financial_performance
            and self.finalized_settlement_evidence_sha256 is not None
        )


def forbidden_root_artifacts(repo_root: str | Path) -> tuple[str, ...]:
    root = Path(repo_root)
    return tuple(
        path for path in PR140_FORBIDDEN_ROOT_ARTIFACTS if (root / path).exists()
    )


def assert_no_forbidden_root_artifacts(repo_root: str | Path) -> None:
    found = forbidden_root_artifacts(repo_root)
    if found:
        raise PR140LineageError(f"forbidden generated artifacts remain: {found}")


def load_pr140_policy(path: str | Path) -> Mapping[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != PR140_POLICY_SCHEMA_VERSION:
        raise PR140LineageError("unsupported PR-140 policy schema")
    artifacts = payload.get("forbidden_tracked_root_artifacts")
    if not isinstance(artifacts, list):
        raise PR140LineageError("forbidden artifacts must be a list")
    listed = tuple(item.get("path") for item in artifacts if isinstance(item, Mapping))
    if set(listed) != set(PR140_FORBIDDEN_ROOT_ARTIFACTS):
        raise PR140LineageError("policy and code disagree on forbidden artifacts")
    return payload


def validate_csv_text_shape(csv_text: str) -> int:
    rows = list(csv.reader(csv_text.splitlines()))
    if not rows:
        raise PR140LineageError("CSV must include a header")
    width = len(rows[0])
    for index, row in enumerate(rows[1:], start=1):
        if len(row) != width:
            raise PR140LineageError(
                f"CSV row {index} has {len(row)} columns; expected {width}"
            )
    return len(rows) - 1


def validate_actual_fields(
    *,
    lineage: PR140DatasetLineage,
    row: Mapping[str, object],
) -> None:
    has_actual = any(key.startswith("actual_") for key in row)
    if not has_actual:
        return
    if lineage.source_kind is PR140SourceKind.SYNTHETIC:
        if not lineage.exclude_from_financial_performance:
            raise PR140LineageError("synthetic actual fields must be excluded")
        return
    if lineage.finalized_settlement_evidence_sha256 is None:
        raise PR140LineageError("actual fields require finalized settlement evidence")


def artifact_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _non_empty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PR140LineageError(f"{name} must be a non-empty string")
    return value


def _sha256(value: object, name: str) -> str:
    checked = _non_empty(value, name).lower()
    if not _SHA256_RE.fullmatch(checked):
        raise PR140LineageError(f"{name} must be a SHA-256 hex digest")
    return checked
