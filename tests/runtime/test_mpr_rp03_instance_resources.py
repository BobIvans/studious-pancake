from __future__ import annotations

import json
from pathlib import Path
import socket

import pytest

from src.runtime.instance_resources import (
    LocalResourceCollision,
    LocalResourceLease,
    LocalResourceManifest,
    RuntimeInstanceIdentity,
)


def _identity(*, deployment: str = "blue", generation: int = 1):
    return RuntimeInstanceIdentity(
        environment="test",
        release_id="release-1",
        deployment_id=deployment,
        instance_id="primary",
        generation=generation,
    )


def test_same_namespace_is_exclusive(tmp_path: Path) -> None:
    manifest = LocalResourceManifest.derive(_identity(), base_root=tmp_path)
    first = LocalResourceLease(manifest).acquire()
    try:
        with pytest.raises(LocalResourceCollision):
            LocalResourceLease(manifest).acquire()
    finally:
        first.release()
    assert not manifest.lock_path.exists()


def test_blue_green_namespaces_and_ports_do_not_collide(tmp_path: Path) -> None:
    blue = LocalResourceManifest.derive(
        _identity(deployment="blue"), base_root=tmp_path, management_port=18080
    )
    green_identity = _identity(deployment="green")
    green = LocalResourceManifest.derive(
        green_identity,
        base_root=tmp_path,
        management_port=green_identity.deterministic_port(18080),
    )

    assert blue.root != green.root
    assert blue.state_path != green.state_path
    assert blue.management_port != green.management_port


def test_cleanup_refuses_to_delete_replaced_generation_lock(tmp_path: Path) -> None:
    manifest = LocalResourceManifest.derive(_identity(), base_root=tmp_path)
    lease = LocalResourceLease(manifest).acquire()
    original = json.loads(manifest.lock_path.read_text(encoding="utf-8"))
    manifest.lock_path.unlink()
    manifest.lock_path.write_text(
        json.dumps({**original, "cleanup_token": "replacement"}),
        encoding="utf-8",
    )

    with pytest.raises(LocalResourceCollision):
        lease.release()
    assert manifest.lock_path.exists()


def test_partial_socket_acquisition_rolls_back_lock(tmp_path: Path) -> None:
    guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    guard.bind(("127.0.0.1", 0))
    guard.listen(1)
    port = int(guard.getsockname()[1])
    manifest = LocalResourceManifest.derive(
        _identity(deployment="occupied"),
        base_root=tmp_path,
        management_port=port,
    )
    try:
        with pytest.raises(LocalResourceCollision):
            LocalResourceLease(manifest).acquire(reserve_socket=True)
        assert not manifest.lock_path.exists()
    finally:
        guard.close()
