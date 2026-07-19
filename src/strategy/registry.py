"""Single source of strategy registration."""
from __future__ import annotations

from collections import OrderedDict
from typing import Iterable

from .interfaces import Strategy


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: OrderedDict[str, Strategy] = OrderedDict()

    def register(self, strategy: Strategy) -> None:
        if strategy.name in self._strategies:
            raise ValueError(f"duplicate strategy registration: {strategy.name}")
        self._strategies[strategy.name] = strategy

    def all(self) -> tuple[Strategy, ...]:
        return tuple(self._strategies.values())

    def get(self, name: str) -> Strategy | None:
        return self._strategies.get(name)

    def enabled(self) -> Iterable[Strategy]:
        return (s for s in self._strategies.values() if s.mode.value != "disabled")
