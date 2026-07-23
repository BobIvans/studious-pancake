"""Canonical sender-free composition root for one bounded paper cycle."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from .model import (
    CandidateDecision, DualClock, PaperCandidate, PaperCycleReport,
    PaperOutcome, PaperPlatformError, RecordingError, SCHEMA_VERSION,
    hash_json, is_sha256, positive_clock,
)
from .source import (
    BoundedRecordedBatchSource, DEFAULT_MAX_BYTES, DEFAULT_MAX_ITEMS,
    DEFAULT_RECORDING_RESOURCE,
)
from .store import CanonicalPaperStore

DEFAULT_DB_PATH = Path(".runtime/canonical-paper.sqlite3")


@dataclass(frozen=True, slots=True)
class CanonicalPaperConfig:
    db_path: Path = DEFAULT_DB_PATH
    recording_path: Path | None = None
    config_digest: str = hashlib.sha256(b"canonical-paper-default-config").hexdigest()
    min_profit_lamports: int = 10_000
    max_slot_skew: int = 8
    max_bytes: int = DEFAULT_MAX_BYTES
    max_items: int = DEFAULT_MAX_ITEMS

    def __post_init__(self) -> None:
        object.__setattr__(self, "db_path", Path(self.db_path))
        if self.recording_path is not None:
            object.__setattr__(self, "recording_path", Path(self.recording_path))
        if not is_sha256(self.config_digest):
            raise ValueError("config_digest must be lowercase sha256")
        for name in ("min_profit_lamports", "max_slot_skew", "max_bytes", "max_items"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


class CanonicalPaperPlatform:
    def __init__(self, config: CanonicalPaperConfig, *, clock: DualClock | None = None) -> None:
        self.config, self.clock = config, clock or DualClock()

    def run_once(self) -> PaperCycleReport:
        start_utc = positive_clock(self.clock.utc_ns, "utc")
        start_mono = positive_clock(self.clock.monotonic_ns, "monotonic")
        source = BoundedRecordedBatchSource(
            self.config.recording_path,
            max_bytes=self.config.max_bytes,
            max_items=self.config.max_items,
        )
        try:
            batch = source.load()
            decisions = tuple(self._evaluate(candidate) for candidate in batch.candidates)
            accepted = any(d.outcome is PaperOutcome.PAPER_ACCEPTED for d in decisions)
            outcome = PaperOutcome.PAPER_ACCEPTED if accepted else PaperOutcome.PAPER_REJECTED
            reason = "paper_accepted" if accepted else "no_candidate_meets_conservative_profit"
            source_digest, source_name = batch.source_digest, batch.source_name
        except RecordingError as exc:
            outcome, reason, decisions = PaperOutcome.BLOCKED, exc.reason_code, ()
            source_name = str(self.config.recording_path or DEFAULT_RECORDING_RESOURCE)
            source_digest = hashlib.sha256(f"{source_name}:{reason}".encode()).hexdigest()
        end_mono = positive_clock(self.clock.monotonic_ns, "monotonic")
        end_utc = positive_clock(self.clock.utc_ns, "utc")
        duration = end_mono - start_mono
        if duration < 0:
            raise PaperPlatformError("monotonic clock moved backwards")
        cycle_id = hash_json(
            {"schema": SCHEMA_VERSION, "source_digest": source_digest, "config_digest": self.config.config_digest}
        )
        unsigned = {
            "schema_version": SCHEMA_VERSION, "cycle_id": cycle_id,
            "source_digest": source_digest, "config_digest": self.config.config_digest,
            "started_utc_ns": start_utc, "completed_utc_ns": end_utc,
            "duration_ns": duration, "outcome": outcome.value, "reason_code": reason,
            "decisions": [d.to_dict() for d in decisions], "db_path": str(self.config.db_path),
            "source_name": source_name, "live_enabled": False,
            "signer_loaded": False, "sender_loaded": False,
        }
        report = PaperCycleReport(
            cycle_id=cycle_id, source_digest=source_digest,
            config_digest=self.config.config_digest, started_utc_ns=start_utc,
            completed_utc_ns=end_utc, duration_ns=duration, outcome=outcome,
            reason_code=reason, decisions=decisions, db_path=str(self.config.db_path),
            source_name=source_name, report_hash=hash_json(unsigned),
        )
        with CanonicalPaperStore(self.config.db_path) as store:
            return store.commit(report)

    def _evaluate(self, candidate: PaperCandidate) -> CandidateDecision:
        outcome, reason = PaperOutcome.PAPER_ACCEPTED, "paper_candidate_accepted"
        if candidate.compiled_message_digest != candidate.simulation_message_digest:
            outcome, reason = PaperOutcome.PAPER_REJECTED, "rejected_message_simulation_digest_mismatch"
        elif candidate.repayment_lamports != candidate.principal_lamports + candidate.flash_fee_lamports:
            outcome, reason = PaperOutcome.PAPER_REJECTED, "rejected_repayment_formula_mismatch"
        elif candidate.rooted_slot > candidate.observed_slot:
            outcome, reason = PaperOutcome.PAPER_REJECTED, "rejected_root_after_observation"
        elif candidate.observed_slot - candidate.rooted_slot > self.config.max_slot_skew:
            outcome, reason = PaperOutcome.PAPER_REJECTED, "rejected_rooted_slot_skew"
        elif candidate.net_profit_lamports < self.config.min_profit_lamports:
            outcome, reason = PaperOutcome.PAPER_REJECTED, "rejected_conservative_profit_below_threshold"
        return CandidateDecision(
            candidate.candidate_id, candidate.digest, outcome, reason,
            candidate.net_profit_lamports,
        )
