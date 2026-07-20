from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

from src.container_runtime import STATE_SCHEMA, check_process_health

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]


def _wait_for_file(path: Path, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if path.is_file():
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"container supervisor exited early ({process.returncode})\n"
                f"stdout={stdout}\nstderr={stderr}"
            )
        time.sleep(0.05)
    raise AssertionError("container supervisor did not create its heartbeat")


def _runtime_env(**overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("FLASHLOAN_HEALTH_URL", None)
    env.update(overrides)
    return env


def _reserved_loopback_listener() -> tuple[socket.socket, int]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    return listener, int(listener.getsockname()[1])


def test_safe_idle_container_supervisor_has_live_process_heartbeat(tmp_path: Path):
    state = tmp_path / "runtime.json"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "src.cli",
            "container",
            "--state-file",
            str(state),
        ],
        cwd=ROOT,
        env=_runtime_env(FLASHLOAN_HEALTH_PORT="0"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_file(state, process)
        healthy, detail = check_process_health(state)
        assert healthy is True
        assert "safe-idle" in detail
        payload = json.loads(state.read_text(encoding="utf-8"))
        assert payload["schema_version"] == STATE_SCHEMA
        assert payload["mode"] == "disabled"
        assert payload["diagnostic"] == "SAFE_IDLE_NO_EXECUTION"
        assert payload["pid"] == process.pid
    finally:
        process.terminate()
        process.wait(timeout=5)
    assert not state.exists()


@pytest.mark.enable_socket
def test_container_port_collision_leaves_no_healthy_state(tmp_path: Path):
    state = tmp_path / "runtime.json"
    listener, port = _reserved_loopback_listener()
    with listener:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "src.cli",
                "container",
                "--state-file",
                str(state),
            ],
            cwd=ROOT,
            env=_runtime_env(
                FLASHLOAN_HEALTH_HOST="127.0.0.1",
                FLASHLOAN_HEALTH_PORT=str(port),
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = process.communicate(timeout=8)

    assert process.returncode != 0
    assert not state.exists()
    healthy, detail = check_process_health(state)
    assert healthy is False
    assert "missing" in detail
    assert "Address already in use" in stderr
    assert "container_safe_idle_started" not in stdout


def test_healthcheck_rejects_missing_stale_dead_and_wrong_mode(tmp_path: Path):
    state = tmp_path / "runtime.json"
    assert check_process_health(state)[0] is False

    base = {
        "schema_version": STATE_SCHEMA,
        "pid": os.getpid(),
        "heartbeat_unix_ns": time.time_ns() - 30_000_000_000,
        "mode": "disabled",
    }
    state.write_text(json.dumps(base), encoding="utf-8")
    healthy, detail = check_process_health(state, max_age_seconds=20.0)
    assert healthy is False
    assert "stale" in detail

    base["heartbeat_unix_ns"] = time.time_ns()
    base["pid"] = 999_999_999
    state.write_text(json.dumps(base), encoding="utf-8")
    healthy, detail = check_process_health(state)
    assert healthy is False
    assert "not alive" in detail

    base["pid"] = os.getpid()
    base["mode"] = "live"
    state.write_text(json.dumps(base), encoding="utf-8")
    healthy, detail = check_process_health(state)
    assert healthy is False
    assert "fail-closed" in detail
