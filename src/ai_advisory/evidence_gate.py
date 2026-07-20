"""PR-068 AI advisory-only model evidence gate.

The objects in this module are deliberately offline and transport neutral.  They
describe evidence for models that may advise humans or dashboards, but they
never grant authority to submit, block, size, or mutate trades.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Iterable, Literal

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA_VERSION = "pr068.ai-advisory-evidence.v1"


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _require_nonempty(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")


def _require_sha256(value: str, field: str) -> None:
    if not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase 64-character sha256")
    if value == "0" * 64:
        raise ValueError(f"{field} cannot be a placeholder digest")


def _require_timezone(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


class AdvisoryFailureCode(StrEnum):
    """Stable blocker identifiers emitted by the PR-068 gate."""

    SCHEMA_VERSION_UNSUPPORTED = "SCHEMA_VERSION_UNSUPPORTED"
    HUMAN_REVIEW_MISSING = "HUMAN_REVIEW_MISSING"
    MODEL_REGISTRY_EMPTY = "MODEL_REGISTRY_EMPTY"
    MODEL_REGISTRY_DUPLICATE = "MODEL_REGISTRY_DUPLICATE"
    MODEL_REGISTRY_ENTRY_INVALID = "MODEL_REGISTRY_ENTRY_INVALID"
    MODEL_NOT_IN_REGISTRY = "MODEL_NOT_IN_REGISTRY"
    MODEL_TRADING_AUTHORITY_ENABLED = "MODEL_TRADING_AUTHORITY_ENABLED"
    DATASET_HASH_MISMATCH = "DATASET_HASH_MISMATCH"
    TIME_SPLIT_EVALUATION_MISSING = "TIME_SPLIT_EVALUATION_MISSING"
    EVALUATION_SAMPLE_TOO_SMALL = "EVALUATION_SAMPLE_TOO_SMALL"
    EVALUATION_METRIC_BELOW_THRESHOLD = "EVALUATION_METRIC_BELOW_THRESHOLD"
    CALIBRATION_ERROR_TOO_HIGH = "CALIBRATION_ERROR_TOO_HIGH"
    LATENCY_TOO_HIGH = "LATENCY_TOO_HIGH"
    DRIFT_REPORT_MISSING = "DRIFT_REPORT_MISSING"
    FEATURE_DRIFT_TOO_HIGH = "FEATURE_DRIFT_TOO_HIGH"
    PREDICTION_DRIFT_TOO_HIGH = "PREDICTION_DRIFT_TOO_HIGH"
    MISSING_FEATURE_RATE_TOO_HIGH = "MISSING_FEATURE_RATE_TOO_HIGH"
    DRIFT_AUTODISABLE_MISSING = "DRIFT_AUTODISABLE_MISSING"
    AB_SHADOW_MISSING = "AB_SHADOW_MISSING"
    AB_SAMPLE_TOO_SMALL = "AB_SAMPLE_TOO_SMALL"
    AB_LIVE_DECISIONS_PRESENT = "AB_LIVE_DECISIONS_PRESENT"
    AB_AUTOMATIC_DISABLE_MISSING = "AB_AUTOMATIC_DISABLE_MISSING"
    AB_HUMAN_REVIEW_MISSING = "AB_HUMAN_REVIEW_MISSING"


class PromotionState(StrEnum):
    """Allowed model states for an advisory-only system."""

    DISABLED = "disabled"
    SHADOW_ONLY = "shadow-only"
    ADVISORY_DASHBOARD = "advisory-dashboard"


class EvaluationSplitKind(StrEnum):
    """Evaluation split contract used to avoid in-sample promotion evidence."""

    TIME_SPLIT = "time-split"
    WALK_FORWARD = "walk-forward"
    RANDOM = "random"
    IN_SAMPLE = "in-sample"


@dataclass(frozen=True, slots=True)
class ModelRegistryEntry:
    """Pinned identity for a model that may produce advisory signals only."""

    model_id: str
    provider: str
    model_version: str
    artifact_sha256: str
    prompt_template_sha256: str
    feature_schema_sha256: str
    training_dataset_sha256: str
    evaluation_dataset_sha256: str
    registered_at: datetime
    registered_by: str
    advisory_only: bool = True
    promotion_state: PromotionState = PromotionState.DISABLED
    trading_authority_enabled: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        for field, value in (
            ("model_id", self.model_id),
            ("provider", self.provider),
            ("model_version", self.model_version),
            ("registered_by", self.registered_by),
        ):
            _require_nonempty(value, field)
        for field, value in (
            ("artifact_sha256", self.artifact_sha256),
            ("prompt_template_sha256", self.prompt_template_sha256),
            ("feature_schema_sha256", self.feature_schema_sha256),
            ("training_dataset_sha256", self.training_dataset_sha256),
            ("evaluation_dataset_sha256", self.evaluation_dataset_sha256),
        ):
            _require_sha256(value, field)
        _require_timezone(self.registered_at, "registered_at")
        if not self.advisory_only or self.trading_authority_enabled:
            raise ValueError("model registry entries must be advisory-only")
        if self.promotion_state not in set(PromotionState):
            raise ValueError("unsupported promotion_state")


@dataclass(frozen=True, slots=True)
class ModelEvaluationReport:
    """Offline model evaluation evidence with deterministic split constraints."""

    model_id: str
    evaluation_id: str
    split_kind: EvaluationSplitKind
    train_window_end: datetime
    evaluation_window_start: datetime
    evaluation_window_end: datetime
    sample_count: int
    precision_at_threshold: float
    recall_at_threshold: float
    brier_score: float
    calibration_error: float
    p95_latency_ms: int
    evaluation_dataset_sha256: str
    report_sha256: str
    generated_at: datetime
    evaluator: str

    def __post_init__(self) -> None:
        for field, value in (
            ("model_id", self.model_id),
            ("evaluation_id", self.evaluation_id),
            ("evaluator", self.evaluator),
        ):
            _require_nonempty(value, field)
        for field, value in (
            ("evaluation_dataset_sha256", self.evaluation_dataset_sha256),
            ("report_sha256", self.report_sha256),
        ):
            _require_sha256(value, field)
        for field, value in (
            ("train_window_end", self.train_window_end),
            ("evaluation_window_start", self.evaluation_window_start),
            ("evaluation_window_end", self.evaluation_window_end),
            ("generated_at", self.generated_at),
        ):
            _require_timezone(value, field)
        if self.sample_count < 0:
            raise ValueError("sample_count cannot be negative")
        for field, value in (
            ("precision_at_threshold", self.precision_at_threshold),
            ("recall_at_threshold", self.recall_at_threshold),
            ("brier_score", self.brier_score),
            ("calibration_error", self.calibration_error),
        ):
            if value < 0:
                raise ValueError(f"{field} cannot be negative")
        if self.p95_latency_ms < 0:
            raise ValueError("p95_latency_ms cannot be negative")


@dataclass(frozen=True, slots=True)
class DriftMonitorReport:
    """Feature and prediction drift evidence for a registered advisory model."""

    model_id: str
    drift_id: str
    baseline_dataset_sha256: str
    observed_dataset_sha256: str
    feature_drift_score: float
    prediction_drift_score: float
    missing_feature_rate: float
    checked_at: datetime
    monitor: str
    automatic_disable_recorded: bool
    report_sha256: str

    def __post_init__(self) -> None:
        for field, value in (
            ("model_id", self.model_id),
            ("drift_id", self.drift_id),
            ("monitor", self.monitor),
        ):
            _require_nonempty(value, field)
        for field, value in (
            ("baseline_dataset_sha256", self.baseline_dataset_sha256),
            ("observed_dataset_sha256", self.observed_dataset_sha256),
            ("report_sha256", self.report_sha256),
        ):
            _require_sha256(value, field)
        _require_timezone(self.checked_at, "checked_at")
        for field, value in (
            ("feature_drift_score", self.feature_drift_score),
            ("prediction_drift_score", self.prediction_drift_score),
            ("missing_feature_rate", self.missing_feature_rate),
        ):
            if value < 0:
                raise ValueError(f"{field} cannot be negative")


@dataclass(frozen=True, slots=True)
class ShadowABReport:
    """A/B shadow evidence proving the model stayed advisory-only."""

    model_id: str
    experiment_id: str
    control_policy_id: str
    candidate_policy_id: str
    sample_count: int
    candidate_recommendations: int
    live_decisions_taken: int
    automatic_disable_recorded: bool
    human_reviewed: bool
    report_sha256: str
    observed_at: datetime
    reviewer: str

    def __post_init__(self) -> None:
        for field, value in (
            ("model_id", self.model_id),
            ("experiment_id", self.experiment_id),
            ("control_policy_id", self.control_policy_id),
            ("candidate_policy_id", self.candidate_policy_id),
            ("reviewer", self.reviewer),
        ):
            _require_nonempty(value, field)
        _require_sha256(self.report_sha256, "report_sha256")
        _require_timezone(self.observed_at, "observed_at")
        for field, value in (
            ("sample_count", self.sample_count),
            ("candidate_recommendations", self.candidate_recommendations),
            ("live_decisions_taken", self.live_decisions_taken),
        ):
            if value < 0:
                raise ValueError(f"{field} cannot be negative")


@dataclass(frozen=True, slots=True)
class AIAdvisoryEvidencePackage:
    """Complete PR-068 evidence envelope consumed by the readiness gate."""

    generated_at: datetime
    generated_by: str
    registry: tuple[ModelRegistryEntry, ...]
    evaluations: tuple[ModelEvaluationReport, ...]
    drift_reports: tuple[DriftMonitorReport, ...]
    ab_reports: tuple[ShadowABReport, ...]
    human_reviewed: bool
    reviewer: str
    schema_version: str = _SCHEMA_VERSION
    notes: str = ""

    def __post_init__(self) -> None:
        _require_timezone(self.generated_at, "generated_at")
        _require_nonempty(self.generated_by, "generated_by")
        if self.human_reviewed:
            _require_nonempty(self.reviewer, "reviewer")

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def evidence_sha256(self) -> str:
        return _sha256_json(self.canonical_payload())


@dataclass(frozen=True, slots=True)
class AIAdvisoryGatePolicy:
    """Thresholds for PR-068 advisory evidence readiness."""

    min_evaluation_samples: int = 250
    min_ab_samples: int = 250
    min_precision_at_threshold: float = 0.55
    min_recall_at_threshold: float = 0.20
    max_brier_score: float = 0.25
    max_calibration_error: float = 0.08
    max_p95_latency_ms: int = 750
    max_feature_drift_score: float = 0.10
    max_prediction_drift_score: float = 0.10
    max_missing_feature_rate: float = 0.01
    allowed_promotion_states: frozenset[PromotionState] = frozenset(
        {
            PromotionState.DISABLED,
            PromotionState.SHADOW_ONLY,
            PromotionState.ADVISORY_DASHBOARD,
        }
    )

    def __post_init__(self) -> None:
        if self.min_evaluation_samples <= 0 or self.min_ab_samples <= 0:
            raise ValueError("sample thresholds must be positive")


@dataclass(frozen=True, slots=True)
class AIAdvisoryReadinessResult:
    """Deterministic gate output.

    `ai_authority_enabled` is always false by construction.  Even a passing
    result only means the advisory evidence is review-ready.
    """

    schema_version: str
    state: Literal["advisory-evidence-ready", "blocked"]
    evidence_sha256: str
    evaluated_models: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    checks_evaluated: int
    ai_authority_enabled: bool = False
    trading_mutation_allowed: bool = False

    @property
    def ready(self) -> bool:
        return self.state == "advisory-evidence-ready" and not self.blockers

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class AIAdvisoryReadinessGate:
    """Fail-closed PR-068 gate for AI advisory-only evidence."""

    def __init__(self, policy: AIAdvisoryGatePolicy | None = None) -> None:
        self.policy = policy or AIAdvisoryGatePolicy()

    def evaluate(
        self,
        evidence: AIAdvisoryEvidencePackage,
    ) -> AIAdvisoryReadinessResult:
        blockers: list[str] = []
        warnings: list[str] = []
        checks = 0

        def check(condition: bool, code: AdvisoryFailureCode, detail: str = "") -> None:
            nonlocal checks
            checks += 1
            if not condition:
                blockers.append(f"{code.value}:{detail}" if detail else code.value)

        check(
            evidence.schema_version == _SCHEMA_VERSION,
            AdvisoryFailureCode.SCHEMA_VERSION_UNSUPPORTED,
            evidence.schema_version,
        )
        check(evidence.human_reviewed, AdvisoryFailureCode.HUMAN_REVIEW_MISSING)
        check(bool(evidence.registry), AdvisoryFailureCode.MODEL_REGISTRY_EMPTY)

        registry_by_model = self._registry_by_model(evidence.registry, blockers)
        evaluation_by_model = {item.model_id: item for item in evidence.evaluations}
        drift_by_model = {item.model_id: item for item in evidence.drift_reports}
        ab_by_model = {item.model_id: item for item in evidence.ab_reports}

        for model_id, registry_entry in registry_by_model.items():
            check(
                registry_entry.advisory_only
                and not registry_entry.trading_authority_enabled
                and registry_entry.promotion_state
                in self.policy.allowed_promotion_states,
                AdvisoryFailureCode.MODEL_TRADING_AUTHORITY_ENABLED,
                model_id,
            )

            evaluation = evaluation_by_model.get(model_id)
            if evaluation is None:
                check(False, AdvisoryFailureCode.MODEL_NOT_IN_REGISTRY, model_id)
            else:
                self._check_evaluation(registry_entry, evaluation, check)

            drift = drift_by_model.get(model_id)
            if drift is None:
                check(False, AdvisoryFailureCode.DRIFT_REPORT_MISSING, model_id)
            else:
                self._check_drift(drift, check)

            ab_report = ab_by_model.get(model_id)
            if ab_report is None:
                check(False, AdvisoryFailureCode.AB_SHADOW_MISSING, model_id)
            else:
                self._check_ab(ab_report, check)

        for model_id in sorted(set(evaluation_by_model).difference(registry_by_model)):
            check(False, AdvisoryFailureCode.MODEL_NOT_IN_REGISTRY, model_id)
        for model_id in sorted(set(drift_by_model).difference(registry_by_model)):
            check(False, AdvisoryFailureCode.MODEL_NOT_IN_REGISTRY, model_id)
        for model_id in sorted(set(ab_by_model).difference(registry_by_model)):
            check(False, AdvisoryFailureCode.MODEL_NOT_IN_REGISTRY, model_id)

        unique_blockers = tuple(dict.fromkeys(blockers))
        state: Literal["advisory-evidence-ready", "blocked"] = (
            "advisory-evidence-ready" if not unique_blockers else "blocked"
        )
        if state == "advisory-evidence-ready":
            warnings.append("AI_ADVISORY_ONLY_NO_TRADING_AUTHORITY")

        return AIAdvisoryReadinessResult(
            schema_version="pr068.ai-advisory-readiness-result.v1",
            state=state,
            evidence_sha256=evidence.evidence_sha256,
            evaluated_models=tuple(sorted(registry_by_model)),
            blockers=unique_blockers,
            warnings=tuple(dict.fromkeys(warnings)),
            checks_evaluated=checks,
        )

    @staticmethod
    def _registry_by_model(
        registry: Iterable[ModelRegistryEntry],
        blockers: list[str],
    ) -> dict[str, ModelRegistryEntry]:
        by_model: dict[str, ModelRegistryEntry] = {}
        for entry in registry:
            if entry.model_id in by_model:
                blockers.append(
                    f"{AdvisoryFailureCode.MODEL_REGISTRY_DUPLICATE.value}:"
                    f"{entry.model_id}"
                )
                continue
            by_model[entry.model_id] = entry
        return by_model

    def _check_evaluation(
        self,
        registry_entry: ModelRegistryEntry,
        evaluation: ModelEvaluationReport,
        check: Any,
    ) -> None:
        model_id = registry_entry.model_id
        check(
            evaluation.evaluation_dataset_sha256
            == registry_entry.evaluation_dataset_sha256,
            AdvisoryFailureCode.DATASET_HASH_MISMATCH,
            model_id,
        )
        check(
            evaluation.split_kind
            in {EvaluationSplitKind.TIME_SPLIT, EvaluationSplitKind.WALK_FORWARD}
            and registry_entry.registered_at >= evaluation.evaluation_window_end
            and evaluation.train_window_end < evaluation.evaluation_window_start
            and evaluation.evaluation_window_start < evaluation.evaluation_window_end,
            AdvisoryFailureCode.TIME_SPLIT_EVALUATION_MISSING,
            model_id,
        )
        check(
            evaluation.sample_count >= self.policy.min_evaluation_samples,
            AdvisoryFailureCode.EVALUATION_SAMPLE_TOO_SMALL,
            model_id,
        )
        metric_ok = (
            evaluation.precision_at_threshold >= self.policy.min_precision_at_threshold
            and evaluation.recall_at_threshold >= self.policy.min_recall_at_threshold
            and evaluation.brier_score <= self.policy.max_brier_score
        )
        check(
            metric_ok,
            AdvisoryFailureCode.EVALUATION_METRIC_BELOW_THRESHOLD,
            model_id,
        )
        check(
            evaluation.calibration_error <= self.policy.max_calibration_error,
            AdvisoryFailureCode.CALIBRATION_ERROR_TOO_HIGH,
            model_id,
        )
        check(
            evaluation.p95_latency_ms <= self.policy.max_p95_latency_ms,
            AdvisoryFailureCode.LATENCY_TOO_HIGH,
            model_id,
        )

    def _check_drift(self, drift: DriftMonitorReport, check: Any) -> None:
        model_id = drift.model_id
        check(
            drift.feature_drift_score <= self.policy.max_feature_drift_score,
            AdvisoryFailureCode.FEATURE_DRIFT_TOO_HIGH,
            model_id,
        )
        check(
            drift.prediction_drift_score <= self.policy.max_prediction_drift_score,
            AdvisoryFailureCode.PREDICTION_DRIFT_TOO_HIGH,
            model_id,
        )
        check(
            drift.missing_feature_rate <= self.policy.max_missing_feature_rate,
            AdvisoryFailureCode.MISSING_FEATURE_RATE_TOO_HIGH,
            model_id,
        )
        check(
            drift.automatic_disable_recorded,
            AdvisoryFailureCode.DRIFT_AUTODISABLE_MISSING,
            model_id,
        )

    def _check_ab(self, ab_report: ShadowABReport, check: Any) -> None:
        model_id = ab_report.model_id
        check(
            ab_report.sample_count >= self.policy.min_ab_samples,
            AdvisoryFailureCode.AB_SAMPLE_TOO_SMALL,
            model_id,
        )
        check(
            ab_report.live_decisions_taken == 0,
            AdvisoryFailureCode.AB_LIVE_DECISIONS_PRESENT,
            model_id,
        )
        check(
            ab_report.automatic_disable_recorded,
            AdvisoryFailureCode.AB_AUTOMATIC_DISABLE_MISSING,
            model_id,
        )
        check(
            ab_report.human_reviewed,
            AdvisoryFailureCode.AB_HUMAN_REVIEW_MISSING,
            model_id,
        )


__all__ = [
    "AIAdvisoryEvidencePackage",
    "AIAdvisoryGatePolicy",
    "AIAdvisoryReadinessGate",
    "AIAdvisoryReadinessResult",
    "AdvisoryFailureCode",
    "DriftMonitorReport",
    "EvaluationSplitKind",
    "ModelEvaluationReport",
    "ModelRegistryEntry",
    "PromotionState",
    "ShadowABReport",
]
