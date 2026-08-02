"""Roadmap PR-200 sender-free continuous paper/shadow replay harness."""

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Callable, Iterable, Mapping, MutableMapping, Sequence


_FORBIDDEN_MODULE_PREFIXES = (
    "flashloan_isolated_signer",
    "isolated_signer_service",
    "src.execution.senders",
    "src.execution.live_control",
    "src.submission.sender",
    "src.submission.jito_sender",
    "src.submission.rpc_sender",
    "solders.keypair",
    "solana.keypair",
)


class PR200Mode(StrEnum):
    PAPER = "paper"
    SHADOW = "shadow"


class PR200DatasetSource(StrEnum):
    SYNTHETIC = "synthetic"
    RECORDED = "recorded"
    SIMULATED = "simulated"


class PR200RejectionCode(StrEnum):
    SOURCE_NOT_ALLOWED = "source_not_allowed"
    DUPLICATE_TERMINAL_OUTCOME = "duplicate_terminal_outcome"
    SILENT_EXCEPTION_BLOCKED = "silent_exception_blocked"


class PR200TerminalStatus(StrEnum):
    SIMULATED_SUCCESS = "simulated_success"
    REJECTED = "rejected"


class PR200InvariantViolation(RuntimeError):
    """Raised when paper/shadow would violate the sender-free contract."""


@dataclass(frozen=True, slots=True)
class PR200RunIdentity:
    release_hash: str
    config_hash: str
    code_hash: str
    data_hash: str

    def __post_init__(self) -> None:
        for name, value in self.as_dict().items():
            _require_digestish(name, value)

    def as_dict(self) -> dict[str, str]:
        return {
            "release_hash": self.release_hash,
            "config_hash": self.config_hash,
            "code_hash": self.code_hash,
            "data_hash": self.data_hash,
        }

    @property
    def run_hash(self) -> str:
        return _stable_hash(self.as_dict())


@dataclass(frozen=True, slots=True)
class PR200CandidateEvent:
    candidate_id: str
    source: PR200DatasetSource
    payload: Mapping[str, object]
    received_at_millis: int

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("candidate_id is required")
        if self.received_at_millis < 0:
            raise ValueError("received_at_millis must be non-negative")
        if self.source not in {PR200DatasetSource.SYNTHETIC, PR200DatasetSource.RECORDED}:
            raise PR200InvariantViolation("paper input must be synthetic or recorded")

    @property
    def evidence_hash(self) -> str:
        return _stable_hash(
            {
                "candidate_id": self.candidate_id,
                "source": self.source.value,
                "payload": self.payload,
                "received_at_millis": self.received_at_millis,
            }
        )


@dataclass(frozen=True, slots=True)
class PR200AttemptOutcome:
    attempt_id: str
    candidate_id: str
    mode: PR200Mode
    status: PR200TerminalStatus
    source: PR200DatasetSource
    evidence_hash: str
    simulated_pnl_lamports: int
    rejection_code: str | None = None

    def __post_init__(self) -> None:
        if self.source is not PR200DatasetSource.SIMULATED:
            raise PR200InvariantViolation("terminal paper outcomes must be simulated")
        if self.status is PR200TerminalStatus.REJECTED and not self.rejection_code:
            raise PR200InvariantViolation("rejected outcomes require a typed code")
        if self.status is PR200TerminalStatus.SIMULATED_SUCCESS and self.rejection_code:
            raise PR200InvariantViolation("successful outcomes cannot carry a rejection")
        if self.simulated_pnl_lamports < 0:
            raise PR200InvariantViolation("negative simulated PnL is not accepted")
        _require_digestish("evidence_hash", self.evidence_hash)

    @property
    def outcome_hash(self) -> str:
        return _stable_hash(
            {
                "attempt_id": self.attempt_id,
                "candidate_id": self.candidate_id,
                "mode": self.mode.value,
                "status": self.status.value,
                "source": self.source.value,
                "evidence_hash": self.evidence_hash,
                "simulated_pnl_lamports": self.simulated_pnl_lamports,
                "rejection_code": self.rejection_code,
            }
        )


@dataclass(frozen=True, slots=True)
class PR200ContinuousConfig:
    mode: PR200Mode = PR200Mode.PAPER
    max_cycles: int = 1
    cycle_deadline_millis: int = 1_000
    max_events_per_cycle: int = 64
    output_dir: Path = Path(".runtime/pr200-paper")

    def __post_init__(self) -> None:
        if self.max_cycles <= 0 or self.cycle_deadline_millis <= 0:
            raise ValueError("cycle settings must be positive")
        if self.max_events_per_cycle <= 0:
            raise ValueError("max_events_per_cycle must be positive")


@dataclass(frozen=True, slots=True)
class PR200ChaosScenario:
    name: str
    fail_after_events: int | None = None
    duplicate_event_ids: frozenset[str] = frozenset()
    db_full_after_writes: int | None = None

    def should_kill_after(self, processed_events: int) -> bool:
        return self.fail_after_events is not None and processed_events >= self.fail_after_events


