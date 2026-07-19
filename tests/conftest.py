"""Pytest compatibility helpers."""

import asyncio

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest


class CompatibilityEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    """Restore pre-3.14 get_event_loop behavior expected by legacy tests."""

    def get_event_loop(self):
        try:
            return super().get_event_loop()
        except RuntimeError:
            loop = self.new_event_loop()
            self.set_event_loop(loop)
            return loop


asyncio.set_event_loop_policy(CompatibilityEventLoopPolicy())


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    """Allow AF_UNIX loop self-pipes while pytest-socket blocks network sockets."""
    setattr(config, "__socket_allow_unix_socket", True)
