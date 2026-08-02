"""Reversible ownership of logging and process signal hooks."""

from __future__ import annotations

import asyncio
import logging
import signal
from types import FrameType
from typing import Callable, Iterable


class LoggingHandlerOwner:
    """Install one CLI handler only when the embedding process has none."""

    def __init__(self, *, level: int = logging.INFO) -> None:
        self.level = level
        self._handler: logging.Handler | None = None
        self._previous_level: int | None = None

    def install(self) -> "LoggingHandlerOwner":
        root = logging.getLogger()
        if root.handlers:
            return self
        self._previous_level = root.level
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        root.addHandler(handler)
        root.setLevel(self.level)
        self._handler = handler
        return self

    def restore(self) -> None:
        if self._handler is None:
            return
        root = logging.getLogger()
        root.removeHandler(self._handler)
        self._handler.close()
        if self._previous_level is not None:
            root.setLevel(self._previous_level)
        self._handler = None

    def __enter__(self) -> "LoggingHandlerOwner":
        return self.install()

    def __exit__(self, *_: object) -> None:
        self.restore()


class AsyncSignalHandlerOwner:
    """Install event-loop stop handlers and restore the prior process handlers."""

    def __init__(
        self,
        callback: Callable[[], None],
        signals: Iterable[signal.Signals] = (signal.SIGINT, signal.SIGTERM),
    ) -> None:
        self.callback = callback
        self.signals = tuple(signals)
        self._previous: dict[signal.Signals, signal.Handlers] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._installed = False

    def install(self) -> "AsyncSignalHandlerOwner":
        if self._installed:
            return self
        self._loop = asyncio.get_running_loop()
        for sig in self.signals:
            self._previous[sig] = signal.getsignal(sig)
            try:
                self._loop.add_signal_handler(sig, self.callback)
            except (NotImplementedError, RuntimeError):  # Windows/non-main thread
                signal.signal(sig, self._fallback)
        self._installed = True
        return self

    def _fallback(self, _signum: int, _frame: FrameType | None) -> None:
        self.callback()

    def restore(self) -> None:
        if not self._installed:
            return
        for sig, previous in self._previous.items():
            if self._loop is not None:
                try:
                    self._loop.remove_signal_handler(sig)
                except (NotImplementedError, RuntimeError):
                    pass
            signal.signal(sig, previous)
        self._previous.clear()
        self._installed = False

    def __enter__(self) -> "AsyncSignalHandlerOwner":
        return self.install()

    def __exit__(self, *_: object) -> None:
        self.restore()