@dataclass(slots=True)
class PR200ServiceReport:
    run_identity: PR200RunIdentity
    mode: PR200Mode
    cycles_completed: int
    accepted_events: int
    terminal_outcomes: int
    duplicate_terminal_outcomes: int
    rejection_counters: Counter[str] = field(default_factory=Counter)
    latency_samples_millis: list[int] = field(default_factory=list)
    invariant_violations: list[str] = field(default_factory=list)
    sender_free_modules_checked: tuple[str, ...] = _FORBIDDEN_MODULE_PREFIXES

    @property
    def artifact_hash(self) -> str:
        return _stable_hash(
            {
                "run_hash": self.run_identity.run_hash,
                "mode": self.mode.value,
                "cycles_completed": self.cycles_completed,
                "accepted_events": self.accepted_events,
                "terminal_outcomes": self.terminal_outcomes,
                "duplicate_terminal_outcomes": self.duplicate_terminal_outcomes,
                "rejection_counters": dict(sorted(self.rejection_counters.items())),
                "latency_samples_millis": sorted(self.latency_samples_millis),
                "invariant_violations": tuple(self.invariant_violations),
            }
        )

    def to_dict(self) -> dict[str, object]:
        samples = sorted(self.latency_samples_millis)
        return {
            "schema_version": "pr200.service_report.v1",
            **self.run_identity.as_dict(),
            "run_hash": self.run_identity.run_hash,
            "mode": self.mode.value,
            "cycles_completed": self.cycles_completed,
            "accepted_events": self.accepted_events,
            "terminal_outcomes": self.terminal_outcomes,
            "duplicate_terminal_outcomes": self.duplicate_terminal_outcomes,
            "rejection_counters": dict(sorted(self.rejection_counters.items())),
            "latency_millis": {
                "p50": _percentile(samples, 0.50),
                "p95": _percentile(samples, 0.95),
                "p99": _percentile(samples, 0.99),
            },
            "invariant_violations": tuple(self.invariant_violations),
            "sender_free_modules_checked": self.sender_free_modules_checked,
            "soak_artifact_hash": self.artifact_hash,
        }


