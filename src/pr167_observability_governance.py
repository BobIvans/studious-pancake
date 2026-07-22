"""PR-167 observability, evidence lifecycle and data-governance gate.

This module is deliberately side-effect free. It does not write databases, emit
metrics, upload evidence, call object stores, or change runtime behaviour. It
models the governance contracts needed before long soak or sustained production
operation can rely on telemetry/evidence without unbounded growth, silent
correction, premature purge, or unsafe metric cardinality.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum, StrEnum
import hashlib
import json
import re
from typing import Any

PR167_GOVERNANCE_SCHEMA = "pr167.observability-evidence-governance.v1"
PR167_GOVERNANCE_RESULT_SCHEMA = "pr167.observability-evidence-governance-result.v1"
LOCAL_INLINE_EVIDENCE_LIMIT_BYTES = 16_384

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_.:-]*$")

FORBIDDEN_METRIC_LABELS = frozenset(
    {
        "attempt_id",
        "logical_opportunity_id",
        "opportunity_id",
        "transaction_signature",
        "tx_signature",
        "signature",
        "message_hash",
        "request_id",
        "provider_request_id",
        "wallet",
        "wallet_address",
        "raw_url",
        "url",
        "exception",
        "exception_text",
        "traceback",
    }
)

REQUIRED_SLO_HISTOGRAMS = frozenset(
    {
        "stage_duration_seconds",
        "provider_latency_seconds",
        "rpc_latency_seconds",
        "queue_wait_seconds",
        "db_commit_latency_seconds",
        "quote_age_seconds",
        "simulation_duration_seconds",
        "reconciliation_latency_seconds",
        "alert_delivery_latency_seconds",
        "backup_restore_seconds",
    }
)


class PR167GovernanceError(ValueError):
    """Raised when PR-167 governance evidence is malformed."""


class DataClassification(StrEnum):
    PUBLIC_CHAIN = "public-chain-data"
    OPERATIONAL_METADATA = "operational-metadata"
    SENSITIVE_TOPOLOGY = "sensitive-wallet-account-topology"
    CONFIDENTIAL_PROVIDER = "confidential-provider-account-data"
    SECRET = "secret"
    IMMUTABLE_AUDIT = "immutable-audit"
    TEMPORARY_DEBUG = "temporary-debug"
    PERSONAL_OPERATOR = "personal-operator-data"


class RetentionClass(StrEnum):
    EPHEMERAL = "ephemeral"
    OPERATIONAL = "operational"
    FINANCIAL_AUDIT = "financial-audit"
    SECURITY_AUDIT = "security-audit"
    LEGAL_HOLD = "legal-hold"
    DELETE_ALLOWED = "delete-allowed"


class StorageTier(StrEnum):
    HOT_DB = "hot-db"
    WARM_ARCHIVE = "warm-archive"
    IMMUTABLE_OBJECT = "immutable-object"
    DELETED_WITH_MANIFEST = "deleted-with-manifest"


class EvidenceState(StrEnum):
    CURRENT = "current"
    SUPERSEDED = "superseded"
    CORRECTED = "corrected"
    REPLACEMENT = "replacement"


class BudgetState(StrEnum):
    OK = "ok"
    SOFT_CAP_EXCEEDED = "soft-cap-exceeded"
    HARD_CAP_EXCEEDED = "hard-cap-exceeded"


class GovernanceState(StrEnum):
    BLOCKED = "blocked"
    READY_FOR_MANUAL_REVIEW = "ready-for-manual-review"


class MetricKind(StrEnum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


class ManifestAction(StrEnum):
    ARCHIVE = "archive"
    DELETE = "delete"
    EXPORT = "export"


@dataclass(frozen=True, slots=True)
class DataFieldPolicy:
    """Classification and retention contract for one durable field."""

    field_path: str
    classification: DataClassification
    retention_class: RetentionClass
    hot_retention_days: int
    warm_archive_days: int
    immutable_retention_days: int
    deletion_allowed: bool
    legal_hold: bool = False

    def __post_init__(self) -> None:
        _require_name(self.field_path, "field_path")
        _require_non_negative_int(self.hot_retention_days, "hot_retention_days")
        _require_non_negative_int(self.warm_archive_days, "warm_archive_days")
        _require_non_negative_int(
            self.immutable_retention_days,
            "immutable_retention_days",
        )
        _require_bool(self.deletion_allowed, "deletion_allowed")
        _require_bool(self.legal_hold, "legal_hold")
        if self.classification == DataClassification.SECRET:
            raise PR167GovernanceError("secret fields must not be retained as evidence")
        if self.retention_class in {
            RetentionClass.FINANCIAL_AUDIT,
            RetentionClass.SECURITY_AUDIT,
            RetentionClass.LEGAL_HOLD,
        } and self.deletion_allowed:
            raise PR167GovernanceError(
                f"{self.field_path}: audit/legal retention cannot be deletion_allowed"
            )
        if self.legal_hold and self.deletion_allowed:
            raise PR167GovernanceError(
                f"{self.field_path}: legal hold forbids deletion"
            )


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """Complete retention policy for durable observability/evidence data."""

    fields: Sequence[DataFieldPolicy]
    minimum_financial_retention_days: int
    immutable_audit_retention_days: int
    backup_retention_days: int
    schema_version: str = PR167_GOVERNANCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PR167_GOVERNANCE_SCHEMA:
            raise PR167GovernanceError("unsupported retention schema")
        if not self.fields:
            raise PR167GovernanceError("retention policy must classify fields")
        _require_positive_int(
            self.minimum_financial_retention_days,
            "minimum_financial_retention_days",
        )
        _require_positive_int(
            self.immutable_audit_retention_days,
            "immutable_audit_retention_days",
        )
        _require_positive_int(self.backup_retention_days, "backup_retention_days")
        seen: set[str] = set()
        for item in self.fields:
            if item.field_path in seen:
                raise PR167GovernanceError(
                    f"duplicate field retention policy: {item.field_path}"
                )
            seen.add(item.field_path)
            if (
                item.retention_class == RetentionClass.FINANCIAL_AUDIT
                and item.immutable_retention_days
                < self.minimum_financial_retention_days
            ):
                raise PR167GovernanceError(
                    f"{item.field_path}: financial retention below minimum"
                )
            if (
                item.classification == DataClassification.IMMUTABLE_AUDIT
                and item.immutable_retention_days
                < self.immutable_audit_retention_days
            ):
                raise PR167GovernanceError(
                    f"{item.field_path}: immutable-audit retention below minimum"
                )


@dataclass(frozen=True, slots=True)
class StorageBudget:
    """Hard/soft storage budget for months-long operation."""

    lifecycle_db_hard_cap_bytes: int
    observability_db_hard_cap_bytes: int
    wal_hard_cap_bytes: int
    evidence_object_hard_cap_bytes_per_day: int
    logs_hard_cap_bytes_per_day: int
    metrics_series_hard_cap: int
    trace_events_hard_cap_per_minute: int
    soft_cap_ratio: float = 0.8

    def __post_init__(self) -> None:
        for field_name in (
            "lifecycle_db_hard_cap_bytes",
            "observability_db_hard_cap_bytes",
            "wal_hard_cap_bytes",
            "evidence_object_hard_cap_bytes_per_day",
            "logs_hard_cap_bytes_per_day",
            "metrics_series_hard_cap",
            "trace_events_hard_cap_per_minute",
        ):
            _require_positive_int(getattr(self, field_name), field_name)
        if not 0 < self.soft_cap_ratio < 1:
            raise PR167GovernanceError("soft_cap_ratio must be between 0 and 1")

    def evaluate(self, usage: StorageUsage) -> BudgetEvaluation:
        violations: list[str] = []
        warnings: list[str] = []
        for used_field, cap_field in (
            ("lifecycle_db_bytes", "lifecycle_db_hard_cap_bytes"),
            ("observability_db_bytes", "observability_db_hard_cap_bytes"),
            ("wal_bytes", "wal_hard_cap_bytes"),
            (
                "evidence_object_bytes_per_day",
                "evidence_object_hard_cap_bytes_per_day",
            ),
            ("logs_bytes_per_day", "logs_hard_cap_bytes_per_day"),
            ("metrics_series", "metrics_series_hard_cap"),
            ("trace_events_per_minute", "trace_events_hard_cap_per_minute"),
        ):
            used = getattr(usage, used_field)
            cap = getattr(self, cap_field)
            if used > cap:
                violations.append(f"{used_field}:hard-cap-exceeded")
            elif used >= int(cap * self.soft_cap_ratio):
                warnings.append(f"{used_field}:soft-cap-exceeded")
        return BudgetEvaluation(
            state=BudgetState.HARD_CAP_EXCEEDED
            if violations
            else (BudgetState.SOFT_CAP_EXCEEDED if warnings else BudgetState.OK),
            violations=tuple(violations),
            warnings=tuple(warnings),
        )


@dataclass(frozen=True, slots=True)
class StorageUsage:
    lifecycle_db_bytes: int
    observability_db_bytes: int
    wal_bytes: int
    evidence_object_bytes_per_day: int
    logs_bytes_per_day: int
    metrics_series: int
    trace_events_per_minute: int

    def __post_init__(self) -> None:
        for field_name in (
            "lifecycle_db_bytes",
            "observability_db_bytes",
            "wal_bytes",
            "evidence_object_bytes_per_day",
            "logs_bytes_per_day",
            "metrics_series",
            "trace_events_per_minute",
        ):
            _require_non_negative_int(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class BudgetEvaluation:
    state: BudgetState
    violations: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceObjectPolicy:
    """Tiering contract for evidence payloads."""

    content_addressed_uri: str
    payload_sha256: str
    encrypted: bool
    immutable_lock: bool
    local_cache_max_bytes: int
    verified_retrieval: bool

    def __post_init__(self) -> None:
        _require_non_empty(self.content_addressed_uri, "content_addressed_uri")
        object.__setattr__(
            self,
            "payload_sha256",
            _require_sha256(self.payload_sha256, "payload_sha256"),
        )
        _require_bool(self.encrypted, "encrypted")
        _require_bool(self.immutable_lock, "immutable_lock")
        _require_positive_int(self.local_cache_max_bytes, "local_cache_max_bytes")
        _require_bool(self.verified_retrieval, "verified_retrieval")
        if not self.encrypted:
            raise PR167GovernanceError("evidence object storage must be encrypted")
        if not self.verified_retrieval:
            raise PR167GovernanceError("evidence object retrieval must be verified")


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """Metadata for one evidence payload or object-store reference."""

    evidence_ref: str
    classification: DataClassification
    retention_class: RetentionClass
    digest_sha256: str
    size_bytes: int
    state: EvidenceState = EvidenceState.CURRENT
    local_payload_allowed: bool = False
    object_policy: EvidenceObjectPolicy | None = None
    related_attempt_ref: str | None = None

    def __post_init__(self) -> None:
        _require_name(self.evidence_ref, "evidence_ref")
        object.__setattr__(
            self,
            "digest_sha256",
            _require_sha256(self.digest_sha256, "digest_sha256"),
        )
        _require_non_negative_int(self.size_bytes, "size_bytes")
        _require_bool(self.local_payload_allowed, "local_payload_allowed")
        if self.classification == DataClassification.SECRET:
            raise PR167GovernanceError("secret payloads cannot be retained as evidence")
        if (
            self.size_bytes > LOCAL_INLINE_EVIDENCE_LIMIT_BYTES
            and self.object_policy is None
        ):
            raise PR167GovernanceError("large evidence requires object storage policy")
        if (
            self.classification
            in {
                DataClassification.SENSITIVE_TOPOLOGY,
                DataClassification.CONFIDENTIAL_PROVIDER,
                DataClassification.PERSONAL_OPERATOR,
            }
            and self.local_payload_allowed
        ):
            raise PR167GovernanceError(
                "sensitive/confidential evidence cannot keep local payload"
            )


@dataclass(frozen=True, slots=True)
class EvidenceCorrection:
    """Immutable supersession edge: original -> replacement."""

    original_ref: str
    correction_ref: str
    replacement_ref: str
    correction_reason: str
    signed_manifest_sha256: str

    def __post_init__(self) -> None:
        for field_name in ("original_ref", "correction_ref", "replacement_ref"):
            _require_name(getattr(self, field_name), field_name)
        if self.original_ref == self.replacement_ref:
            raise PR167GovernanceError("correction cannot replace evidence with itself")
        if self.correction_ref in {self.original_ref, self.replacement_ref}:
            raise PR167GovernanceError("correction record must be distinct evidence")
        _require_non_empty(self.correction_reason, "correction_reason")
        object.__setattr__(
            self,
            "signed_manifest_sha256",
            _require_sha256(self.signed_manifest_sha256, "signed_manifest_sha256"),
        )


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    name: str
    kind: MetricKind
    labels: tuple[str, ...]
    populated: bool = True

    def __post_init__(self) -> None:
        _require_metric_name(self.name, "metric.name")
        if not self.name.endswith(
            ("_total", "_seconds", "_bytes", "_ratio", "_count")
        ):
            raise PR167GovernanceError(
                f"metric {self.name!r} must use a stable unit suffix"
            )
        for label in self.labels:
            _require_metric_name(label, "metric.label")
            if _label_is_forbidden(label):
                raise PR167GovernanceError(f"metric label is high-cardinality: {label}")
        _require_bool(self.populated, "populated")


@dataclass(frozen=True, slots=True)
class MetricCardinalityPolicy:
    """Allowed bounded metric labels and maximum series estimate."""

    allowed_label_values: Mapping[str, Sequence[str]]
    max_estimated_series: int

    def __post_init__(self) -> None:
        _require_positive_int(self.max_estimated_series, "max_estimated_series")
        normalized: dict[str, tuple[str, ...]] = {}
        if not self.allowed_label_values:
            raise PR167GovernanceError("metric label policy cannot be empty")
        for label, values in self.allowed_label_values.items():
            _require_metric_name(label, "metric.label")
            if _label_is_forbidden(label):
                raise PR167GovernanceError(f"forbidden metric label: {label}")
            if not values:
                raise PR167GovernanceError(f"metric label {label} has no values")
            normalized[label] = tuple(str(value) for value in values)
        object.__setattr__(self, "allowed_label_values", normalized)

    def estimate_series(self, metrics: Sequence[MetricDefinition]) -> int:
        total = 0
        for metric in metrics:
            series = 1
            for label in metric.labels:
                values = self.allowed_label_values.get(label)
                if values is None:
                    raise PR167GovernanceError(
                        f"metric {metric.name} uses unapproved label {label}"
                    )
                series *= len(values)
            total += series
        return total

    def validate(self, metrics: Sequence[MetricDefinition]) -> MetricCardinalityResult:
        estimated = self.estimate_series(metrics)
        blockers: list[str] = []
        if estimated > self.max_estimated_series:
            blockers.append("metric-series-hard-cap-exceeded")
        return MetricCardinalityResult(
            estimated_series=estimated,
            max_series=self.max_estimated_series,
            blockers=tuple(blockers),
        )


@dataclass(frozen=True, slots=True)
class MetricCardinalityResult:
    estimated_series: int
    max_series: int
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SLOMetricSet:
    metrics: Sequence[MetricDefinition]

    def __post_init__(self) -> None:
        if not self.metrics:
            raise PR167GovernanceError("SLO metric set cannot be empty")
        names = {metric.name for metric in self.metrics}
        missing = sorted(REQUIRED_SLO_HISTOGRAMS.difference(names))
        if missing:
            raise PR167GovernanceError(
                "missing required SLO histograms: " + ", ".join(missing)
            )
        for metric in self.metrics:
            if metric.name in REQUIRED_SLO_HISTOGRAMS:
                if metric.kind != MetricKind.HISTOGRAM:
                    raise PR167GovernanceError(f"{metric.name} must be a histogram")
                if not metric.populated:
                    raise PR167GovernanceError(f"{metric.name} is not populated")


@dataclass(frozen=True, slots=True)
class WALCompactionPolicy:
    checkpoint_interval_seconds: int
    max_wal_bytes: int
    minimum_free_disk_bytes: int
    corruption_safe_archive: bool
    fail_closed_on_hard_cap: bool

    def __post_init__(self) -> None:
        _require_positive_int(
            self.checkpoint_interval_seconds,
            "checkpoint_interval_seconds",
        )
        _require_positive_int(self.max_wal_bytes, "max_wal_bytes")
        _require_positive_int(self.minimum_free_disk_bytes, "minimum_free_disk_bytes")
        _require_bool(self.corruption_safe_archive, "corruption_safe_archive")
        _require_bool(self.fail_closed_on_hard_cap, "fail_closed_on_hard_cap")
        if not self.corruption_safe_archive:
            raise PR167GovernanceError("WAL policy requires corruption-safe archive")
        if not self.fail_closed_on_hard_cap:
            raise PR167GovernanceError("WAL hard cap must fail closed")


@dataclass(frozen=True, slots=True)
class ArchiveDeleteManifest:
    action: ManifestAction
    evidence_refs: tuple[str, ...]
    requested_by: str
    reason: str
    created_at_ns: int
    signed_manifest_sha256: str
    approval_ref: str

    def __post_init__(self) -> None:
        if not self.evidence_refs:
            raise PR167GovernanceError("manifest requires evidence refs")
        for ref in self.evidence_refs:
            _require_name(ref, "evidence_ref")
        _require_name(self.requested_by, "requested_by")
        _require_non_empty(self.reason, "reason")
        _require_positive_int(self.created_at_ns, "created_at_ns")
        _require_name(self.approval_ref, "approval_ref")
        object.__setattr__(
            self,
            "signed_manifest_sha256",
            _require_sha256(self.signed_manifest_sha256, "signed_manifest_sha256"),
        )


@dataclass(frozen=True, slots=True)
class PR167GovernancePackage:
    retention_policy: RetentionPolicy
    storage_budget: StorageBudget
    current_usage: StorageUsage
    evidence_records: Sequence[EvidenceRecord]
    corrections: Sequence[EvidenceCorrection]
    metric_policy: MetricCardinalityPolicy
    metrics: Sequence[MetricDefinition]
    slo_metrics: SLOMetricSet
    wal_policy: WALCompactionPolicy
    archive_delete_manifests: Sequence[ArchiveDeleteManifest]
    cost_budget_present: bool
    access_audit_enabled: bool
    schema_version: str = PR167_GOVERNANCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PR167_GOVERNANCE_SCHEMA:
            raise PR167GovernanceError("unsupported PR-167 package schema")
        if not self.evidence_records:
            raise PR167GovernanceError("governance package requires evidence records")
        if not self.metrics:
            raise PR167GovernanceError("governance package requires metrics")
        _require_bool(self.cost_budget_present, "cost_budget_present")
        _require_bool(self.access_audit_enabled, "access_audit_enabled")
        _assert_unique_refs(self.evidence_records)
        build_authoritative_evidence_view(self.evidence_records, self.corrections)
        for manifest in self.archive_delete_manifests:
            validate_archive_delete_manifest(manifest, self.evidence_records)

    @property
    def package_sha256(self) -> str:
        return _sha256_payload(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class PR167GovernanceReadiness:
    state: GovernanceState
    ready_for_manual_review: bool
    runtime_live_enabled: bool
    write_path_can_purge_financial_evidence: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    package_sha256: str
    estimated_metric_series: int
    schema_version: str = PR167_GOVERNANCE_RESULT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_pr167_governance(
    package: PR167GovernancePackage,
) -> PR167GovernanceReadiness:
    blockers: list[str] = []
    warnings: list[str] = []

    budget = package.storage_budget.evaluate(package.current_usage)
    blockers.extend(budget.violations)
    warnings.extend(budget.warnings)

    metric_result = package.metric_policy.validate(package.metrics)
    blockers.extend(metric_result.blockers)

    if not package.cost_budget_present:
        blockers.append("observability-cost-budget-missing")
    if not package.access_audit_enabled:
        blockers.append("evidence-access-audit-disabled")

    financial_refs = {
        record.evidence_ref
        for record in package.evidence_records
        if record.retention_class == RetentionClass.FINANCIAL_AUDIT
    }
    for manifest in package.archive_delete_manifests:
        if manifest.action == ManifestAction.DELETE:
            overlap = financial_refs.intersection(manifest.evidence_refs)
            if overlap:
                blockers.append(
                    "financial-evidence-delete-requested:"
                    + ",".join(sorted(overlap))
                )

    unique_blockers = _dedupe(blockers)
    return PR167GovernanceReadiness(
        state=GovernanceState.READY_FOR_MANUAL_REVIEW
        if not unique_blockers
        else GovernanceState.BLOCKED,
        ready_for_manual_review=not unique_blockers,
        runtime_live_enabled=False,
        write_path_can_purge_financial_evidence=False,
        blockers=unique_blockers,
        warnings=_dedupe(warnings),
        package_sha256=package.package_sha256,
        estimated_metric_series=metric_result.estimated_series,
    )


def build_authoritative_evidence_view(
    records: Sequence[EvidenceRecord],
    corrections: Sequence[EvidenceCorrection],
) -> Mapping[str, str]:
    refs = {record.evidence_ref for record in records}
    view = {ref: ref for ref in refs}
    for correction in corrections:
        if correction.original_ref not in refs:
            raise PR167GovernanceError(
                f"correction original not found: {correction.original_ref}"
            )
        if correction.correction_ref not in refs:
            raise PR167GovernanceError(
                f"correction record not found: {correction.correction_ref}"
            )
        if correction.replacement_ref not in refs:
            raise PR167GovernanceError(
                f"correction replacement not found: {correction.replacement_ref}"
            )
        if view[correction.original_ref] != correction.original_ref:
            raise PR167GovernanceError(
                f"evidence has multiple corrections: {correction.original_ref}"
            )
        view[correction.original_ref] = correction.replacement_ref
    for original, replacement in view.items():
        if view.get(replacement) == original and original != replacement:
            raise PR167GovernanceError("evidence correction cycle detected")
    return view


def validate_archive_delete_manifest(
    manifest: ArchiveDeleteManifest,
    records: Sequence[EvidenceRecord],
) -> None:
    by_ref = {record.evidence_ref: record for record in records}
    missing = sorted(set(manifest.evidence_refs).difference(by_ref))
    if missing:
        raise PR167GovernanceError(
            "manifest references unknown evidence: " + ", ".join(missing)
        )
    if manifest.action == ManifestAction.DELETE:
        for ref in manifest.evidence_refs:
            record = by_ref[ref]
            if record.retention_class in {
                RetentionClass.FINANCIAL_AUDIT,
                RetentionClass.SECURITY_AUDIT,
                RetentionClass.LEGAL_HOLD,
            }:
                raise PR167GovernanceError(f"cannot delete audit/legal evidence: {ref}")


def _assert_unique_refs(records: Sequence[EvidenceRecord]) -> None:
    seen: set[str] = set()
    for record in records:
        if record.evidence_ref in seen:
            raise PR167GovernanceError(f"duplicate evidence ref: {record.evidence_ref}")
        seen.add(record.evidence_ref)


def _require_sha256(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise PR167GovernanceError(f"{field} must be a non-placeholder sha256")
    return lowered


def _require_name(value: str, field: str) -> None:
    if not isinstance(value, str) or not _NAME_RE.fullmatch(value):
        raise PR167GovernanceError(f"{field} must be a stable lowercase identifier")


def _require_metric_name(value: str, field: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"^[a-z][a-z0-9_]*$", value):
        raise PR167GovernanceError(f"{field} must be a metric-safe identifier")


def _require_non_empty(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PR167GovernanceError(f"{field} must be non-empty")


def _require_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PR167GovernanceError(f"{field} must be a positive integer")
    return value


def _require_non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PR167GovernanceError(f"{field} must be a non-negative integer")
    return value


def _require_bool(value: Any, field: str) -> None:
    if not isinstance(value, bool):
        raise PR167GovernanceError(f"{field} must be boolean")


def _label_is_forbidden(label: str) -> bool:
    return (
        label in FORBIDDEN_METRIC_LABELS
        or label.endswith("_id")
        or "hash" in label
        or "signature" in label
    )


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field.name: _jsonable(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    return value


def _stable_json(payload: Any) -> str:
    return json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


__all__ = [
    "ArchiveDeleteManifest",
    "BudgetEvaluation",
    "BudgetState",
    "DataClassification",
    "DataFieldPolicy",
    "EvidenceCorrection",
    "EvidenceObjectPolicy",
    "EvidenceRecord",
    "EvidenceState",
    "GovernanceState",
    "ManifestAction",
    "MetricCardinalityPolicy",
    "MetricCardinalityResult",
    "MetricDefinition",
    "MetricKind",
    "PR167GovernanceError",
    "PR167GovernancePackage",
    "PR167GovernanceReadiness",
    "PR167_GOVERNANCE_RESULT_SCHEMA",
    "PR167_GOVERNANCE_SCHEMA",
    "REQUIRED_SLO_HISTOGRAMS",
    "RetentionClass",
    "RetentionPolicy",
    "SLOMetricSet",
    "StorageBudget",
    "StorageTier",
    "StorageUsage",
    "WALCompactionPolicy",
    "build_authoritative_evidence_view",
    "evaluate_pr167_governance",
    "validate_archive_delete_manifest",
]
