"""Typed sender-free paper models and exact integer economics."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import time
from typing import Callable, Mapping, Sequence

SCHEMA_VERSION = "mega-pr-01.canonical-paper-platform.v1"
RECORDING_SCHEMA = "mega-pr-01.recorded-paper-batch.v1"


class PaperPlatformError(RuntimeError):
    reason_code = "paper_platform_error"


class RecordingError(PaperPlatformError):
    reason_code = "blocked_recording_invalid"


class PersistenceError(PaperPlatformError):
    reason_code = "blocked_persistence_failed"


class PaperOutcome(StrEnum):
    PAPER_ACCEPTED = "PAPER_ACCEPTED"
    PAPER_REJECTED = "PAPER_REJECTED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class DualClock:
    utc_ns: Callable[[], int] = time.time_ns
    monotonic_ns: Callable[[], int] = time.monotonic_ns


@dataclass(frozen=True, slots=True)
class PaperCandidate:
    candidate_id: str
    provider_evidence_digest: str
    compiled_message_digest: str
    simulation_message_digest: str
    principal_lamports: int
    flash_fee_lamports: int
    repayment_lamports: int
    simulated_output_lamports: int
    total_tx_fee_lamports: int
    rent_lamports: int
    tip_lamports: int
    safety_buffer_lamports: int
    observed_slot: int
    rooted_slot: int

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise RecordingError("candidate_id is required")
        for name in (
            "provider_evidence_digest",
            "compiled_message_digest",
            "simulation_message_digest",
        ):
            if not is_sha256(getattr(self, name)):
                raise RecordingError(f"{name} must be a lowercase sha256")
        for name in (
            "principal_lamports",
            "flash_fee_lamports",
            "repayment_lamports",
            "simulated_output_lamports",
            "total_tx_fee_lamports",
            "rent_lamports",
            "tip_lamports",
            "safety_buffer_lamports",
            "observed_slot",
            "rooted_slot",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RecordingError(f"{name} must be a non-negative integer")
        if self.principal_lamports <= 0 or self.simulated_output_lamports <= 0:
            raise RecordingError("principal and simulated output must be positive")

    @property
    def net_profit_lamports(self) -> int:
        return (
            self.simulated_output_lamports
            - self.repayment_lamports
            - self.total_tx_fee_lamports
            - self.rent_lamports
            - self.tip_lamports
            - self.safety_buffer_lamports
        )

    def to_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def digest(self) -> str:
        return hash_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    candidate_id: str
    candidate_digest: str
    outcome: PaperOutcome
    reason_code: str
    net_profit_lamports: int

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_digest": self.candidate_digest,
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "net_profit_lamports": self.net_profit_lamports,
        }


@dataclass(frozen=True, slots=True)
class PaperCycleReport:
    cycle_id: str
    source_digest: str
    config_digest: str
    started_utc_ns: int
    completed_utc_ns: int
    duration_ns: int
    outcome: PaperOutcome
    reason_code: str
    decisions: tuple[CandidateDecision, ...]
    db_path: str
    source_name: str
    report_hash: str
    live_enabled: bool = False
    signer_loaded: bool = False
    sender_loaded: bool = False
    input_identity: str = ""
    run_sequence: int = 0

    def __post_init__(self) -> None:
        if not is_sha256(self.cycle_id):
            raise ValueError("cycle_id must be lowercase sha256")
        for name in ("source_digest", "config_digest", "report_hash"):
            if not is_sha256(getattr(self, name)):
                raise ValueError(f"{name} must be lowercase sha256")
        if self.input_identity and not is_sha256(self.input_identity):
            raise ValueError("input_identity must be lowercase sha256 when present")
        if (
            isinstance(self.run_sequence, bool)
            or not isinstance(self.run_sequence, int)
            or self.run_sequence < 0
        ):
            raise ValueError("run_sequence must be a non-negative integer")
        if self.live_enabled or self.signer_loaded or self.sender_loaded:
            raise ValueError("paper report cannot expose live/signer/sender")
        if self.completed_utc_ns < self.started_utc_ns or self.duration_ns < 0:
            raise ValueError("invalid report clock ordering")

    @property
    def accepted_count(self) -> int:
        return sum(d.outcome is PaperOutcome.PAPER_ACCEPTED for d in self.decisions)

    @property
    def rejected_count(self) -> int:
        return sum(d.outcome is PaperOutcome.PAPER_REJECTED for d in self.decisions)

    def unsigned_payload(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "cycle_id": self.cycle_id,
            "input_identity": self.input_identity,
            "run_sequence": self.run_sequence,
            "source_digest": self.source_digest,
            "config_digest": self.config_digest,
            "started_utc_ns": self.started_utc_ns,
            "completed_utc_ns": self.completed_utc_ns,
            "duration_ns": self.duration_ns,
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "decisions": [d.to_dict() for d in self.decisions],
            "db_path": self.db_path,
            "source_name": self.source_name,
            "live_enabled": False,
            "signer_loaded": False,
            "sender_loaded": False,
        }

    def to_dict(self) -> dict[str, object]:
        payload = self.unsigned_payload()
        payload.update(
            accepted_count=self.accepted_count,
            rejected_count=self.rejected_count,
            report_hash=self.report_hash,
        )
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "PaperCycleReport":
        raw = payload.get("decisions", ())
        if not isinstance(raw, Sequence):
            raise PersistenceError("stored decisions are invalid")
        decisions = tuple(
            CandidateDecision(
                candidate_id=str(item["candidate_id"]),
                candidate_digest=str(item["candidate_digest"]),
                outcome=PaperOutcome(str(item["outcome"])),
                reason_code=str(item["reason_code"]),
                net_profit_lamports=int(item["net_profit_lamports"]),
            )
            for item in raw
            if isinstance(item, Mapping)
        )
        report = cls(
            cycle_id=str(payload["cycle_id"]),
            source_digest=str(payload["source_digest"]),
            config_digest=str(payload["config_digest"]),
            started_utc_ns=int(payload["started_utc_ns"]),
            completed_utc_ns=int(payload["completed_utc_ns"]),
            duration_ns=int(payload["duration_ns"]),
            outcome=PaperOutcome(str(payload["outcome"])),
            reason_code=str(payload["reason_code"]),
            decisions=decisions,
            db_path=str(payload["db_path"]),
            source_name=str(payload["source_name"]),
            report_hash=str(payload["report_hash"]),
            live_enabled=bool(payload.get("live_enabled", False)),
            signer_loaded=bool(payload.get("signer_loaded", False)),
            sender_loaded=bool(payload.get("sender_loaded", False)),
            input_identity=str(payload.get("input_identity", "")),
            run_sequence=int(payload.get("run_sequence", 0)),
        )
        if hash_json(report.unsigned_payload()) != report.report_hash:
            if not _legacy_report_hash_matches(payload):
                raise PersistenceError("stored report hash mismatch")
        return report


def strict_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RecordingError(f"{name} must be an integer")
    return value


def positive_clock(clock: Callable[[], int], name: str) -> int:
    value = clock()
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PaperPlatformError(f"{name} clock returned invalid value")
    return value


def is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(ch in "0123456789abcdef" for ch in value)
        and len(set(value)) > 1
    )


def hash_json(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _legacy_report_hash_matches(payload: Mapping[str, object]) -> bool:
    """Accept already-written V1 reports while rejecting corrupt rows."""

    if "input_identity" in payload or "run_sequence" in payload:
        return False
    legacy = {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": payload["cycle_id"],
        "source_digest": payload["source_digest"],
        "config_digest": payload["config_digest"],
        "started_utc_ns": int(payload["started_utc_ns"]),
        "completed_utc_ns": int(payload["completed_utc_ns"]),
        "duration_ns": int(payload["duration_ns"]),
        "outcome": str(payload["outcome"]),
        "reason_code": str(payload["reason_code"]),
        "decisions": list(payload.get("decisions", ())),
        "db_path": str(payload["db_path"]),
        "source_name": str(payload["source_name"]),
        "live_enabled": False,
        "signer_loaded": False,
        "sender_loaded": False,
    }
    return hash_json(legacy) == str(payload.get("report_hash", ""))
