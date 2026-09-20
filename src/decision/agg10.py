"""AGG-10 offline intelligence, data-value and strategy-learning primitives.

This module extends the existing :mod:`src.decision` advisory boundary.  It is
intentionally sender-free: it performs deterministic research, ranking,
ablation and counterfactual work from already admitted evidence.  No object in
this module can sign, submit, mutate provider resources, or grant live trading
permission.

The implementation covers AGG-10/NF-081, NF-090, NF-095, NF-152, NF-154 and
NF-216..NF-238.  Advanced methods are represented by reproducible research
contracts with deterministic baselines rather than unverified black-box claims.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import math
import statistics
from typing import Mapping, Sequence


AGG10_SCHEMA_VERSION = "agg10-intelligence/v1"


def _stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nonempty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _variance(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return sum((item - mean) ** 2 for item in values) / len(values)


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_mean = _mean(left)
    right_mean = _mean(right)
    numerator = sum(
        (a - left_mean) * (b - right_mean) for a, b in zip(left, right, strict=True)
    )
    left_var = sum((a - left_mean) ** 2 for a in left)
    right_var = sum((b - right_mean) ** 2 for b in right)
    denominator = math.sqrt(left_var * right_var)
    return 0.0 if denominator == 0 else numerator / denominator


def _rank(values: Sequence[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        rank = (index + end - 1) / 2 + 1
        for position in range(index, end):
            ranks[ordered[position][0]] = rank
        index = end
    return ranks


def _spearman(left: Sequence[float], right: Sequence[float]) -> float:
    return _pearson(_rank(left), _rank(right))


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    if q <= 0:
        return min(values)
    if q >= 1:
        return max(values)
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


class IntelligenceDisposition(StrEnum):
    OBSERVED = "observed"
    HYPOTHESIS = "hypothesis"
    RESEARCH_ONLY = "research-only"
    BLOCKED = "blocked"


class LabelState(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    CENSORED = "censored"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FrozenExperiment:
    """Immutable experiment identity used by all AGG-10 comparisons."""

    experiment_id: str
    split_id: str
    workload_hash: str
    budget_units: int
    holdout_locked: bool = True
    available_at_semantics: bool = True
    live_effects_allowed: bool = False

    def __post_init__(self) -> None:
        _nonempty(self.experiment_id, "experiment_id")
        _nonempty(self.split_id, "split_id")
        _nonempty(self.workload_hash, "workload_hash")
        _positive_int(self.budget_units, "budget_units")
        if not self.holdout_locked or not self.available_at_semantics:
            raise ValueError("AGG-10 experiments require a locked temporal holdout")
        if self.live_effects_allowed:
            raise ValueError("AGG-10 research cannot authorize live effects")

    @property
    def identity(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True, slots=True)
class TimedFeatureRow:
    episode_id: str
    available_at: float
    features: Mapping[str, float]
    label: int | None = None

    def __post_init__(self) -> None:
        _nonempty(self.episode_id, "episode_id")
        _finite(self.available_at, "available_at")
        for key, value in self.features.items():
            _nonempty(key, "feature name")
            _finite(value, f"feature:{key}")
        if self.label not in (None, 0, 1):
            raise ValueError("label must be 0, 1 or None")


@dataclass(frozen=True, slots=True)
class OrderflowObservation:
    source_id: str
    observation_id: str
    visibility: str
    observed_at: float
    expires_at: float | None
    authorized: bool
    payload_hash: str
    settlement_confirmed: bool = False

    def __post_init__(self) -> None:
        _nonempty(self.source_id, "source_id")
        _nonempty(self.observation_id, "observation_id")
        if self.visibility not in {"hint", "signed_order", "auction_result", "history"}:
            raise ValueError("unsupported orderflow visibility")
        observed = _finite(self.observed_at, "observed_at")
        if self.expires_at is not None and _finite(
            self.expires_at, "expires_at"
        ) <= observed:
            raise ValueError("orderflow observation is already expired")
        if not self.authorized:
            raise PermissionError(
                "private/opt-in orderflow requires explicit authorization"
            )
        _nonempty(self.payload_hash, "payload_hash")
        if self.visibility == "hint" and self.settlement_confirmed:
            raise ValueError("a hint cannot self-attest settlement")

    @property
    def full_transaction_observed(self) -> bool:
        return self.visibility == "signed_order"


@dataclass(frozen=True, slots=True)
class StatisticalEdge:
    left_feature: str
    right_feature: str
    lag: int
    effect: float
    sample_count: int
    uncertainty: float
    corrected_alpha: float
    disposition: IntelligenceDisposition = IntelligenceDisposition.HYPOTHESIS
    causal_claim: bool = False
    trade_permission: bool = False

    def __post_init__(self) -> None:
        if self.causal_claim or self.trade_permission:
            raise ValueError(
                "statistical relations cannot authorize causality or trade"
            )


class StatisticalRelationGraph:
    """Build robust lagged dependence on a frozen train window."""

    @staticmethod
    def fit(
        rows: Sequence[TimedFeatureRow],
        *,
        feature_pairs: Sequence[tuple[str, str]],
        lags: Sequence[int] = (0, 1),
        alpha: float = 0.05,
    ) -> tuple[StatisticalEdge, ...]:
        if not rows:
            return ()
        ordered = sorted(rows, key=lambda row: (row.available_at, row.episode_id))
        tests = max(1, len(feature_pairs) * len(lags))
        corrected = alpha / tests
        edges: list[StatisticalEdge] = []
        for left_name, right_name in feature_pairs:
            for lag in lags:
                if lag < 0:
                    raise ValueError("lags must be non-negative")
                left: list[float] = []
                right: list[float] = []
                for index in range(lag, len(ordered)):
                    earlier = ordered[index - lag]
                    current = ordered[index]
                    if (
                        left_name not in earlier.features
                        or right_name not in current.features
                    ):
                        continue
                    left.append(float(earlier.features[left_name]))
                    right.append(float(current.features[right_name]))
                effect = _spearman(left, right)
                uncertainty = 1.0 / math.sqrt(max(1, len(left)))
                edges.append(
                    StatisticalEdge(
                        left_feature=left_name,
                        right_feature=right_name,
                        lag=lag,
                        effect=effect,
                        sample_count=len(left),
                        uncertainty=uncertainty,
                        corrected_alpha=corrected,
                    )
                )
        return tuple(edges)


@dataclass(frozen=True, slots=True)
class AblationArm:
    arm_id: str
    episode_ids: tuple[str, ...]
    correct: int
    admitted: int
    useful: int
    cost_units: int

    def __post_init__(self) -> None:
        _nonempty(self.arm_id, "arm_id")
        if len(self.episode_ids) != len(set(self.episode_ids)):
            raise ValueError("ablation episode_ids must be unique")
        for name, value in (
            ("correct", self.correct),
            ("admitted", self.admitted),
            ("useful", self.useful),
            ("cost_units", self.cost_units),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.correct > self.admitted or self.useful > self.admitted:
            raise ValueError("ablation counts are inconsistent")

    @property
    def precision(self) -> float | None:
        return None if self.admitted == 0 else self.correct / self.admitted

    @property
    def cost_per_useful(self) -> float | None:
        return None if self.useful == 0 else self.cost_units / self.useful


@dataclass(frozen=True, slots=True)
class AblationReport:
    experiment_id: str
    baseline: AblationArm
    challenger: AblationArm
    uplift_precision: float | None
    delta_cost_per_useful: float | None
    equal_workload: bool
    equal_budget: bool


def compare_source_ablation(
    experiment: FrozenExperiment, baseline: AblationArm, challenger: AblationArm
) -> AblationReport:
    equal_workload = set(baseline.episode_ids) == set(challenger.episode_ids)
    equal_budget = (
        baseline.cost_units <= experiment.budget_units
        and challenger.cost_units <= experiment.budget_units
    )
    if not equal_workload:
        raise ValueError("source ablation requires the same independent episodes")
    if not equal_budget:
        raise ValueError("source ablation exceeded the frozen research budget")
    uplift = (
        None
        if baseline.precision is None or challenger.precision is None
        else challenger.precision - baseline.precision
    )
    cost_delta = (
        None
        if baseline.cost_per_useful is None or challenger.cost_per_useful is None
        else challenger.cost_per_useful - baseline.cost_per_useful
    )
    return AblationReport(
        experiment_id=experiment.experiment_id,
        baseline=baseline,
        challenger=challenger,
        uplift_precision=uplift,
        delta_cost_per_useful=cost_delta,
        equal_workload=True,
        equal_budget=True,
    )


@dataclass(frozen=True, slots=True)
class CoverageGapHypothesis:
    market_id: str
    amount_base_units: int
    reason: str
    direct_output: int | None
    router_output: int | None
    program_trusted: bool
    execution_proven: bool = False
    disposition: IntelligenceDisposition = IntelligenceDisposition.HYPOTHESIS

    def __post_init__(self) -> None:
        _positive_int(self.amount_base_units, "amount_base_units")
        if self.reason not in {
            "aggregator_omission",
            "decoder_error",
            "stale_state",
            "permission_gap",
            "quote_disagreement",
        }:
            raise ValueError("unsupported coverage-gap reason")
        if self.execution_proven and not self.program_trusted:
            raise ValueError("untrusted programs cannot be execution-proven")


@dataclass(frozen=True, slots=True)
class OracleDivergenceSignal:
    asset_id: str
    market_price: float
    oracle_price: float
    oracle_age_seconds: float
    oracle_confidence: float
    affected_strategies: tuple[str, ...]
    data_quality_ok: bool
    trade_permission: bool = False

    def __post_init__(self) -> None:
        if self.trade_permission:
            raise ValueError("oracle divergence is a feature, not a trading venue")
        if self.oracle_price <= 0 or self.market_price <= 0:
            raise ValueError("prices must be positive")
        if self.oracle_age_seconds < 0 or self.oracle_confidence < 0:
            raise ValueError("oracle metadata is invalid")

    @property
    def relative_divergence(self) -> float:
        return (self.market_price - self.oracle_price) / self.oracle_price


@dataclass(frozen=True, slots=True)
class StatisticalFeatureSet:
    ewma: float
    median: float
    mad: float
    robust_z: float
    velocity: float
    missing_fraction: float
    window: int
    unit: str


def robust_statistics(
    values: Sequence[float | None], *, alpha: float = 0.25, unit: str = "ratio"
) -> StatisticalFeatureSet:
    if not 0 < alpha <= 1:
        raise ValueError("alpha must be in (0, 1]")
    _nonempty(unit, "unit")
    clean = [_finite(value, "value") for value in values if value is not None]
    if not clean:
        return StatisticalFeatureSet(
            0.0, 0.0, 0.0, 0.0, 0.0, 1.0, len(values), unit
        )
    ewma = clean[0]
    for item in clean[1:]:
        ewma = alpha * item + (1 - alpha) * ewma
    median = statistics.median(clean)
    deviations = [abs(item - median) for item in clean]
    mad = statistics.median(deviations)
    robust_z = 0.0 if mad == 0 else 0.67448975 * (clean[-1] - median) / mad
    velocity = 0.0 if len(clean) < 2 else clean[-1] - clean[-2]
    return StatisticalFeatureSet(
        ewma=ewma,
        median=median,
        mad=mad,
        robust_z=robust_z,
        velocity=velocity,
        missing_fraction=(len(values) - len(clean)) / max(1, len(values)),
        window=len(values),
        unit=unit,
    )


@dataclass(frozen=True, slots=True)
class MultivariateAnomalyModel:
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    training_rows: int

    @classmethod
    def fit(
        cls, rows: Sequence[Mapping[str, float]]
    ) -> "MultivariateAnomalyModel":
        if len(rows) < 2:
            raise ValueError(
                "multivariate anomaly baseline needs at least two rows"
            )
        names = tuple(sorted(set.intersection(*(set(row) for row in rows))))
        if not names:
            raise ValueError("no common anomaly features")
        columns = [[_finite(row[name], name) for row in rows] for name in names]
        means = tuple(_mean(column) for column in columns)
        scales = tuple(
            max(math.sqrt(_variance(column)), 1e-12) for column in columns
        )
        return cls(names, means, scales, len(rows))

    def score(self, features: Mapping[str, float]) -> float:
        total = 0.0
        for name, mean, scale in zip(
            self.feature_names, self.means, self.scales, strict=True
        ):
            if name not in features:
                raise ValueError(f"missing anomaly feature: {name}")
            z = (_finite(features[name], name) - mean) / scale
            total += z * z
        return math.sqrt(total)


class FeatureTransform(StrEnum):
    IDENTITY = "identity"
    LAG = "lag"
    ROLLING_MEAN = "rolling_mean"
    RATIO = "ratio"


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    name: str
    transform: FeatureTransform
    sources: tuple[str, ...]
    window: int = 1
    unit: str = "ratio"
    cost_units: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.name, "feature name")
        if any(
            token in self.name.lower() for token in ("future", "label", "landing")
        ):
            raise ValueError("feature names may not encode future labels")
        if not self.sources:
            raise ValueError("feature definition needs source fields")
        _positive_int(self.window, "window")
        _positive_int(self.cost_units, "cost_units")

    @property
    def identity(self) -> str:
        return _digest(
            {
                "name": self.name,
                "transform": self.transform.value,
                "sources": self.sources,
                "window": self.window,
                "unit": self.unit,
                "cost_units": self.cost_units,
            }
        )


class FeatureGenerator:
    def __init__(
        self, definitions: Sequence[FeatureDefinition], *, budget_units: int
    ) -> None:
        self.definitions = tuple(definitions)
        self.budget_units = _positive_int(budget_units, "budget_units")
        if sum(item.cost_units for item in self.definitions) > self.budget_units:
            raise ValueError("feature-generation cost exceeds frozen budget")

    def materialize(
        self, history: Sequence[Mapping[str, float]]
    ) -> Mapping[str, float | None]:
        if not history:
            return {item.name: None for item in self.definitions}
        current = history[-1]
        output: dict[str, float | None] = {}
        for item in self.definitions:
            if item.transform is FeatureTransform.IDENTITY:
                output[item.name] = (
                    _finite(current[item.sources[0]], item.sources[0])
                    if item.sources[0] in current
                    else None
                )
            elif item.transform is FeatureTransform.LAG:
                index = len(history) - 1 - item.window
                output[item.name] = (
                    _finite(history[index][item.sources[0]], item.sources[0])
                    if index >= 0 and item.sources[0] in history[index]
                    else None
                )
            elif item.transform is FeatureTransform.ROLLING_MEAN:
                tail = history[-item.window :]
                values = [
                    _finite(row[item.sources[0]], item.sources[0])
                    for row in tail
                    if item.sources[0] in row
                ]
                output[item.name] = _mean(values) if values else None
            elif item.transform is FeatureTransform.RATIO:
                if len(item.sources) != 2:
                    raise ValueError(
                        "ratio transforms require two source fields"
                    )
                if any(name not in current for name in item.sources):
                    output[item.name] = None
                else:
                    numerator = _finite(
                        current[item.sources[0]], item.sources[0]
                    )
                    denominator = _finite(
                        current[item.sources[1]], item.sources[1]
                    )
                    output[item.name] = (
                        None if denominator == 0 else numerator / denominator
                    )
        return output


@dataclass(frozen=True, slots=True)
class CandidateLearningRow:
    candidate_id: str
    episode_id: str
    features: Mapping[str, float]
    admitted: bool
    useful_simulation: bool | None
    buildable: bool | None
    error_class: str | None = None
    adapter_id: str = "unknown"


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    candidate_id: str
    score: float
    propensity: float


class BudgetedSimulationRanker:
    """Deterministic simulation-budget ranker with no execution authority."""

    def __init__(self, weights: Mapping[str, float]) -> None:
        self.weights = dict(weights)

    @classmethod
    def fit(
        cls, rows: Sequence[CandidateLearningRow]
    ) -> "BudgetedSimulationRanker":
        labeled = [
            row
            for row in rows
            if row.admitted and row.useful_simulation is not None
        ]
        positives = [row for row in labeled if row.useful_simulation]
        negatives = [row for row in labeled if not row.useful_simulation]
        if not positives or not negatives:
            return cls({})
        names = sorted(set.intersection(*(set(row.features) for row in labeled)))
        weights: dict[str, float] = {}
        for name in names:
            pos = _mean(
                [_finite(row.features[name], name) for row in positives]
            )
            neg = _mean(
                [_finite(row.features[name], name) for row in negatives]
            )
            scale_values = [
                _finite(row.features[name], name) for row in labeled
            ]
            scale = max(math.sqrt(_variance(scale_values)), 1e-12)
            weights[name] = (pos - neg) / scale
        return cls(weights)

    def rank(
        self, rows: Sequence[CandidateLearningRow], *, budget: int
    ) -> tuple[RankedCandidate, ...]:
        _positive_int(budget, "budget")
        admitted = [row for row in rows if row.admitted]
        scored = [
            (
                row,
                sum(
                    self.weights.get(name, 0.0) * _finite(value, name)
                    for name, value in row.features.items()
                ),
            )
            for row in admitted
        ]
        scored.sort(key=lambda item: (-item[1], item[0].candidate_id))
        selected = scored[:budget]
        propensity = (
            0.0 if not admitted else min(1.0, budget / len(admitted))
        )
        return tuple(
            RankedCandidate(row.candidate_id, score, propensity)
            for row, score in selected
        )


@dataclass(frozen=True, slots=True)
class BuildabilityPrediction:
    probability: float | None
    error_class: str | None
    abstained: bool


class BuildabilityModel:
    def __init__(
        self,
        table: Mapping[str, tuple[int, int, Mapping[str, int]]],
        *,
        min_support: int,
    ) -> None:
        self.table = dict(table)
        self.min_support = _positive_int(min_support, "min_support")

    @classmethod
    def fit(
        cls, rows: Sequence[CandidateLearningRow], *, min_support: int = 3
    ) -> "BuildabilityModel":
        table: dict[str, tuple[int, int, dict[str, int]]] = {}
        mutable: dict[str, dict[str, object]] = {}
        for row in rows:
            if not row.admitted or row.buildable is None:
                continue
            bucket = mutable.setdefault(
                row.adapter_id, {"total": 0, "ok": 0, "errors": {}}
            )
            bucket["total"] = int(bucket["total"]) + 1
            bucket["ok"] = int(bucket["ok"]) + int(row.buildable)
            if row.error_class:
                errors = bucket["errors"]
                assert isinstance(errors, dict)
                errors[row.error_class] = (
                    int(errors.get(row.error_class, 0)) + 1
                )
        for adapter, bucket in mutable.items():
            errors = bucket["errors"]
            assert isinstance(errors, dict)
            table[adapter] = (
                int(bucket["total"]),
                int(bucket["ok"]),
                errors,
            )
        return cls(table, min_support=min_support)

    def predict(self, adapter_id: str) -> BuildabilityPrediction:
        item = self.table.get(adapter_id)
        if item is None or item[0] < self.min_support:
            return BuildabilityPrediction(None, None, True)
        total, ok, errors = item
        error_class = None
        if errors:
            error_class = max(
                errors.items(), key=lambda pair: (pair[1], pair[0])
            )[0]
        return BuildabilityPrediction(ok / total, error_class, False)


@dataclass(frozen=True, slots=True)
class ExactSizeTrace:
    amount: int
    conservative_net: int
    feasible: bool


class SizeProposalModel:
    def __init__(self, traces: Sequence[ExactSizeTrace]) -> None:
        self.traces = tuple(sorted(traces, key=lambda item: item.amount))
        if any(item.amount <= 0 for item in self.traces):
            raise ValueError("size traces require positive amounts")

    def propose(
        self, *, max_amount: int, top_k: int = 3
    ) -> tuple[int, ...]:
        _positive_int(max_amount, "max_amount")
        _positive_int(top_k, "top_k")
        feasible = [
            item
            for item in self.traces
            if item.feasible and item.amount <= max_amount
        ]
        if not feasible:
            return ()
        feasible.sort(
            key=lambda item: (-item.conservative_net, item.amount)
        )
        return tuple(item.amount for item in feasible[:top_k])


@dataclass(frozen=True, slots=True)
class SurvivalObservation:
    episode_id: str
    family: str
    regime: str
    horizon_ms: int
    state: LabelState


@dataclass(frozen=True, slots=True)
class SurvivalPrediction:
    probability: float | None
    support: int
    abstained: bool


class SurvivalModel:
    def __init__(
        self,
        observations: Sequence[SurvivalObservation],
        *,
        min_support: int = 3,
    ) -> None:
        self.observations = tuple(observations)
        self.min_support = _positive_int(min_support, "min_support")

    def predict(
        self, *, family: str, regime: str, horizon_ms: int
    ) -> SurvivalPrediction:
        _positive_int(horizon_ms, "horizon_ms")
        rows = [
            item
            for item in self.observations
            if item.family == family
            and item.regime == regime
            and item.horizon_ms == horizon_ms
            and item.state in {LabelState.POSITIVE, LabelState.NEGATIVE}
        ]
        if len(rows) < self.min_support:
            return SurvivalPrediction(None, len(rows), True)
        positives = sum(
            item.state is LabelState.POSITIVE for item in rows
        )
        return SurvivalPrediction(
            positives / len(rows), len(rows), False
        )


@dataclass(frozen=True, slots=True)
class LandingObservation:
    attempt_id: str
    live03_evidence_id: str | None
    observed_execution: bool
    outcome: LabelState
    cost_base_units: int | None
    route_class: str
    fee_band: str

    def __post_init__(self) -> None:
        _nonempty(self.attempt_id, "attempt_id")
        if self.observed_execution and not self.live03_evidence_id:
            raise ValueError(
                "real landing labels require LIVE-03 evidence identity"
            )
        if not self.observed_execution and self.outcome in {
            LabelState.POSITIVE,
            LabelState.NEGATIVE,
        }:
            raise ValueError(
                "paper/counterfactual rows cannot be real landing labels"
            )
        if self.cost_base_units is not None and self.cost_base_units < 0:
            raise ValueError("landing cost cannot be negative")


@dataclass(frozen=True, slots=True)
class LandingCostPrediction:
    probability: float | None
    expected_cost_base_units: int | None
    support: int
    blocked_reason: str | None


class LandingCostModel:
    def __init__(
        self,
        rows: Sequence[LandingObservation],
        *,
        min_support: int = 3,
    ) -> None:
        self.rows = tuple(rows)
        self.min_support = _positive_int(min_support, "min_support")

    def predict(
        self, *, route_class: str, fee_band: str
    ) -> LandingCostPrediction:
        real = [
            row
            for row in self.rows
            if row.observed_execution
            and row.live03_evidence_id
            and row.route_class == route_class
            and row.fee_band == fee_band
            and row.outcome in {LabelState.POSITIVE, LabelState.NEGATIVE}
        ]
        if len(real) < self.min_support:
            return LandingCostPrediction(
                None,
                None,
                len(real),
                "INSUFFICIENT_LIVE03_LABELS",
            )
        success = sum(
            row.outcome is LabelState.POSITIVE for row in real
        )
        costs = [
            row.cost_base_units
            for row in real
            if row.cost_base_units is not None
        ]
        expected_cost = (
            None if not costs else round(sum(costs) / len(costs))
        )
        return LandingCostPrediction(
            success / len(real),
            expected_cost,
            len(real),
            None,
        )


@dataclass(frozen=True, slots=True)
class ResearchComparison:
    experiment_id: str
    task: str
    baseline_metric: float
    challenger_metric: float
    compute_cost_units: int
    holdout_locked: bool
    assumptions: tuple[str, ...]
    causal_claim: bool = False

    @property
    def uplift(self) -> float:
        return self.challenger_metric - self.baseline_metric


def factor_cointegration_research(
    *,
    experiment_id: str,
    left: Sequence[float],
    right: Sequence[float],
    compute_cost_units: int,
) -> ResearchComparison:
    if len(left) != len(right) or len(left) < 4:
        raise ValueError("factor research requires aligned series")
    levels = abs(_spearman(left, right))
    left_diff = [b - a for a, b in zip(left, left[1:])]
    right_diff = [b - a for a, b in zip(right, right[1:])]
    changes = abs(_spearman(left_diff, right_diff))
    return ResearchComparison(
        experiment_id=experiment_id,
        task="factor-cointegration-screen",
        baseline_metric=levels,
        challenger_metric=changes,
        compute_cost_units=compute_cost_units,
        holdout_locked=True,
        assumptions=(
            "screen-only; stationarity and costs require downstream validation",
            "available-at aligned inputs",
        ),
    )


def lead_lag_research(
    *,
    experiment_id: str,
    trigger: Sequence[float],
    target: Sequence[float],
    max_lag: int,
) -> ResearchComparison:
    _positive_int(max_lag, "max_lag")
    if len(trigger) != len(target) or len(trigger) <= max_lag + 2:
        raise ValueError("lead-lag research requires aligned history")
    baseline = abs(_spearman(trigger, target))
    effects = []
    for lag in range(1, max_lag + 1):
        effects.append(
            abs(_spearman(trigger[:-lag], target[lag:]))
        )
    return ResearchComparison(
        experiment_id=experiment_id,
        task="lead-lag-screen",
        baseline_metric=baseline,
        challenger_metric=max(effects, default=0.0),
        compute_cost_units=max_lag,
        holdout_locked=True,
        assumptions=(
            "delivery-delay controls required",
            "prediction is not causality",
        ),
    )


@dataclass(frozen=True, slots=True)
class AdvancedModelExperiment:
    model_family: str
    upstream_identity: str
    licence_reviewed: bool
    task: str
    baseline_metric: float
    challenger_metric: float
    holdout_hash: str
    compute_cost_units: int
    trading_authority: bool = False

    def __post_init__(self) -> None:
        if not self.licence_reviewed:
            raise ValueError(
                "advanced model experiments require a licence decision"
            )
        if self.trading_authority:
            raise ValueError(
                "advanced models cannot receive trading authority"
            )
        _nonempty(self.holdout_hash, "holdout_hash")


@dataclass(frozen=True, slots=True)
class InvariantCheck:
    name: str
    minimum: float | None = None
    maximum: float | None = None
    hard: bool = True

    def evaluate(self, value: float | None) -> str:
        if value is None:
            return "unknown"
        value = _finite(value, self.name)
        if self.minimum is not None and value < self.minimum:
            return "violation"
        if self.maximum is not None and value > self.maximum:
            return "violation"
        return "ok"


@dataclass(frozen=True, slots=True)
class RegimeModelSnapshot:
    model_id: str
    feature_schema_hash: str
    regime_id: str
    context_hash: str
    performance_metric: float


class RegimeMemory:
    def __init__(self) -> None:
        self._snapshots: list[RegimeModelSnapshot] = []

    def archive(self, snapshot: RegimeModelSnapshot) -> None:
        if snapshot in self._snapshots:
            return
        self._snapshots.append(snapshot)

    def compatible(
        self, *, feature_schema_hash: str, regime_id: str
    ) -> tuple[RegimeModelSnapshot, ...]:
        return tuple(
            item
            for item in self._snapshots
            if item.feature_schema_hash == feature_schema_hash
            and item.regime_id == regime_id
        )


@dataclass(frozen=True, slots=True)
class DriftSignals:
    psi: float | None
    ks_distance: float | None
    economic_error_delta: float | None
    support: int
    demote: bool
    retrain: bool


def _histogram(
    values: Sequence[float], cuts: Sequence[float]
) -> list[int]:
    bins = [0] * (len(cuts) + 1)
    for value in values:
        index = 0
        while index < len(cuts) and value > cuts[index]:
            index += 1
        bins[index] += 1
    return bins


def drift_monitor(
    baseline: Sequence[float],
    current: Sequence[float],
    *,
    economic_error_delta: float | None = None,
    min_support: int = 20,
    psi_threshold: float = 0.2,
    ks_threshold: float = 0.2,
) -> DriftSignals:
    if len(baseline) < min_support or len(current) < min_support:
        return DriftSignals(
            None,
            None,
            economic_error_delta,
            min(len(baseline), len(current)),
            False,
            False,
        )
    base = [_finite(value, "baseline") for value in baseline]
    now = [_finite(value, "current") for value in current]
    cuts = [_quantile(base, q) for q in (0.2, 0.4, 0.6, 0.8)]
    base_hist = _histogram(base, cuts)
    now_hist = _histogram(now, cuts)
    eps = 1e-9
    psi = 0.0
    for base_count, now_count in zip(
        base_hist, now_hist, strict=True
    ):
        p = max(eps, base_count / len(base))
        q = max(eps, now_count / len(now))
        psi += (q - p) * math.log(q / p)
    points = sorted(set(base + now))
    ks = 0.0
    for point in points:
        base_cdf = sum(value <= point for value in base) / len(base)
        now_cdf = sum(value <= point for value in now) / len(now)
        ks = max(ks, abs(base_cdf - now_cdf))
    economic_bad = (
        economic_error_delta is not None
        and economic_error_delta > 0
    )
    drifted = (
        psi > psi_threshold
        or ks > ks_threshold
        or economic_bad
    )
    return DriftSignals(
        psi,
        ks,
        economic_error_delta,
        min(len(base), len(now)),
        drifted,
        drifted,
    )


@dataclass(frozen=True, slots=True)
class ModelBundle:
    model_id: str
    artifact_hash: str
    dataset_hash: str
    train_code_hash: str
    feature_schema_hash: str
    split_hash: str
    policy_hash: str
    supported_regimes: tuple[str, ...]
    limitations: tuple[str, ...]
    compute_cost_units: int
    signer_or_sender_authority: bool = False

    def __post_init__(self) -> None:
        for name in (
            "model_id",
            "artifact_hash",
            "dataset_hash",
            "train_code_hash",
            "feature_schema_hash",
            "split_hash",
            "policy_hash",
        ):
            _nonempty(str(getattr(self, name)), name)
        if self.signer_or_sender_authority:
            raise ValueError(
                "model bundles cannot carry signer/sender authority"
            )
        if self.compute_cost_units < 0:
            raise ValueError("compute_cost_units cannot be negative")

    @property
    def identity(self) -> str:
        return _digest(asdict(self))


class ModelRegistry:
    """Content-addressed model registry; there is no mutable latest."""

    def __init__(self) -> None:
        self._bundles: dict[str, ModelBundle] = {}

    def register(self, bundle: ModelBundle) -> str:
        identity = bundle.identity
        existing = self._bundles.get(identity)
        if existing is not None and existing != bundle:
            raise ValueError("model bundle identity collision")
        self._bundles[identity] = bundle
        return identity

    def get(self, identity: str) -> ModelBundle:
        if identity not in self._bundles:
            raise KeyError(identity)
        return self._bundles[identity]


@dataclass(frozen=True, slots=True)
class PromotionMetrics:
    quality: float
    calibration_error: float
    tail_loss: float
    cost_units: int


@dataclass(frozen=True, slots=True)
class ModelPromotionDecision:
    promoted: bool
    reason: str
    rollback_identity: str
    live_authority_granted: bool = False


def compare_champion_challenger(
    *,
    champion_identity: str,
    challenger_identity: str,
    champion: PromotionMetrics,
    challenger: PromotionMetrics,
    same_frozen_holdout: bool,
) -> ModelPromotionDecision:
    del challenger_identity
    if not same_frozen_holdout:
        return ModelPromotionDecision(
            False, "HOLDOUT_MISMATCH", champion_identity
        )
    better_quality = challenger.quality > champion.quality
    calibration_ok = (
        challenger.calibration_error
        <= champion.calibration_error
    )
    tail_ok = challenger.tail_loss <= champion.tail_loss
    cost_ok = challenger.cost_units <= champion.cost_units
    promoted = (
        better_quality and calibration_ok and tail_ok and cost_ok
    )
    return ModelPromotionDecision(
        promoted,
        (
            "QUALIFIED_CHALLENGER"
            if promoted
            else "CHALLENGER_NOT_BETTER_ON_ALL_GATES"
        ),
        champion_identity,
    )


@dataclass(frozen=True, slots=True)
class QueryCandidate:
    query_id: str
    expected_uncertainty_reduction: float
    cost_units: int
    mandatory_safety: bool = False


class ValueOfInformationPolicy:
    def choose(
        self,
        candidates: Sequence[QueryCandidate],
        *,
        remaining_budget: int,
    ) -> QueryCandidate | None:
        if remaining_budget < 0:
            raise ValueError("remaining_budget cannot be negative")
        mandatory = [
            item for item in candidates if item.mandatory_safety
        ]
        affordable_mandatory = [
            item
            for item in mandatory
            if item.cost_units <= remaining_budget
        ]
        if mandatory and len(affordable_mandatory) != len(mandatory):
            raise ValueError(
                "research optimization may not drop mandatory safety queries"
            )
        mandatory_cost = sum(item.cost_units for item in mandatory)
        optional_budget = remaining_budget - mandatory_cost
        optional = [
            item
            for item in candidates
            if not item.mandatory_safety
            and item.cost_units <= optional_budget
        ]
        if not optional:
            return None
        return max(
            optional,
            key=lambda item: (
                item.expected_uncertainty_reduction
                / max(1, item.cost_units),
                item.expected_uncertainty_reduction,
                item.query_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class ExogenousScenario:
    scenario_id: str
    flow_multiplier: float
    latency_multiplier: float
    competition_multiplier: float
    synthetic: bool = True

    def __post_init__(self) -> None:
        for name in (
            "flow_multiplier",
            "latency_multiplier",
            "competition_multiplier",
        ):
            if _finite(getattr(self, name), name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if not self.synthetic:
            raise ValueError(
                "AGG-10 scenarios are counterfactual, not observed market rows"
            )


@dataclass(frozen=True, slots=True)
class MarketWorldModel:
    deterministic_state_hash: str
    empirical_distribution_hash: str
    unknown_fields: tuple[str, ...]

    def scenario(
        self, item: ExogenousScenario
    ) -> Mapping[str, object]:
        return {
            "deterministic_state_hash": self.deterministic_state_hash,
            "scenario_id": item.scenario_id,
            "flow_multiplier": item.flow_multiplier,
            "latency_multiplier": item.latency_multiplier,
            "competition_multiplier": item.competition_multiplier,
            "synthetic": True,
            "unknown_fields": self.unknown_fields,
        }


@dataclass(frozen=True, slots=True)
class StressScenarioResult:
    scenario_id: str
    conservative_net: int
    passed: bool
    observed_market_evidence: bool = False


def run_stress_scenarios(
    *, baseline_net: int, scenarios: Sequence[ExogenousScenario]
) -> tuple[StressScenarioResult, ...]:
    output: list[StressScenarioResult] = []
    for item in scenarios:
        penalty = (
            item.latency_multiplier * item.competition_multiplier
        )
        adjusted = int(baseline_net / max(1.0, penalty))
        output.append(
            StressScenarioResult(
                item.scenario_id, adjusted, adjusted > 0
            )
        )
    return tuple(output)


@dataclass(frozen=True, slots=True)
class CapacityReflexivityReport:
    size_points: tuple[int, ...]
    net_points: tuple[int, ...]
    overlap_fraction: float
    linear_extrapolation_allowed: bool = False

    def __post_init__(self) -> None:
        if (
            len(self.size_points) != len(self.net_points)
            or not self.size_points
        ):
            raise ValueError(
                "capacity report requires aligned size/net points"
            )
        if not 0 <= self.overlap_fraction <= 1:
            raise ValueError(
                "overlap_fraction must be in [0, 1]"
            )
        if self.linear_extrapolation_allowed:
            raise ValueError(
                "AGG-10 forbids linear extrapolation of alpha capacity"
            )


@dataclass(frozen=True, slots=True)
class StrategyPrimitive:
    primitive_id: str
    input_unit: str
    output_unit: str
    debt_delta: int = 0
    trusted: bool = True


@dataclass(frozen=True, slots=True)
class GeneratedStrategySpec:
    primitive_ids: tuple[str, ...]
    input_unit: str
    output_unit: str
    debt_closed: bool
    strategy_id: str
    research_only: bool = True


class SymbolicStrategyFactory:
    def __init__(
        self, primitives: Sequence[StrategyPrimitive]
    ) -> None:
        self.primitives = {
            item.primitive_id: item for item in primitives
        }
        if len(self.primitives) != len(primitives):
            raise ValueError("duplicate strategy primitive")

    def compose(
        self, primitive_ids: Sequence[str]
    ) -> GeneratedStrategySpec:
        if not primitive_ids:
            raise ValueError(
                "strategy composition cannot be empty"
            )
        selected: list[StrategyPrimitive] = []
        for primitive_id in primitive_ids:
            if primitive_id not in self.primitives:
                raise ValueError(
                    "LLM/research cannot introduce an unverified primitive"
                )
            primitive = self.primitives[primitive_id]
            if not primitive.trusted:
                raise ValueError("untrusted strategy primitive")
            selected.append(primitive)
        for left, right in zip(
            selected, selected[1:]
        ):
            if left.output_unit != right.input_unit:
                raise ValueError(
                    "strategy units do not compose"
                )
        debt = sum(item.debt_delta for item in selected)
        if debt != 0:
            raise ValueError(
                "generated strategy leaves an open debt"
            )
        canonical = tuple(
            item.primitive_id for item in selected
        )
        strategy_id = _digest(
            {"primitives": canonical}
        )
        return GeneratedStrategySpec(
            canonical,
            selected[0].input_unit,
            selected[-1].output_unit,
            True,
            strategy_id,
        )


@dataclass(frozen=True, slots=True)
class OfflinePolicyCandidate:
    policy_id: str
    action_support_fraction: float
    estimated_reward: float
    uncertainty: float
    changes_risk_limits: bool = False


@dataclass(frozen=True, slots=True)
class OfflinePolicyDecision:
    selected_policy_id: str
    trusted: bool
    reason: str
    live_exploration_allowed: bool = False


def evaluate_offline_policies(
    baseline: OfflinePolicyCandidate,
    challengers: Sequence[OfflinePolicyCandidate],
) -> OfflinePolicyDecision:
    allowed = [baseline, *challengers]
    for item in allowed:
        if item.changes_risk_limits:
            raise ValueError(
                "learning policies may not change risk limits"
            )
    eligible = [
        item
        for item in allowed
        if item.action_support_fraction >= 0.8
        and item.uncertainty <= 0.25
    ]
    if not eligible:
        return OfflinePolicyDecision(
            baseline.policy_id,
            False,
            "INSUFFICIENT_SUPPORT",
        )
    winner = max(
        eligible,
        key=lambda item: (
            item.estimated_reward,
            item.policy_id,
        ),
    )
    trusted = (
        winner.estimated_reward > baseline.estimated_reward
        and winner is not baseline
    )
    return OfflinePolicyDecision(
        winner.policy_id if trusted else baseline.policy_id,
        trusted,
        (
            "OFFLINE_CHALLENGER_BETTER"
            if trusted
            else "BASELINE_RETAINED"
        ),
    )


@dataclass(frozen=True, slots=True)
class LearningTaskEvidence:
    task_id: str
    reproducible: bool
    holdout_uplift: float | None
    cost_units: int
    fallback_verified: bool
    calibration_ok: bool
    replay_consistent: bool
    required: bool = False


@dataclass(frozen=True, slots=True)
class LearningQualificationVerdict:
    accepted_tasks: tuple[str, ...]
    blocked_tasks: tuple[str, ...]
    operational_status: str
    live_authority_granted: bool = False


def qualify_learning_layer(
    tasks: Sequence[LearningTaskEvidence],
) -> LearningQualificationVerdict:
    accepted: list[str] = []
    blocked: list[str] = []
    for item in tasks:
        ok = (
            item.reproducible
            and item.fallback_verified
            and item.calibration_ok
            and item.replay_consistent
            and item.cost_units >= 0
            and item.holdout_uplift is not None
            and item.holdout_uplift >= 0
        )
        (accepted if ok else blocked).append(
            item.task_id
        )
    required_blocked = any(
        item.required and item.task_id in blocked
        for item in tasks
    )
    status = (
        "BLOCKED"
        if required_blocked
        else "IMPLEMENTED_OFFLINE"
    )
    return LearningQualificationVerdict(
        tuple(accepted),
        tuple(blocked),
        status,
    )


AGG10_NF_COVERAGE: Mapping[str, str] = {
    "NF-081": "OrderflowObservation",
    "NF-090": "StatisticalRelationGraph",
    "NF-095": "compare_source_ablation",
    "NF-152": "CoverageGapHypothesis",
    "NF-154": "OracleDivergenceSignal",
    "NF-216": "robust_statistics",
    "NF-217": "MultivariateAnomalyModel",
    "NF-218": "FeatureGenerator",
    "NF-219": "BudgetedSimulationRanker",
    "NF-220": "BuildabilityModel",
    "NF-221": "SizeProposalModel",
    "NF-222": "SurvivalModel",
    "NF-223": "LandingCostModel",
    "NF-224": "factor_cointegration_research",
    "NF-225": "lead_lag_research",
    "NF-226": "AdvancedModelExperiment",
    "NF-227": "InvariantCheck",
    "NF-228": "RegimeMemory",
    "NF-229": "drift_monitor",
    "NF-230": "ModelRegistry",
    "NF-231": "compare_champion_challenger",
    "NF-232": "ValueOfInformationPolicy",
    "NF-233": "MarketWorldModel",
    "NF-234": "run_stress_scenarios",
    "NF-235": "CapacityReflexivityReport",
    "NF-236": "SymbolicStrategyFactory",
    "NF-237": "evaluate_offline_policies",
    "NF-238": "qualify_learning_layer",
}


def validate_agg10_coverage() -> bool:
    expected = {
        "NF-081",
        "NF-090",
        "NF-095",
        "NF-152",
        "NF-154",
        *(f"NF-{number:03d}" for number in range(216, 239)),
    }
    return set(AGG10_NF_COVERAGE) == expected
