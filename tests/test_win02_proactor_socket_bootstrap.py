"""WIN-02: Proactor socketpair bootstrap must survive pytest-socket's guard.

On native Windows the ProactorEventLoop self-pipe calls the pure-Python
``socket.socketpair``, which constructs AF_INET loopback sockets through
``socket.socket``.  tests/conftest.py temporarily restores the pristine
socket class around socketpair only; every other socket creation stays
blocked under ``--disable-socket``.
"""

import asyncio
import socket

import pytest
import pytest_socket

from tests.conftest import _PRISTINE_SOCKET

pytestmark = pytest.mark.unit


def _require_socket_guard() -> None:
    """Skip unless pytest-socket's per-test guard is active right now."""
    if socket.socket is _PRISTINE_SOCKET:
        pytest.skip("socket guard inactive (run with --disable-socket)")


def test_asyncio_bootstrap_works_under_socket_guard() -> None:
    """Loop bootstrap (Proactor self-pipe socketpair) must not be blocked."""

    async def trivial() -> int:
        await asyncio.sleep(0)
        return 7

    assert asyncio.run(trivial()) == 7

    loop = asyncio.new_event_loop()
    try:
        assert not loop.is_closed()
    finally:
        loop.close()


def test_direct_af_INET_creation_still_blocked() -> None:
    """AF_INET socket creation must stay blocked while the guard is active."""
    _require_socket_guard()
    with pytest.raises(pytest_socket.SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_loopback_creation_still_blocked_and_socketpair_exempt() -> None:
    """Loopback creation is blocked, yet socketpair stays usable."""
    _require_socket_guard()
    with pytest.raises(pytest_socket.SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    client, server = socket.socketpair()
    try:
        client.send(b"ping")
        assert server.recv(4) == b"ping"
    finally:
        client.close()
        server.close()


def test_compatibility_policy_get_event_loop_semantics() -> None:
    """CompatibilityEventLoopPolicy still fabricates a loop when unset."""
    from tests.conftest import CompatibilityEventLoopPolicy

    policy = CompatibilityEventLoopPolicy()
    previous = asyncio.get_event_loop_policy()
    try:
        asyncio.set_event_loop_policy(policy)
        asyncio.set_event_loop(None)
        loop = asyncio.get_event_loop()
        assert isinstance(loop, asyncio.AbstractEventLoop)
        policy.get_event_loop().close()
    finally:
        asyncio.set_event_loop_policy(previous)
