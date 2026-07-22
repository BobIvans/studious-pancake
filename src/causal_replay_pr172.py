"""PR-172 causal replay, backtest and model-promotion validity gate.

This module is deliberately side-effect-free.  It does not train a model, open a
database, call providers, or promote a strategy.  It defines a strict offline
contract that future research/backtest pipelines must satisfy before their
results can be used as tuning or promotion evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:/@+-]{3,160}$")


class ReplayTier(StrEnum):
    DECISION_REPLAY = "decision-replay"
    TRANSACTION_REPLAY = "transaction-replay"
    MARKET_REPLAY = "market-replay"
    LIVE_SHADOW = "live-shadow"


class EventType(StrEnum):
    CANDIDATE = "candidate"
    TERMINAL = "terminal"


class PromotionDecision(StrEnum):
    BLOCKED = "blocked"
    REVIEWABLE = "reviewable"


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    """A recorded candidate or terminal event with explicit availability time."""

    event_id: str
    event_type: EventType
    root_opportunity_id: str
    attempt_generation: int
    evidence_generation: int
    observed_at_ns: int
    available_at_ns: int
    route_shape_class: str = "unknown"
    provider_health: str = "unknown"
    label_value: int | None = None

    def __post_init__(self) -> None:
        if not SAFE_ID_RE.fullmatch(self.event_id):
            raise ValueError("invalid event_id")
        if not SAFE_ID_RE.fullmatch(self.root_opportunity_id):
            raise ValueError("invalid root_opportunity_id")
        if self.attempt_generation < 0 or self.evidence_generation < 0:
            raise ValueError("negative generation")
        if self.available_at_ns < self.observed_at_ns:
            raise ValueError("available_at_ns before observed_at_ns")
        if self.event_type is EventType.TERMINAL and self.label_value not in {0, 1}:
            raise ValueError("terminal event requires binary label_value")
        if self.event_type is EventType.CANDIDATE and self.label_value is not None:
            raise ValueError("candidate event cannot carry label_value")


@dataclass(frozen=True, slots=True)
class CausalFeatureRow:
    row_id: str
    candidate_event_id: str
    root_opportunity_id: str
    attempt_generation: int
    evidence_generation: int
    candidate_available_at_ns: int
    historical_success_count: int
    historical_failure_count: int
    historical_success_rate_ppm: int
    label_status: str
    label_value: int | None
    terminal_event_id: str | None


@dataclass(frozen=True, slots=True)
class ReplayCorpusManifest:
    dataset_id: str
    dataset_hash: str
    code_hash: str
    policy_bundle_hash: str
    replay_tier: ReplayTier
    event_count: int
    synthetic: bool = False

    def validate(self) -> None:
        if not SAFE_ID_RE.fullmatch(self.dataset_id):
            raise ValueError("invalid dataset_id")
        for field_name, value in (
            ("dataset_hash", self.dataset_hash),
            ("code_hash", self.code_hash),
            ("policy_bundle_hash", self.policy_bundle_hash),
        ):
            if not SHA256_RE.fullmatch(value):
                raise ValueError(f"{field_name} must be sha256")
        if self.event_count <= 0:
            raise ValueError("event_count must be positive")


@dataclass(frozen=True, slots=True)
class EvaluationSplitEvidence:
    train_ids: tuple[str, ...]
    calibration_ids: tuple[str, ...]
    test_ids: tuple[str, ...]
    train_statistics_source: str
    threshold_source: str
    environment_dependent: bool = False

    def validate(self) -> None:
        train = set(self.train_ids)
        calibration = set(self.calibration_ids)
        test = set(self.test_ids)
        if not train or not calibration or not test:
            raise ValueError("train/calibration/test partitions are required")
        if train & calibration or train & test or calibration & test:
            raise ValueError("train/calibration/test partitions overlap")
        if self.train_statistics_source != "train-only":
            raise ValueError("train statistics must use train-only data")
        if self.threshold_source not in {"calibration", "fixed-reviewed-policy"}:
            raise ValueError("threshold source must be calibration or reviewed policy")
        if self.environment_dependent:
            raise ValueError("offline evaluation cannot depend on process environment")


@dataclass(frozen=True, slots=True)
class BacktestInputContract:
    requested_db_path: str
    opened_db_path: str
    approved_table: str
    observed_tables: tuple[str, ...]
    schema_hash: str
    read_only: bool
    used_float_money: bool
    arbitrary_table_fallback: bool
    linear_slippage_claims_market_replay: bool

    def validate(self) -> None:
        if self.requested_db_path != self.opened_db_path:
            raise ValueError("backtest opened a different database than requested")
        if self.approved_table != "paper_trades":
            raise ValueError("approved replay table must be paper_trades")
        if self.observed_tables != ("paper_trades",):
            raise ValueError("backtest may not mix arbitrary SQLite tables")
        if not SHA256_RE.fullmatch(self.schema_hash):
            raise ValueError("schema_hash must be sha256")
        if not self.read_only:
            raise ValueError("backtest database connection must be read-only")
        if self.used_float_money:
            raise ValueError("financial replay must use integer base units")
        if self.arbitrary_table_fallback:
            raise ValueError("arbitrary table fallback is forbidden")
        if self.linear_slippage_claims_market_replay:
            raise ValueError("linear haircut cannot claim market replay")


@dataclass(slots=True)
class ReplayValidityReport:
    manifest: ReplayCorpusManifest
    split: EvaluationSplitEvidence
    backtest: BacktestInputContract
    rows: tuple[CausalFeatureRow, ...]
    causal: bool
    promotion_decision: PromotionDecision
    blockers: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    report_hash: str = ""

    @property
    def promotion_allowed(self) -> bool:
        return self.promotion_decision is PromotionDecision.REVIEWABLE and not self.blockers


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _history_key(event: ReplayEvent) -> tuple[str, str]:
    return (event.provider_health, event.route_shape_class)


def build_causal_feature_rows(
    events: Iterable[ReplayEvent], *, label_horizon_ns: int
) -> tuple[CausalFeatureRow, ...]:
    """Build rows without letting future terminal outcomes affect prior features."""

    if label_horizon_ns <= 0:
        raise ValueError("label_horizon_ns must be positive")

    ordered = sorted(events, key=lambda e: (e.available_at_ns, e.observed_at_ns, e.event_id))
    terminals = [e for e in ordered if e.event_type is EventType.TERMINAL]
    prior_outcomes: dict[tuple[str, str], list[int]] = {}
    rows: list[CausalFeatureRow] = []

    for event in ordered:
        if event.event_type is EventType.TERMINAL:
            prior_outcomes.setdefault(_history_key(event), []).append(int(event.label_value or 0))
            continue

        prior = prior_outcomes.get(_history_key(event), [])
        successes = sum(prior)
        failures = len(prior) - successes
        rate = int(successes * 1_000_000 / len(prior)) if prior else 0
        matching_terminals = [
            terminal
            for terminal in terminals
            if terminal.root_opportunity_id == event.root_opportunity_id
            and terminal.attempt_generation == event.attempt_generation
            and terminal.evidence_generation == event.evidence_generation
            and event.available_at_ns < terminal.available_at_ns <= event.available_at_ns + label_horizon_ns
        ]
        if matching_terminals:
            terminal = sorted(
                matching_terminals,
                key=lambda t: (t.available_at_ns, t.event_id),
            )[0]
            label_status = "LABELED_FIRST_TERMINAL"
            label_value = int(terminal.label_value or 0)
            terminal_event_id = terminal.event_id
        else:
            label_status = "UNLABELED_CENSORED"
            label_value = None
            terminal_event_id = None

        row_id = sha256_json(
            {
                "candidate_event_id": event.event_id,
                "root": event.root_opportunity_id,
                "attempt_generation": event.attempt_generation,
                "evidence_generation": event.evidence_generation,
                "available_at_ns": event.available_at_ns,
            }
        )[:24]
        rows.append(
            CausalFeatureRow(
                row_id=row_id,
                candidate_event_id=event.event_id,
                root_opportunity_id=event.root_opportunity_id,
                attempt_generation=event.attempt_generation,
                evidence_generation=event.evidence_generation,
                candidate_available_at_ns=event.available_at_ns,
                historical_success_count=successes,
                historical_failure_count=failures,
                historical_success_rate_ppm=rate,
                label_status=label_status,
                label_value=label_value,
                terminal_event_id=terminal_event_id,
            )
        )

    return tuple(rows)


def detect_temporal_leakage(events: Iterable[ReplayEvent], rows: Sequence[CausalFeatureRow]) -> tuple[str, ...]:
    """Return blockers if a row appears to use terminal evidence unavailable at row time."""

    terminal_by_key: dict[tuple[str, str], list[ReplayEvent]] = {}
    for event in events:
        if event.event_type is EventType.TERMINAL:
            terminal_by_key.setdefault(_history_key(event), []).append(event)

    blockers: list[str] = []
    candidates_by_id = {e.event_id: e for e in events if e.event_type is EventType.CANDIDATE}
    for row in rows:
        candidate = candidates_by_id[row.candidate_event_id]
        key = _history_key(candidate)
        allowed = [
            event
            for event in terminal_by_key.get(key, [])
            if event.available_at_ns <= row.candidate_available_at_ns
        ]
        allowed_successes = sum(int(event.label_value or 0) for event in allowed)
        allowed_failures = len(allowed) - allowed_successes
        if row.historical_success_count != allowed_successes or row.historical_failure_count != allowed_failures:
            blockers.append(f"temporal_leakage:{row.row_id}")
    return tuple(blockers)


def evaluate_replay_validity(
    *,
    manifest: ReplayCorpusManifest,
    split: EvaluationSplitEvidence,
    backtest: BacktestInputContract,
    events: Sequence[ReplayEvent],
    minimum_labeled: int = 1,
    allow_synthetic: bool = False,
) -> ReplayValidityReport:
    blockers: list[str] = []
    warnings: list[str] = []

    for name, validator in (
        ("manifest", manifest.validate),
        ("split", split.validate),
        ("backtest", backtest.validate),
    ):
        try:
            validator()
        except ValueError as exc:
            blockers.append(f"{name}:{exc}")

    if manifest.synthetic and not allow_synthetic:
        blockers.append("manifest:synthetic_corpus_not_allowed_for_promotion")

    rows = build_causal_feature_rows(events, label_horizon_ns=3_600_000_000_000)
    blockers.extend(detect_temporal_leakage(events, rows))

    labeled = [row for row in rows if row.label_status.startswith("LABELED")]
    if len(labeled) < minimum_labeled:
        blockers.append("replay:not_enough_labeled_rows")

    if manifest.replay_tier is ReplayTier.DECISION_REPLAY:
        warnings.append("decision_replay_is_not_market_replay")

    causal = not any(blocker.startswith("temporal_leakage:") for blocker in blockers)
    decision = PromotionDecision.REVIEWABLE if not blockers else PromotionDecision.BLOCKED
    report_payload = {
        "manifest": manifest,
        "split": split,
        "backtest": backtest,
        "row_count": len(rows),
        "causal": causal,
        "promotion_decision": decision.value,
        "blockers": blockers,
        "warnings": warnings,
    }
    return ReplayValidityReport(
        manifest=manifest,
        split=split,
        backtest=backtest,
        rows=rows,
        causal=causal,
        promotion_decision=decision,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        report_hash=sha256_json(report_payload),
    )


def assert_no_model_promotion(report: ReplayValidityReport) -> None:
    """Fail closed unless the replay package is independently reviewable."""

    if not report.promotion_allowed:
        raise ValueError(";".join(report.blockers) or "promotion blocked")
