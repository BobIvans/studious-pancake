"""AGG-02 causal market-data contracts.

The contracts in this module are intentionally sender-free. They bind public
observations, availability time and dependency generations without creating a
second runtime, quota authority, capital authority or financial ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Iterable, Mapping

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class Agg02Error(ValueError):
    """Fail-closed AGG-02 validation error with a stable reason code."""

    def __init__(self, reason_code: str, message: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(message or reason_code)


def _text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Agg02Error("AGG02_INVALID_TEXT", f"{field} must be non-empty text")
    return value


def _integer(value: int, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise Agg02Error(
            "AGG02_INVALID_INTEGER",
            f"{field} must be an integer >= {minimum}",
        )
    return value


def _sha256(value: str, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise Agg02Error("AGG02_INVALID_SHA256", f"{field} must be sha256 hex")
    return value


def canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise Agg02Error("AGG02_NON_CANONICAL_VALUE") from exc


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RawEventEnvelope:
    """Immutable causal envelope around raw provider bytes.

    available_at_ms is the earliest time the event may be used by a decision.
    It is deliberately distinct from source event time and slot. Missing source
    sequence/time stays None rather than being invented.
    """

    event_id: str
    source_id: str
    chain_id: str
    payload_sha256: str
    received_at_ms: int
    available_at_ms: int
    decoder_version: str
    cursor_source: str
    cursor_partition: str
    cursor_offset: int
    reconnect_epoch: int
    slot: int | None = None
    commitment: str = "unknown"
    source_event_time_ms: int | None = None
    source_sequence: int | None = None
    uncertainty_ms: int = 0
    gap_before: bool = False

    def __post_init__(self) -> None:
        for field, value in (
            ("event_id", self.event_id),
            ("source_id", self.source_id),
            ("chain_id", self.chain_id),
            ("decoder_version", self.decoder_version),
            ("cursor_source", self.cursor_source),
            ("cursor_partition", self.cursor_partition),
            ("commitment", self.commitment),
        ):
            _text(value, field)
        _sha256(self.payload_sha256, "payload_sha256")
        _integer(self.received_at_ms, "received_at_ms")
        _integer(self.available_at_ms, "available_at_ms")
        if self.available_at_ms < self.received_at_ms:
            raise Agg02Error("AGG02_AVAILABLE_BEFORE_RECEIVE")
        _integer(self.cursor_offset, "cursor_offset")
        _integer(self.reconnect_epoch, "reconnect_epoch")
        _integer(self.uncertainty_ms, "uncertainty_ms")
        if self.slot is not None:
            _integer(self.slot, "slot")
        if self.source_event_time_ms is not None:
            _integer(self.source_event_time_ms, "source_event_time_ms")
        if self.source_sequence is not None:
            _integer(self.source_sequence, "source_sequence")
        if not isinstance(self.gap_before, bool):
            raise Agg02Error("AGG02_INVALID_GAP_FLAG")

    @property
    def cursor_key(self) -> str:
        return f"{self.cursor_source}:{self.cursor_partition}"

    @property
    def identity(self) -> str:
        return canonical_hash(
            {
                "event_id": self.event_id,
                "source_id": self.source_id,
                "chain_id": self.chain_id,
                "payload_sha256": self.payload_sha256,
                "received_at_ms": self.received_at_ms,
                "available_at_ms": self.available_at_ms,
                "decoder_version": self.decoder_version,
                "cursor": {
                    "source": self.cursor_source,
                    "partition": self.cursor_partition,
                    "offset": self.cursor_offset,
                    "epoch": self.reconnect_epoch,
                },
                "slot": self.slot,
                "commitment": self.commitment,
                "source_event_time_ms": self.source_event_time_ms,
                "source_sequence": self.source_sequence,
                "uncertainty_ms": self.uncertainty_ms,
                "gap_before": self.gap_before,
            }
        )


@dataclass(frozen=True, slots=True)
class StateRecord:
    dependency_id: str
    generation: str
    available_at_ms: int
    value_sha256: str
    payload_json: str
    slot: int | None = None
    quarantined: bool = False
    gap_affected: bool = False

    def __post_init__(self) -> None:
        _text(self.dependency_id, "dependency_id")
        _text(self.generation, "generation")
        _integer(self.available_at_ms, "available_at_ms")
        _sha256(self.value_sha256, "value_sha256")
        _text(self.payload_json, "payload_json")
        try:
            payload = json.loads(self.payload_json)
        except json.JSONDecodeError as exc:
            raise Agg02Error("AGG02_INVALID_STATE_PAYLOAD") from exc
        if canonical_json(payload) != self.payload_json:
            raise Agg02Error("AGG02_NON_CANONICAL_STATE_PAYLOAD")
        if hashlib.sha256(self.payload_json.encode()).hexdigest() != self.value_sha256:
            raise Agg02Error("AGG02_STATE_HASH_MISMATCH")
        if self.slot is not None:
            _integer(self.slot, "slot")
        if not isinstance(self.quarantined, bool) or not isinstance(
            self.gap_affected, bool
        ):
            raise Agg02Error("AGG02_INVALID_STATE_QUALITY_FLAG")

    @classmethod
    def from_mapping(
        cls,
        *,
        dependency_id: str,
        generation: str,
        available_at_ms: int,
        payload: Mapping[str, object],
        slot: int | None = None,
        quarantined: bool = False,
        gap_affected: bool = False,
    ) -> "StateRecord":
        encoded = canonical_json(dict(payload))
        return cls(
            dependency_id=dependency_id,
            generation=generation,
            available_at_ms=available_at_ms,
            value_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
            payload_json=encoded,
            slot=slot,
            quarantined=quarantined,
            gap_affected=gap_affected,
        )


@dataclass(frozen=True, slots=True)
class StateFrame:
    decision_time_ms: int
    records: tuple[StateRecord, ...]
    required_dependencies: tuple[str, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        _integer(self.decision_time_ms, "decision_time_ms")
        if not self.records:
            raise Agg02Error("AGG02_EMPTY_STATE_FRAME")
        if len(self.required_dependencies) != len(set(self.required_dependencies)):
            raise Agg02Error("AGG02_DUPLICATE_FRAME_DEPENDENCY")
        _sha256(self.fingerprint, "fingerprint")
        if any(record.available_at_ms > self.decision_time_ms for record in self.records):
            raise Agg02Error("AGG02_FUTURE_STATE_IN_FRAME")
        if any(record.quarantined for record in self.records):
            raise Agg02Error("AGG02_QUARANTINED_STATE_IN_FRAME")
        if any(record.gap_affected for record in self.records):
            raise Agg02Error("AGG02_GAP_AFFECTED_STATE_IN_FRAME")
        observed = {record.dependency_id for record in self.records}
        missing = set(self.required_dependencies) - observed
        if missing:
            raise Agg02Error(
                "AGG02_FRAME_DEPENDENCY_MISSING",
                "missing dependencies: " + ",".join(sorted(missing)),
            )


def build_state_frame(
    records: Iterable[StateRecord],
    *,
    required_dependencies: Iterable[str],
    decision_time_ms: int,
) -> StateFrame:
    """Point-in-time materialization that never backfills from the future."""

    _integer(decision_time_ms, "decision_time_ms")
    required = tuple(sorted(set(required_dependencies)))
    if not required:
        raise Agg02Error("AGG02_FRAME_REQUIRES_DEPENDENCIES")
    latest: dict[str, StateRecord] = {}
    for record in records:
        if record.available_at_ms > decision_time_ms:
            continue
        current = latest.get(record.dependency_id)
        current_slot = -1 if current is None or current.slot is None else current.slot
        record_slot = -1 if record.slot is None else record.slot
        if current is None or (record.available_at_ms, record_slot, record.value_sha256) > (
            current.available_at_ms,
            current_slot,
            current.value_sha256,
        ):
            latest[record.dependency_id] = record
    selected = tuple(latest[key] for key in required if key in latest)
    fingerprint = canonical_hash(
        {
            "decision_time_ms": decision_time_ms,
            "required": required,
            "records": [
                {
                    "dependency_id": item.dependency_id,
                    "generation": item.generation,
                    "available_at_ms": item.available_at_ms,
                    "slot": item.slot,
                    "value_sha256": item.value_sha256,
                }
                for item in selected
            ],
        }
    )
    return StateFrame(decision_time_ms, selected, required, fingerprint)


def as_of_join(
    records: Iterable[StateRecord],
    *,
    dependency_ids: Iterable[str],
    decision_time_ms: int,
) -> Mapping[str, StateRecord]:
    frame = build_state_frame(
        records,
        required_dependencies=dependency_ids,
        decision_time_ms=decision_time_ms,
    )
    return {record.dependency_id: record for record in frame.records}
