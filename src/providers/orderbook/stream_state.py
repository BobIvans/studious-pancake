"""Local absolute-level reconstruction; no subscription or strategy promotion.

A feed adapter must prove that its native updates use these semantics before
using this owner. Prices/quantities are integer lots, not parsed float decimals.
"""

from dataclasses import dataclass
from hashlib import sha256
import json
from .models import L2Level, OrderbookDepth, Side


class BookResyncRequired(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AbsoluteBookFrame:
    generation: str
    sequence: int
    depth: OrderbookDepth
    evidence_hash: str


class AbsoluteLevelBook:
    def __init__(self, *, max_levels: int = 512):
        if type(max_levels) is not int or not 1 <= max_levels <= 4096:
            raise ValueError("book level bound required")
        self.max_levels = max_levels
        self._levels: dict[tuple[Side, int], int] = {}
        self._generation = ""
        self._sequence = 0
        self._valid = False

    @staticmethod
    def _validated(levels: tuple[L2Level, ...]) -> tuple[L2Level, ...]:
        if len({(level.side, level.price_lots) for level in levels}) != len(levels):
            raise ValueError("duplicate absolute level")
        for level in levels:
            if (
                not isinstance(level.side, Side)
                or type(level.price_lots) is not int
                or level.price_lots <= 0
                or type(level.base_lots) is not int
                or level.base_lots < 0
            ):
                raise ValueError("integer lot levels required")
        return levels

    def install_snapshot(
        self, *, generation: str, sequence: int, depth: OrderbookDepth
    ) -> AbsoluteBookFrame:
        self._valid = False
        if not generation.strip() or type(sequence) is not int or sequence < 0:
            raise ValueError("book generation and sequence required")
        if any(level.side is not Side.BID for level in depth.bids) or any(
            level.side is not Side.ASK for level in depth.asks
        ):
            raise ValueError("snapshot side mismatch")
        levels = self._validated((*depth.bids, *depth.asks))
        values = {
            (level.side, level.price_lots): level.base_lots
            for level in levels
            if level.base_lots
        }
        if len(values) > self.max_levels:
            raise ValueError("book level bound exceeded")
        self._levels = values
        self._generation = generation
        self._sequence = sequence
        self._valid = True
        return self.frame()

    def update(
        self, *, generation: str, sequence: int, absolute_levels: tuple[L2Level, ...]
    ) -> AbsoluteBookFrame:
        if (
            not self._valid
            or generation != self._generation
            or type(sequence) is not int
            or sequence != self._sequence + 1
        ):
            self._valid = False
            raise BookResyncRequired(
                "book sequence/generation requires snapshot resync"
            )
        try:
            levels = self._validated(absolute_levels)
            updated = dict(self._levels)
            for level in levels:
                key = (level.side, level.price_lots)
                if level.base_lots:
                    updated[key] = level.base_lots
                else:
                    updated.pop(key, None)
            if len(updated) > self.max_levels:
                raise ValueError("book level bound exceeded")
        except BaseException:
            self._valid = False
            raise
        self._levels = updated
        self._sequence = sequence
        return self.frame()

    def frame(self) -> AbsoluteBookFrame:
        if not self._valid:
            raise BookResyncRequired("book has no qualified reconstructed frame")
        bids = tuple(
            L2Level(side, price, size)
            for (side, price), size in self._levels.items()
            if side is Side.BID
        )
        asks = tuple(
            L2Level(side, price, size)
            for (side, price), size in self._levels.items()
            if side is Side.ASK
        )
        depth = OrderbookDepth(bids, asks).sorted()
        encoded = json.dumps(
            {
                "generation": self._generation,
                "sequence": self._sequence,
                "levels": [
                    (level.side.value, level.price_lots, level.base_lots)
                    for level in (*depth.bids, *depth.asks)
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return AbsoluteBookFrame(
            self._generation, self._sequence, depth, sha256(encoded).hexdigest()
        )
