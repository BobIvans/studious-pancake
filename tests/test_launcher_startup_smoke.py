"""Offline startup smoke for the supported arb_bot composition path."""

from __future__ import annotations

import asyncio

import pytest

import arb_bot
from src.application import build_application


@pytest.mark.integration
@pytest.mark.asyncio
async def test_arb_bot_launcher_builds_starts_and_stops_within_timeout() -> None:
    config = arb_bot.load_configuration()
    application = build_application(config)

    try:
        await asyncio.wait_for(application.run(), timeout=2.0)
        manifest = application.manifest()
        assert manifest
        assert all(entry.effective_mode != "live" for entry in manifest)
    finally:
        await asyncio.wait_for(application.stop(), timeout=2.0)
