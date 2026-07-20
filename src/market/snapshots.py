"""Immutable market snapshot primitives for detector-only shadow candidates.

The models in this module are intentionally transport-neutral. Provider clients
or recorded fixtures may populate them, but they never build instructions,
simulate transactions, sign payloads, or submit anything to Solana.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol
import inspect
import time


class SnapshotSourceError(ValueError):
    """Raised when a market snapshot source returns unsupported data."""


@dataclass(frozen=True, slots=True)
class MarketQuoteSnapshot:
    """A quote observation for one directed route leg."""

    provider: str
    input_mint: str
    output_mint: str
    in_amount: int
    out_amount: int
    slot: int
    observed_at: float
    source: str = "unknown"
    quote_id: str | None = None
    confidence: str = "recorded"

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("snapshot provider is required")
        if self.input_mint == self.output_mint:
            raise ValueError("snapshot input_mint and output_mint must differ")
        if self.in_amount <= 0:
            raise ValueError("snapshot in_amount must be positive")
        if self.out_amount < 0:
            raise ValueError("snapshot out_amount must be non-negative")
        if self.slot < 0:
            raise ValueError("snapshot slot must be non-negative")
        if self.observed_at <= 0:
            raise ValueError("snapshot observed_at must be a unix timestamp")

    def age_seconds(self, *, now: float | None = None) -> float:
        reference = time.time() if now is None else now
        return max(0.0, reference - self.observed_at)

    def is_fresh(self, *, now: float | None = None, max_age_seconds: float) -> bool:
        return self.age_seconds(now=now) <= max_age_seconds

    def project_output(self, input_amount: int) -> int:
        """Project output for ``input_amount`` using integer floor math."""

        if input_amount < 0:
            raise ValueError("input_amount must not be negative")
        return (input_amount * self.out_amount) // self.in_amount


@dataclass(frozen=True, slots=True)
class SnapshotSet:
    """A deterministic, immutable bundle of quote snapshots."""

    quotes: tuple[MarketQuoteSnapshot, ...]

    def __init__(self, quotes: Iterable[MarketQuoteSnapshot] = ()) -> None:
        object.__setattr__(self, "quotes", tuple(quotes))

    def matching_quotes(
        self,
        *,
        input_mint: str,
        output_mint: str,
        now: float | None = None,
        max_age_seconds: float,
    ) -> tuple[MarketQuoteSnapshot, ...]:
        return tuple(
            quote
            for quote in self.quotes
            if quote.input_mint == input_mint
            and quote.output_mint == output_mint
            and quote.is_fresh(now=now, max_age_seconds=max_age_seconds)
        )

    def best_projected_quote(
        self,
        *,
        input_mint: str,
        output_mint: str,
        input_amount: int,
        now: float | None = None,
        max_age_seconds: float,
    ) -> MarketQuoteSnapshot | None:
        candidates = self.matching_quotes(
            input_mint=input_mint,
            output_mint=output_mint,
            now=now,
            max_age_seconds=max_age_seconds,
        )
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.project_output(input_amount))


class MarketSnapshotSource(Protocol):
    """Read-only source that returns the latest detector snapshots."""

    async def latest(self) -> SnapshotSet: ...


class RecordedSnapshotSource:
    """In-memory snapshot source for fixtures, replays, and unit tests."""

    def __init__(self, quotes: Iterable[MarketQuoteSnapshot] = ()) -> None:
        self._snapshot_set = SnapshotSet(quotes)

    async def latest(self) -> SnapshotSet:
        return self._snapshot_set

    def replace(self, quotes: Iterable[MarketQuoteSnapshot]) -> None:
        self._snapshot_set = SnapshotSet(quotes)


async def coerce_snapshot_set(source: object | None) -> SnapshotSet:
    """Return a ``SnapshotSet`` from supported in-process source shapes."""

    if source is None:
        return SnapshotSet()
    if isinstance(source, SnapshotSet):
        return source
    if hasattr(source, "latest"):
        result = source.latest()
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, SnapshotSet):
            return result
        if isinstance(result, Iterable):
            return SnapshotSet(result)
    if isinstance(source, Iterable):
        return SnapshotSet(source)
    raise SnapshotSourceError(
        f"unsupported market snapshot source: {type(source).__name__}"
    )
