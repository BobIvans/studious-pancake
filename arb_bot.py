"""Thin application launcher for the arbitrage bot."""
from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import dataclass, field

from src.application import build_application
from src.strategy.interfaces import StrategyMode

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LauncherConfig:
    """Runtime configuration normalized for PR-002 strategy modes."""

    strategy_modes: dict[str, str] = field(default_factory=lambda: {
        "lst_depeg": StrategyMode.DISABLED.value,
        "lst_unstake": StrategyMode.DISABLED.value,
        "circular_arbitrage": StrategyMode.DISABLED.value,
    })
    opportunity_queue_size: int = 1024
    shutdown_drain_timeout_seconds: float = 0.25


def load_configuration() -> LauncherConfig:
    """Load launcher configuration.

    Legacy configuration remains available to execution adapters, while strategy
    activation is normalized to StrategyMode values.
    """
    return LauncherConfig()


def install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_configuration()
    application = build_application(config)
    stop_event = asyncio.Event()
    install_signal_handlers(stop_event)
    try:
        await application.run()
        await stop_event.wait()
    finally:
        await application.stop()


if __name__ == "__main__":
    asyncio.run(main())
