"""Pytest compatibility helpers."""

import asyncio
import socket

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest

# Capture the pristine socket primitives before pytest-socket patches
# ``socket.socket`` in its own pytest_configure.  On Windows the pure-Python
# ``socket.socketpair`` used by ProactorEventLoop's self-pipe constructs its
# loopback sockets through ``socket.socket``, so a temporary restore of the
# pristine class around the socketpair call is required to keep loop
# bootstrap working under ``--disable-socket``.
_PRISTINE_SOCKET = socket.socket
_PRISTINE_SOCKETPAIR = socket.socketpair


def _guarded_socketpair(*args, **kwargs):
    """Run socketpair with the pristine socket class (Proactor self-pipe).

    pytest-socket's creation guard must not break the event loop's internal
    channel.  Only this primitive is exempt; any other socket creation
    (loopback included) stays blocked under --disable-socket.
    """
    current = socket.socket
    socket.socket = _PRISTINE_SOCKET  # type: ignore[misc]
    try:
        return _PRISTINE_SOCKETPAIR(*args, **kwargs)
    finally:
        socket.socket = current  # type: ignore[misc]


socket.socketpair = _guarded_socketpair


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
