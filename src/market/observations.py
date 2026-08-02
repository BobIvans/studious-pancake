"""Canonical watermarked market observations for MPR-042.

This module is the installed market-truth authority.  It keeps optimistic and
conservative economics separate, binds every observation to source/generation
identity, and publishes only immutable batches with an explicit completeness
verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import time
import inspect
from typing import Iterable, Iterator, Protocol


class ObservationError(ValueError):
    """Raised when market evidence violates the canonical observation contract."""


class CompletenessState(str, Enum):
    COMPLETE = "complete"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


class CorrectionKind(str, Enum):
    ORIGINAL = "original"
    CORRECTION = "correction"
    RETRACTION = "retraction"


@dataclass(frozen=True, slots=True)
class ObservationGeneration:
    """Closed generation identity for decision-affecting market evidence."""

    genesis_hash: str = "unknown"
    provider_generation: str = "unknown"
    asset_generation: str = "unknown"
    policy_generation: str = "unknown"
    code_generation: str = "unknown"

    def __post_init__(self) -> None:
        for name, value in (
            ("genesis_hash", self.genesis_hash),
            ("provider_generation", self.provider_generation),
            ("asset_generation", self.asset_generation),
            ("policy_generation", self.policy_generation),
            ("code_generation", self.code_generation),
        ):
            if not isinstance(value, str) or not value:
                raise ObservationError(f"{name} must be non-empty text")

    @property
    def identity(self) -> str:
        payload = {
            "asset": self.asset_generation,
            "code": self.code_generation,
            "genesis": self.genesis_hash,
            "policy": self.policy_generation,
            "provider": self.provider_generation,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceCursor:
    source: str
    partition: str
    offset: int
    slot: int
    reconnect_epoch: int = 0

    def __post_init__(self) -> None:
        if not self.source or not self.partition:
            raise ObservationError("source cursor identity is required")
        if type(self.offset) is not int or self.offset < 0:
            raise ObservationError(
                "source cursor offset must be a non-negative integer"
            )
        if type(self.slot) is not int or self.slot < 0:
            raise ObservationError("source cursor slot must be a non-negative integer")
        if type(self.reconnect_epoch) is not int or self.reconnect_epoch < 0:
            raise ObservationError(
                "source cursor reconnect_epoch must be a non-negative integer"
            )

    @property
    def key(self) -> str:
        return f"{self.source}:{self.partition}"


@dataclass(frozen=True, slots=True)
class ObservationWatermark:
    """A deterministic lower bound on the source evidence included in a batch."""

    cursors: tuple[SourceCursor, ...]
    minimum_slot: int
    maximum_slot: int
    reconnect_epoch: int

    def __post_init__(self) -> None:
        if not self.cursors:
            raise ObservationError("watermark requires at least one source cursor")
        keys = tuple(cursor.key for cursor in self.cursors)
        if len(keys) != len(set(keys)):
            raise ObservationError("watermark source cursors must be unique")
        if type(self.minimum_slot) is not int or self.minimum_slot < 0:
            raise ObservationError("watermark minimum_slot is invalid")
        if type(self.maximum_slot) is not int or self.maximum_slot < self.minimum_slot:
            raise ObservationError("watermark maximum_slot is invalid")
        if type(self.reconnect_epoch) is not int or self.reconnect_epoch < 0:
            raise ObservationError("watermark reconnect_epoch is invalid")
        if any(cursor.slot < self.minimum_slot for cursor in self.cursors):
            raise ObservationError("watermark minimum_slot exceeds a source cursor")
        if any(cursor.slot > self.maximum_slot for cursor in self.cursors):
            raise ObservationError("watermark maximum_slot is below a source cursor")
        if any(
            cursor.reconnect_epoch != self.reconnect_epoch for cursor in self.cursors
        ):
            raise ObservationError("watermark mixes reconnect epochs")

    @property
    def identity(self) -> str:
        payload = {
            "cursors": [
                {
                    "key": cursor.key,
                    "offset": cursor.offset,
                    "slot": cursor.slot,
                    "reconnect_epoch": cursor.reconnect_epoch,
                }
                for cursor in sorted(self.cursors, key=lambda item: item.key)
            ],
            "maximum_slot": self.maximum_slot,
            "minimum_slot": self.minimum_slot,
            "reconnect_epoch": self.reconnect_epoch,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CompletenessPolicy:
    policy_id: str
    required_sources: tuple[str, ...]
    max_slot_skew: int = 0
    minimum_observations: int = 1

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ObservationError("completeness policy_id is required")
        if not self.required_sources:
            raise ObservationError("completeness policy needs required_sources")
        if len(self.required_sources) != len(set(self.required_sources)):
            raise ObservationError("completeness required_sources must be unique")
        if type(self.max_slot_skew) is not int or self.max_slot_skew < 0:
            raise ObservationError("completeness max_slot_skew is invalid")
        if type(self.minimum_observations) is not int or self.minimum_observations <= 0:
            raise ObservationError("completeness minimum_observations is invalid")

    def evaluate(
        self,
        *,
        observations: tuple["MarketObservationV2", ...],
        watermark: ObservationWatermark,
    ) -> tuple[CompletenessState, tuple[str, ...]]:
        reasons: list[str] = []
        cursor_sources = {cursor.source for cursor in watermark.cursors}
        missing_sources = sorted(set(self.required_sources) - cursor_sources)
        if missing_sources:
            reasons.append("missing_sources:" + ",".join(missing_sources))
        if len(observations) < self.minimum_observations:
            reasons.append("insufficient_observations")
        if watermark.maximum_slot - watermark.minimum_slot > self.max_slot_skew:
            reasons.append("slot_skew_exceeded")
        if any(
            item.correction_kind is CorrectionKind.RETRACTION for item in observations
        ):
            reasons.append("contains_retraction")
        if not reasons:
            return CompletenessState.COMPLETE, ()
        if missing_sources or len(observations) < self.minimum_observations:
            return CompletenessState.BLOCKED, tuple(reasons)
        return CompletenessState.DEGRADED, tuple(reasons)


@dataclass(frozen=True, slots=True, init=False)
class MarketObservationV2:
    """Lossless observation with separate expected and guaranteed economics.

    The custom initializer accepts historical ``in_amount``/``out_amount`` names
    so old fixtures remain readable.  New producers must supply
    ``input_amount``, ``expected_output`` and ``guaranteed_output`` explicitly.
    """

    provider: str
    input_mint: str
    output_mint: str
    input_amount: int
    expected_output: int
    guaranteed_output: int
    slot: int
    observed_at: float
    source: str
    quote_id: str | None
    confidence: str
    commitment: str
    expires_at: float | None
    request_fingerprint: str | None
    response_hash: str | None
    correlation_labels: tuple[str, ...]
    provider_timestamp: float | None
    root_slot: int | None
    generation: ObservationGeneration
    cursor: SourceCursor | None
    correction_kind: CorrectionKind
    supersedes_id: str | None

    def __init__(
        self,
        *,
        provider: str,
        input_mint: str,
        output_mint: str,
        slot: int,
        observed_at: float,
        input_amount: int | None = None,
        expected_output: int | None = None,
        guaranteed_output: int | None = None,
        in_amount: int | None = None,
        out_amount: int | None = None,
        source: str = "unknown",
        quote_id: str | None = None,
        confidence: str = "recorded",
        commitment: str = "unknown",
        expires_at: float | None = None,
        request_fingerprint: str | None = None,
        response_hash: str | None = None,
        correlation_labels: tuple[str, ...] = (),
        provider_timestamp: float | None = None,
        root_slot: int | None = None,
        generation: ObservationGeneration | None = None,
        cursor: SourceCursor | None = None,
        correction_kind: CorrectionKind | str = CorrectionKind.ORIGINAL,
        supersedes_id: str | None = None,
    ) -> None:
        resolved_input = input_amount if input_amount is not None else in_amount
        resolved_expected = (
            expected_output if expected_output is not None else out_amount
        )
        resolved_guaranteed = (
            guaranteed_output if guaranteed_output is not None else resolved_expected
        )
        if (
            input_amount is not None
            and in_amount is not None
            and input_amount != in_amount
        ):
            raise ObservationError("input_amount and in_amount disagree")
        if (
            expected_output is not None
            and out_amount is not None
            and expected_output != out_amount
        ):
            raise ObservationError("expected_output and out_amount disagree")
        if (
            resolved_input is None
            or resolved_expected is None
            or resolved_guaranteed is None
        ):
            raise ObservationError("observation amounts are required")
        try:
            correction = CorrectionKind(correction_kind)
        except ValueError as exc:
            raise ObservationError("unsupported correction kind") from exc
        values = {
            "provider": provider,
            "input_mint": input_mint,
            "output_mint": output_mint,
            "input_amount": resolved_input,
            "expected_output": resolved_expected,
            "guaranteed_output": resolved_guaranteed,
            "slot": slot,
            "observed_at": observed_at,
            "source": source,
            "quote_id": quote_id,
            "confidence": confidence,
            "commitment": commitment,
            "expires_at": expires_at,
            "request_fingerprint": request_fingerprint,
            "response_hash": response_hash,
            "correlation_labels": tuple(correlation_labels),
            "provider_timestamp": provider_timestamp,
            "root_slot": root_slot,
            "generation": generation or ObservationGeneration(),
            "cursor": cursor,
            "correction_kind": correction,
            "supersedes_id": supersedes_id,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)
        self._validate()

    def _validate(self) -> None:
        if not self.provider or not self.source:
            raise ObservationError("observation provider and source are required")
        if self.input_mint == self.output_mint:
            raise ObservationError("observation mints must differ")
        for name, value, positive in (
            ("input_amount", self.input_amount, True),
            ("expected_output", self.expected_output, False),
            ("guaranteed_output", self.guaranteed_output, False),
            ("slot", self.slot, False),
        ):
            if type(value) is not int or value < (1 if positive else 0):
                raise ObservationError(f"{name} has invalid integer value")
        if self.guaranteed_output > self.expected_output:
            raise ObservationError("guaranteed_output cannot exceed expected_output")
        if not isinstance(self.observed_at, (int, float)) or self.observed_at <= 0:
            raise ObservationError("observed_at must be a positive unix timestamp")
        if not self.commitment or not self.confidence:
            raise ObservationError("commitment and confidence are required")
        if self.expires_at is not None and self.expires_at <= self.observed_at:
            raise ObservationError("expires_at must be after observed_at")
        if self.provider_timestamp is not None and self.provider_timestamp <= 0:
            raise ObservationError("provider_timestamp is invalid")
        if self.root_slot is not None:
            if type(self.root_slot) is not int or self.root_slot < 0:
                raise ObservationError("root_slot is invalid")
            if self.root_slot > self.slot:
                raise ObservationError("root_slot cannot exceed observation slot")
        if self.cursor is not None and self.cursor.slot != self.slot:
            raise ObservationError("source cursor slot must match observation slot")
        if self.correction_kind is CorrectionKind.ORIGINAL and self.supersedes_id:
            raise ObservationError(
                "original observation cannot supersede another record"
            )
        if (
            self.correction_kind is not CorrectionKind.ORIGINAL
            and not self.supersedes_id
        ):
            raise ObservationError("correction/retraction requires supersedes_id")

    @property
    def in_amount(self) -> int:
        return self.input_amount

    @property
    def out_amount(self) -> int:
        """Compatibility view; decision code receives the guaranteed amount."""

        return self.guaranteed_output

    @property
    def observation_id(self) -> str:
        payload = {
            "correction": self.correction_kind.value,
            "generation": self.generation.identity,
            "guaranteed_output": self.guaranteed_output,
            "input_amount": self.input_amount,
            "input_mint": self.input_mint,
            "output_mint": self.output_mint,
            "provider": self.provider,
            "request_fingerprint": self.request_fingerprint,
            "response_hash": self.response_hash,
            "slot": self.slot,
            "supersedes_id": self.supersedes_id,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def age_seconds(self, *, now: float | None = None) -> float:
        reference = time.time() if now is None else now
        return max(0.0, reference - self.observed_at)

    def is_fresh(self, *, now: float | None = None, max_age_seconds: float) -> bool:
        reference = time.time() if now is None else now
        if self.expires_at is None:
            if self.confidence != "recorded":
                return False
        elif reference >= self.expires_at:
            return False
        return self.age_seconds(now=reference) <= max_age_seconds

    def exact_output_for(self, input_amount: int) -> int:
        if type(input_amount) is not int or input_amount <= 0:
            raise ObservationError("input_amount must be a positive integer")
        if input_amount != self.input_amount:
            raise ObservationError(
                "observation amount mismatch: exact request evidence is required"
            )
        return self.guaranteed_output

    def project_output(self, input_amount: int) -> int:
        if type(input_amount) is not int or input_amount < 0:
            raise ObservationError("input_amount must be a non-negative integer")
        return (input_amount * self.guaranteed_output) // self.input_amount


# Historical import name is an alias to the installed V2 authority.
MarketQuoteSnapshot = MarketObservationV2


@dataclass(frozen=True, slots=True, init=False)
class ObservationBatch:
    batch_id: str
    observations: tuple[MarketObservationV2, ...]
    watermark: ObservationWatermark
    policy: CompletenessPolicy
    completeness: CompletenessState
    degraded_reasons: tuple[str, ...]
    published_at: float
    generation_identity: str

    def __init__(
        self,
        observations: Iterable[MarketObservationV2] = (),
        *,
        batch_id: str | None = None,
        watermark: ObservationWatermark | None = None,
        policy: CompletenessPolicy | None = None,
        completeness: CompletenessState | str | None = None,
        degraded_reasons: tuple[str, ...] = (),
        published_at: float | None = None,
    ) -> None:
        items = tuple(observations)
        if watermark is None:
            watermark = self._synthetic_watermark(items)
        if policy is None:
            sources = tuple(sorted({cursor.source for cursor in watermark.cursors}))
            policy = CompletenessPolicy(
                policy_id="compat.snapshot-set.v2",
                required_sources=sources,
                max_slot_skew=max(0, watermark.maximum_slot - watermark.minimum_slot),
                minimum_observations=max(1, len(items)),
            )
        evaluated, evaluated_reasons = policy.evaluate(
            observations=items, watermark=watermark
        )
        resolved = (
            evaluated if completeness is None else CompletenessState(completeness)
        )
        reasons = tuple(dict.fromkeys((*degraded_reasons, *evaluated_reasons)))
        if (
            resolved is CompletenessState.COMPLETE
            and evaluated is not CompletenessState.COMPLETE
        ):
            raise ObservationError("batch cannot override an incomplete policy verdict")
        generation_ids = sorted({item.generation.identity for item in items})
        generation_identity = hashlib.sha256(
            json.dumps(generation_ids, separators=(",", ":")).encode()
        ).hexdigest()
        identity_payload = {
            "generation": generation_identity,
            "observations": sorted(item.observation_id for item in items),
            "policy": policy.policy_id,
            "watermark": watermark.identity,
        }
        derived_batch_id = hashlib.sha256(
            json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        values = {
            "batch_id": batch_id or derived_batch_id,
            "observations": items,
            "watermark": watermark,
            "policy": policy,
            "completeness": resolved,
            "degraded_reasons": reasons,
            "published_at": time.time() if published_at is None else published_at,
            "generation_identity": generation_identity,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)
        if not self.batch_id:
            raise ObservationError("batch_id is required")
        if self.published_at <= 0:
            raise ObservationError("published_at must be positive")

    @staticmethod
    def _synthetic_watermark(
        observations: tuple[MarketObservationV2, ...],
    ) -> ObservationWatermark:
        if observations:
            candidates = tuple(
                item.cursor
                or SourceCursor(
                    source=item.provider,
                    partition=f"{item.input_mint}:{item.output_mint}:{index}",
                    offset=index,
                    slot=item.slot,
                )
                for index, item in enumerate(observations)
            )
            latest: dict[str, SourceCursor] = {}
            for cursor in candidates:
                previous = latest.get(cursor.key)
                if previous is None or cursor.offset > previous.offset:
                    latest[cursor.key] = cursor
            cursors = tuple(latest.values())
            epoch = max(cursor.reconnect_epoch for cursor in cursors)
            if any(cursor.reconnect_epoch != epoch for cursor in cursors):
                cursors = tuple(
                    SourceCursor(
                        source=cursor.source,
                        partition=cursor.partition,
                        offset=cursor.offset,
                        slot=cursor.slot,
                        reconnect_epoch=epoch,
                    )
                    for cursor in cursors
                )
            return ObservationWatermark(
                cursors=cursors,
                minimum_slot=min(item.slot for item in observations),
                maximum_slot=max(item.slot for item in observations),
                reconnect_epoch=epoch,
            )
        cursor = SourceCursor("empty", "empty", 0, 0)
        return ObservationWatermark((cursor,), 0, 0, 0)

    @property
    def quotes(self) -> tuple[MarketObservationV2, ...]:
        return self.observations

    @property
    def admissible(self) -> bool:
        return self.completeness is CompletenessState.COMPLETE

    def __iter__(self) -> Iterator[MarketObservationV2]:
        return iter(self.observations)

    def matching_quotes(
        self,
        *,
        input_mint: str,
        output_mint: str,
        now: float | None = None,
        max_age_seconds: float,
    ) -> tuple[MarketObservationV2, ...]:
        if not self.admissible:
            return ()
        return tuple(
            item
            for item in self.observations
            if item.correction_kind is not CorrectionKind.RETRACTION
            and item.input_mint == input_mint
            and item.output_mint == output_mint
            and item.is_fresh(now=now, max_age_seconds=max_age_seconds)
        )

    def best_projected_quote(
        self,
        *,
        input_mint: str,
        output_mint: str,
        input_amount: int,
        now: float | None = None,
        max_age_seconds: float,
    ) -> MarketObservationV2 | None:
        candidates = self.matching_quotes(
            input_mint=input_mint,
            output_mint=output_mint,
            now=now,
            max_age_seconds=max_age_seconds,
        )
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.project_output(input_amount))

    def active_observations(self) -> tuple[MarketObservationV2, ...]:
        superseded = {
            item.supersedes_id
            for item in self.observations
            if item.supersedes_id is not None
        }
        return tuple(
            item
            for item in self.observations
            if item.observation_id not in superseded
            and item.correction_kind is not CorrectionKind.RETRACTION
        )


class SnapshotSet(ObservationBatch):
    """Compatibility constructor that still produces a complete V2 batch."""

    def __init__(self, quotes: Iterable[MarketObservationV2] = ()) -> None:
        items = tuple(quotes)
        super().__init__(items)


class MarketSnapshotSource(Protocol):
    async def latest(self) -> ObservationBatch: ...


class RecordedSnapshotSource:
    def __init__(self, quotes: Iterable[MarketObservationV2] = ()) -> None:
        self._batch: ObservationBatch = SnapshotSet(quotes)

    async def latest(self) -> ObservationBatch:
        return self._batch

    def replace(self, quotes: Iterable[MarketObservationV2]) -> None:
        self._batch = SnapshotSet(quotes)

    def replace_batch(self, batch: ObservationBatch) -> None:
        self._batch = batch


async def coerce_observation_batch(source: object | None) -> ObservationBatch:
    if source is None:
        return SnapshotSet()
    if isinstance(source, ObservationBatch):
        return source
    if hasattr(source, "latest"):
        result = source.latest()
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, ObservationBatch):
            return result
        if isinstance(result, Iterable):
            return SnapshotSet(result)
    if isinstance(source, Iterable):
        return SnapshotSet(source)
    raise ObservationError(
        f"unsupported market observation source: {type(source).__name__}"
    )


coerce_snapshot_set = coerce_observation_batch
SnapshotSourceError = ObservationError
