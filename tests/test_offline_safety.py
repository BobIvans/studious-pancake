"""Offline safety guard tests for CI verification."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts import verify_repo

pytestmark = pytest.mark.unit


def test_verify_repo_uses_safe_environment_defaults() -> None:
    assert verify_repo.SAFE_ENV == {
        "PAPER_TRADING_ONLY": "true",
        "LIVE_TRADING_ENABLED": "false",
        "JITO_ENABLED": "false",
        "KAMINO_LIQUIDATION_ENABLED": "false",
    }


def test_offline_pytest_command_blocks_live_and_manual_tests_and_sockets() -> None:
    offline_command = verify_repo.COMMANDS[-1]
    assert offline_command[:3] == [os.sys.executable, "-m", "pytest"]
    assert "not live and not manual" in offline_command
    assert "--disable-socket" in offline_command


def test_verify_repo_does_not_call_paper_trading_or_live_simulation() -> None:
    script = Path("scripts/verify_repo.py").read_text()
    forbidden = ["paper_trader.py", "paper trading", "live simulation", "production-ready", "Ready for production"]
    lowered = script.lower()
    for term in forbidden:
        assert term.lower() not in lowered