class PR200ImmutableJsonlStore:
    """Append-only JSONL evidence with duplicate terminal detection."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._terminal_by_attempt: dict[str, str] = {}

    def append(self, dataset: str, payload: Mapping[str, object]) -> None:
        with (self.root / f"{dataset}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(_canonical_json(payload) + "\n")

    def record_event(self, event: PR200CandidateEvent) -> None:
        self.append(
            "events",
            {
                "schema_version": "pr200.event.v1",
                "candidate_id": event.candidate_id,
                "source": event.source.value,
                "payload": event.payload,
                "received_at_millis": event.received_at_millis,
                "evidence_hash": event.evidence_hash,
            },
        )

    def record_outcome(self, outcome: PR200AttemptOutcome) -> bool:
        previous = self._terminal_by_attempt.get(outcome.attempt_id)
        if previous is not None:
            return previous == outcome.outcome_hash
        self._terminal_by_attempt[outcome.attempt_id] = outcome.outcome_hash
        self.append(
            "outcomes",
            {
                "schema_version": "pr200.outcome.v1",
                "attempt_id": outcome.attempt_id,
                "candidate_id": outcome.candidate_id,
                "mode": outcome.mode.value,
                "status": outcome.status.value,
                "source": outcome.source.value,
                "evidence_hash": outcome.evidence_hash,
                "simulated_pnl_lamports": outcome.simulated_pnl_lamports,
                "rejection_code": outcome.rejection_code,
                "outcome_hash": outcome.outcome_hash,
            },
        )
        return True

    def record_report(self, report: PR200ServiceReport) -> None:
        self.append("reports", report.to_dict())


class PR200DeterministicReplayHarness:
    def __init__(self, run_identity: PR200RunIdentity, mode: PR200Mode) -> None:
        self.run_identity = run_identity
        self.mode = mode

    def attempt_id(self, event: PR200CandidateEvent, attempt_generation: int = 0) -> str:
        return _stable_hash(
            {
                "run_hash": self.run_identity.run_hash,
                "candidate_id": event.candidate_id,
                "evidence_hash": event.evidence_hash,
                "attempt_generation": attempt_generation,
                "mode": self.mode.value,
            }
        )

    def simulate(self, event: PR200CandidateEvent) -> PR200AttemptOutcome:
        gross = _coerce_int(event.payload.get("simulated_pnl_lamports", 0))
        if gross <= 0:
            return PR200AttemptOutcome(
                attempt_id=self.attempt_id(event),
                candidate_id=event.candidate_id,
                mode=self.mode,
                status=PR200TerminalStatus.REJECTED,
                source=PR200DatasetSource.SIMULATED,
                evidence_hash=event.evidence_hash,
                simulated_pnl_lamports=0,
                rejection_code="no_positive_simulated_pnl",
            )
        return PR200AttemptOutcome(
            attempt_id=self.attempt_id(event),
            candidate_id=event.candidate_id,
            mode=self.mode,
            status=PR200TerminalStatus.SIMULATED_SUCCESS,
            source=PR200DatasetSource.SIMULATED,
            evidence_hash=event.evidence_hash,
            simulated_pnl_lamports=gross,
        )


class PR200ContinuousPaperService:
    """Bounded continuous paper/shadow loop with sender-free evidence output."""

    def __init__(
        self,
        config: PR200ContinuousConfig,
        run_identity: PR200RunIdentity,
        events: Iterable[PR200CandidateEvent],
        *,
        store: PR200ImmutableJsonlStore | None = None,
        clock_millis: Callable[[], int] | None = None,
        chaos: PR200ChaosScenario | None = None,
    ) -> None:
        self.config = config
        self._events = iter(events)
        self._store = store or PR200ImmutableJsonlStore(config.output_dir)
        self._clock_millis = clock_millis or (lambda: int(time.time() * 1000))
        self._chaos = chaos
        self._replay = PR200DeterministicReplayHarness(run_identity, config.mode)
        self._seen_terminal: MutableMapping[str, str] = {}
        self._import_baseline = frozenset(sys.modules)
        self._run_identity = run_identity

    def run(self) -> PR200ServiceReport:
        _assert_sender_free_process(self._import_baseline)
        report = PR200ServiceReport(
            run_identity=self._run_identity,
            mode=self.config.mode,
            cycles_completed=0,
            accepted_events=0,
            terminal_outcomes=0,
            duplicate_terminal_outcomes=0,
        )
        for _ in range(self.config.max_cycles):
            cycle_started = self._clock_millis()
            processed_this_cycle = 0
            while processed_this_cycle < self.config.max_events_per_cycle:
                if self._clock_millis() - cycle_started > self.config.cycle_deadline_millis:
                    break
                try:
                    event = next(self._events)
                except StopIteration:
                    break
                try:
                    self._process_event(event, report)
                except Exception as exc:  # noqa: BLE001 - converted to typed evidence
                    code = PR200RejectionCode.SILENT_EXCEPTION_BLOCKED.value
                    report.rejection_counters[code] += 1
                    report.invariant_violations.append(type(exc).__name__)
                processed_this_cycle += 1
                if self._chaos and self._chaos.should_kill_after(report.accepted_events):
                    report.invariant_violations.append("chaos_kill_after_events")
                    self._store.record_report(report)
                    return report
            report.cycles_completed += 1
        self._store.record_report(report)
        return report

    def _process_event(
        self, event: PR200CandidateEvent, report: PR200ServiceReport
    ) -> None:
        if event.source not in {PR200DatasetSource.SYNTHETIC, PR200DatasetSource.RECORDED}:
            report.rejection_counters[PR200RejectionCode.SOURCE_NOT_ALLOWED.value] += 1
            return
        started = self._clock_millis()
        self._store.record_event(event)
        report.accepted_events += 1
        outcome = self._replay.simulate(event)
        previous = self._seen_terminal.get(outcome.attempt_id)
        if previous is not None:
            report.duplicate_terminal_outcomes += 1
            if previous != outcome.outcome_hash:
                code = PR200RejectionCode.DUPLICATE_TERMINAL_OUTCOME.value
                report.rejection_counters[code] += 1
                report.invariant_violations.append("conflicting_terminal_outcome")
            return
        if not self._store.record_outcome(outcome):
            report.duplicate_terminal_outcomes += 1
            return
        self._seen_terminal[outcome.attempt_id] = outcome.outcome_hash
        report.terminal_outcomes += 1
        if outcome.rejection_code:
            report.rejection_counters[outcome.rejection_code] += 1
        report.latency_samples_millis.append(max(0, self._clock_millis() - started))


def build_pr200_run_identity(
    *,
    release: str,
    config: Mapping[str, object],
    code_files: Mapping[str, str],
    events: Sequence[Mapping[str, object]],
) -> PR200RunIdentity:
    return PR200RunIdentity(
        release_hash=_stable_hash({"release": release}),
        config_hash=_stable_hash(config),
        code_hash=_stable_hash(code_files),
        data_hash=_stable_hash({"events": events}),
    )


def _assert_sender_free_process(import_baseline: frozenset[str]) -> None:
    for module_name in sorted(set(sys.modules) - import_baseline):
        if module_name.startswith(_FORBIDDEN_MODULE_PREFIXES):
            raise PR200InvariantViolation(
                f"sender-free process imported forbidden module: {module_name}"
            )


def _coerce_int(value: object) -> int:
    if isinstance(value, bool):
        raise PR200InvariantViolation("boolean values are not valid amounts")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    raise PR200InvariantViolation("amount must be an integer-like value")


def _require_digestish(field_name: str, value: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field_name} must be a 64-character hex digest")
    int(value, 16)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _stable_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _percentile(values: Sequence[int], quantile: float) -> int:
    if not values:
        return 0
    index = min(len(values) - 1, max(0, round((len(values) - 1) * quantile)))
    return int(values[index])
