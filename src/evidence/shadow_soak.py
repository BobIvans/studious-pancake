"""Deterministic shadow-soak and replay promotion evidence for PR-039.

This module is intentionally offline-only. It reads already persisted shadow
outcomes or JSONL replay records and produces a deterministic evidence bundle
that can be reviewed by a human before any later live-canary PR is considered.
It never opens RPC connections, never signs, and never submits transactions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "pr039.shadow-soak-evidence.v1"
RECONCILED_REASON = "SHADOW_RECONCILED"
KNOWN_MISMATCH_REASONS = frozenset(
    {
        "MESSAGE_HASH_MISMATCH",
        "SIGNATURE_MODE_MISMATCH",
        "ACCOUNT_KEYS_MISMATCH",
        "BALANCE_VECTOR_LENGTH_MISMATCH",
        "REPAYMENT_NOT_PROVEN",
        "FEE_MISMATCH",
    }
)
KNOWN_REASON_PREFIXES = (
    "PRE_",
    "RPC_",
    "SIMULATION_",
    "MESSAGE_",
    "SIGNATURE_",
    "ACCOUNT_",
    "BALANCE_",
    "TOKEN_",
    "OWNER_",
    "INCOMPLETE_",
    "REPAYMENT_",
    "FEE_",
    "COMPUTE_",
    "RENT_",
    "SHADOW_",
)


class EvidenceError(ValueError):
    """Raised when PR-039 evidence input is malformed."""


def _stable_json(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_json(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _strict_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value)
        raise EvidenceError(f"{field_name} must be an integer or integer string")
    return value


def _strict_bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str) and value.lower() in {"0", "1", "false", "true"}:
        return value.lower() in {"1", "true"}
    raise EvidenceError(f"{field_name} must be boolean-like")


def _strict_string(value: Any, *, field_name: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise EvidenceError(f"{field_name} must be a string")
    if not allow_empty and not value:
        raise EvidenceError(f"{field_name} must not be empty")
    return value


def _json_object(value: Any, *, field_name: str) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise EvidenceError(f"{field_name} must be valid JSON") from exc
    else:
        decoded = value
    if not isinstance(decoded, dict):
        raise EvidenceError(f"{field_name} must be a JSON object")
    return dict(decoded)


@dataclass(frozen=True, slots=True)
class ShadowOutcomeRecord:
    """Minimal immutable row used for PR-039 promotion evidence."""

    opportunity_id: str
    attempt_id: str
    plan_hash: str
    message_hash: str
    reconciliation_hash: str
    terminal_reason: str
    created_at: int
    completed_at: int
    context_slot: int | None = None
    response_hash: str = ""
    theoretical_quote_pnl: int = 0
    conservative_quote_pnl: int = 0
    simulated_executable_pnl: int = 0
    simulation_success: bool = False
    units_consumed: int | None = None
    fee_lamports: int = 0
    required_repayment: int = 0
    observed_repayment: int = 0
    repayment_proven: bool = False
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ShadowOutcomeRecord":
        context_slot = payload.get("context_slot")
        units_consumed = payload.get("units_consumed")
        return cls(
            opportunity_id=_strict_string(
                payload.get("opportunity_id"), field_name="opportunity_id"
            ),
            attempt_id=_strict_string(payload.get("attempt_id"), field_name="attempt_id"),
            plan_hash=_strict_string(payload.get("plan_hash"), field_name="plan_hash"),
            message_hash=_strict_string(
                payload.get("message_hash"), field_name="message_hash"
            ),
            reconciliation_hash=_strict_string(
                payload.get("reconciliation_hash"), field_name="reconciliation_hash"
            ),
            terminal_reason=_strict_string(
                payload.get("terminal_reason"), field_name="terminal_reason"
            ),
            created_at=_strict_int(payload.get("created_at"), field_name="created_at"),
            completed_at=_strict_int(
                payload.get("completed_at", payload.get("created_at")),
                field_name="completed_at",
            ),
            context_slot=(
                None
                if context_slot in (None, "")
                else _strict_int(context_slot, field_name="context_slot")
            ),
            response_hash=str(payload.get("response_hash") or ""),
            theoretical_quote_pnl=_strict_int(
                payload.get("theoretical_quote_pnl", 0),
                field_name="theoretical_quote_pnl",
            ),
            conservative_quote_pnl=_strict_int(
                payload.get("conservative_quote_pnl", 0),
                field_name="conservative_quote_pnl",
            ),
            simulated_executable_pnl=_strict_int(
                payload.get("simulated_executable_pnl", 0),
                field_name="simulated_executable_pnl",
            ),
            simulation_success=_strict_bool(
                payload.get("simulation_success", False), field_name="simulation_success"
            ),
            units_consumed=(
                None
                if units_consumed in (None, "")
                else _strict_int(units_consumed, field_name="units_consumed")
            ),
            fee_lamports=_strict_int(payload.get("fee_lamports", 0), field_name="fee_lamports"),
            required_repayment=_strict_int(
                payload.get("required_repayment", 0), field_name="required_repayment"
            ),
            observed_repayment=_strict_int(
                payload.get("observed_repayment", 0), field_name="observed_repayment"
            ),
            repayment_proven=_strict_bool(
                payload.get("repayment_proven", False), field_name="repayment_proven"
            ),
            provenance=_json_object(
                payload.get("provenance", payload.get("provenance_json", {})),
                field_name="provenance",
            ),
        )

    @property
    def latency_seconds(self) -> int:
        return max(0, self.completed_at - self.created_at)

    @property
    def replay_identity(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "message_hash": self.message_hash,
            "plan_hash": self.plan_hash,
            "reconciliation_hash": self.reconciliation_hash,
            "terminal_reason": self.terminal_reason,
            "simulated_executable_pnl": str(self.simulated_executable_pnl),
            "repayment_proven": self.repayment_proven,
        }

    @property
    def promotion_success(self) -> bool:
        return (
            self.terminal_reason == RECONCILED_REASON
            and self.simulation_success
            and self.repayment_proven
        )

    @property
    def false_positive(self) -> bool:
        return self.conservative_quote_pnl > 0 and not self.promotion_success

    @property
    def mismatch_reason(self) -> bool:
        return self.terminal_reason in KNOWN_MISMATCH_REASONS

    @property
    def classified_reason(self) -> bool:
        if self.terminal_reason == RECONCILED_REASON:
            return True
        return self.terminal_reason.startswith(KNOWN_REASON_PREFIXES)


@dataclass(frozen=True, slots=True)
class ShadowSoakThresholds:
    """Human-reviewed minimum evidence thresholds for PR-039."""

    minimum_samples: int = 1
    minimum_duration_seconds: int = 72 * 60 * 60
    maximum_unexplained_mismatches: int = 0
    maximum_unclassified_failures: int = 0
    maximum_false_positive_rate_bps: int = 0

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, int) or value < 0:
                raise EvidenceError(f"threshold {name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ReplayDigest:
    """Deterministic digest proving replay decisions are stable."""

    record_count: int
    digest: str

    @classmethod
    def from_records(cls, records: Sequence[ShadowOutcomeRecord]) -> "ReplayDigest":
        identities = sorted(
            (record.replay_identity for record in records),
            key=lambda item: (item["attempt_id"], item["message_hash"]),
        )
        return cls(record_count=len(records), digest=_sha256_json(identities))


@dataclass(frozen=True, slots=True)
class ShadowSoakMetrics:
    """Computed metrics for a shadow-soak corpus."""

    sample_count: int
    started_at: int | None
    completed_at: int | None
    duration_seconds: int
    success_count: int
    failure_count: int
    repayment_proven_count: int
    mismatch_count: int
    unclassified_failure_count: int
    false_positive_count: int
    false_positive_rate_bps: int
    conservative_quote_pnl_sum: int
    simulated_executable_pnl_sum: int
    pnl_prediction_error_sum: int
    max_latency_seconds: int
    total_fee_lamports: int
    reason_counts: Mapping[str, int]

    @classmethod
    def from_records(cls, records: Sequence[ShadowOutcomeRecord]) -> "ShadowSoakMetrics":
        if not records:
            return cls(
                sample_count=0,
                started_at=None,
                completed_at=None,
                duration_seconds=0,
                success_count=0,
                failure_count=0,
                repayment_proven_count=0,
                mismatch_count=0,
                unclassified_failure_count=0,
                false_positive_count=0,
                false_positive_rate_bps=0,
                conservative_quote_pnl_sum=0,
                simulated_executable_pnl_sum=0,
                pnl_prediction_error_sum=0,
                max_latency_seconds=0,
                total_fee_lamports=0,
                reason_counts={},
            )

        started_at = min(record.created_at for record in records)
        completed_at = max(record.completed_at for record in records)
        reason_counts: dict[str, int] = {}
        for record in records:
            reason_counts[record.terminal_reason] = reason_counts.get(record.terminal_reason, 0) + 1

        success_count = sum(1 for record in records if record.promotion_success)
        false_positive_count = sum(1 for record in records if record.false_positive)
        failure_count = len(records) - success_count
        false_positive_rate_bps = (
            false_positive_count * 10_000 // len(records) if records else 0
        )
        conservative_sum = sum(record.conservative_quote_pnl for record in records)
        simulated_sum = sum(record.simulated_executable_pnl for record in records)
        return cls(
            sample_count=len(records),
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=max(0, completed_at - started_at),
            success_count=success_count,
            failure_count=failure_count,
            repayment_proven_count=sum(1 for record in records if record.repayment_proven),
            mismatch_count=sum(1 for record in records if record.mismatch_reason),
            unclassified_failure_count=sum(
                1
                for record in records
                if not record.promotion_success and not record.classified_reason
            ),
            false_positive_count=false_positive_count,
            false_positive_rate_bps=false_positive_rate_bps,
            conservative_quote_pnl_sum=conservative_sum,
            simulated_executable_pnl_sum=simulated_sum,
            pnl_prediction_error_sum=simulated_sum - conservative_sum,
            max_latency_seconds=max(record.latency_seconds for record in records),
            total_fee_lamports=sum(record.fee_lamports for record in records),
            reason_counts=dict(sorted(reason_counts.items())),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PromotionEvidenceBundle:
    """Signed-by-digest PR-039 evidence bundle requiring human review."""

    corpus_id: str
    thresholds: ShadowSoakThresholds
    metrics: ShadowSoakMetrics
    replay_digest: ReplayDigest
    blocking_reasons: tuple[str, ...]
    human_review_required: bool = True
    live_enabled: bool = False
    schema_version: str = SCHEMA_VERSION

    @property
    def passed(self) -> bool:
        return not self.blocking_reasons

    @property
    def evidence_hash(self) -> str:
        return _sha256_json(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "corpus_id": self.corpus_id,
            "thresholds": asdict(self.thresholds),
            "metrics": self.metrics.to_dict(),
            "replay_digest": asdict(self.replay_digest),
            "blocking_reasons": list(self.blocking_reasons),
            "passed": self.passed,
            "human_review_required": self.human_review_required,
            "live_enabled": self.live_enabled,
        }
        if include_hash:
            payload["evidence_hash"] = self.evidence_hash
        return payload

    def to_json(self) -> str:
        return _stable_json(self.to_dict()) + "\n"


class ShadowSoakAnalyzer:
    """Build deterministic PR-039 promotion evidence from offline records."""

    def __init__(
        self,
        records: Iterable[ShadowOutcomeRecord],
        *,
        thresholds: ShadowSoakThresholds | None = None,
        corpus_id: str | None = None,
    ) -> None:
        self.records = tuple(sorted(records, key=lambda item: (item.created_at, item.attempt_id)))
        self.thresholds = thresholds or ShadowSoakThresholds()
        self.corpus_id = corpus_id or self._derive_corpus_id(self.records)

    @classmethod
    def from_jsonl(
        cls,
        path: str | Path,
        *,
        thresholds: ShadowSoakThresholds | None = None,
        corpus_id: str | None = None,
    ) -> "ShadowSoakAnalyzer":
        records: list[ShadowOutcomeRecord] = []
        for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvidenceError(f"invalid JSONL at line {line_number}") from exc
            if not isinstance(payload, dict):
                raise EvidenceError(f"JSONL line {line_number} must be an object")
            records.append(ShadowOutcomeRecord.from_mapping(payload))
        return cls(records, thresholds=thresholds, corpus_id=corpus_id)

    @classmethod
    def from_shadow_sqlite(
        cls,
        path: str | Path,
        *,
        thresholds: ShadowSoakThresholds | None = None,
        corpus_id: str | None = None,
    ) -> "ShadowSoakAnalyzer":
        sqlite_path = Path(path)
        if not sqlite_path.exists():
            raise EvidenceError(f"shadow SQLite database does not exist: {sqlite_path}")
        with sqlite3.connect(sqlite_path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """
                SELECT
                  opportunity_id,
                  attempt_id,
                  plan_hash,
                  message_hash,
                  response_hash,
                  reconciliation_hash,
                  created_at,
                  completed_at,
                  context_slot,
                  terminal_reason,
                  theoretical_quote_pnl,
                  conservative_quote_pnl,
                  simulated_executable_pnl,
                  simulation_success,
                  units_consumed,
                  fee_lamports,
                  required_repayment,
                  observed_repayment,
                  repayment_proven,
                  provenance_json
                FROM shadow_outcomes
                ORDER BY created_at, attempt_id
                """
            ).fetchall()
        records = [ShadowOutcomeRecord.from_mapping(dict(row)) for row in rows]
        return cls(records, thresholds=thresholds, corpus_id=corpus_id)

    def build_bundle(self) -> PromotionEvidenceBundle:
        metrics = ShadowSoakMetrics.from_records(self.records)
        replay_digest = ReplayDigest.from_records(self.records)
        blocking_reasons = self._blocking_reasons(metrics)
        return PromotionEvidenceBundle(
            corpus_id=self.corpus_id,
            thresholds=self.thresholds,
            metrics=metrics,
            replay_digest=replay_digest,
            blocking_reasons=tuple(blocking_reasons),
        )

    def _blocking_reasons(self, metrics: ShadowSoakMetrics) -> list[str]:
        reasons: list[str] = []
        if metrics.sample_count < self.thresholds.minimum_samples:
            reasons.append("SAMPLE_COUNT_BELOW_THRESHOLD")
        if metrics.duration_seconds < self.thresholds.minimum_duration_seconds:
            reasons.append("SOAK_DURATION_BELOW_THRESHOLD")
        if metrics.mismatch_count > self.thresholds.maximum_unexplained_mismatches:
            reasons.append("REPAYMENT_OR_SERIALIZATION_MISMATCH_PRESENT")
        if metrics.unclassified_failure_count > self.thresholds.maximum_unclassified_failures:
            reasons.append("UNCLASSIFIED_FAILURE_PRESENT")
        if metrics.false_positive_rate_bps > self.thresholds.maximum_false_positive_rate_bps:
            reasons.append("FALSE_POSITIVE_RATE_ABOVE_THRESHOLD")
        return reasons

    @staticmethod
    def _derive_corpus_id(records: Sequence[ShadowOutcomeRecord]) -> str:
        digest = ReplayDigest.from_records(records).digest
        return f"shadow-soak:{len(records)}:{digest[:16]}"
