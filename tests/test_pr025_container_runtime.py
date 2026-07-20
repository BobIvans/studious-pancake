from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

import src.container_runtime as container_runtime
from src.container_runtime import STATE_SCHEMA, check_process_health

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]


class _DummyMatrix:
    product_state = "not-production-ready"

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": "test.capabilities.v1"}


class _DummyApp:
    def validate(self) -> None:
        return None

    def capability_errors(self) -> tuple[str, ...]:
        return ()


class _FailingStatusServer:
    base_url = "http://127.0.0.1:0"

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        return None

    def start(self) -> "_FailingStatusServer":
        raise OSError("health server bind failed for test")

    def stop(self) -> None:
        raise AssertionError("server was never started")


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


def _wait_for_missing(path: Path) -> None:
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if not path.exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"container supervisor left stale state file: {path}")


def _terminate(process: subprocess.Popen[str]) -> tuple[str, str]:
    if process.poll() is None:
        process.terminate()
    try:
        stdout, stderr = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=5)
        raise AssertionError(
            "container supervisor ignored SIGTERM and required SIGKILL\n"
            f"stdout={stdout}\nstderr={stderr}"
        )
    return stdout, stderr


def _container_env(**overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(overrides)
    return env


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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_container_env(FLASHLOAN_HEALTH_PORT="0"),
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
        _terminate(process)
    _wait_for_missing(state)


def test_safe_idle_container_supervisor_cleans_state_when_http_start_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    state = tmp_path / "runtime.json"
    monkeypatch.setattr(
        container_runtime,
        "RuntimeStatusHttpServer",
        _FailingStatusServer,
    )

    with pytest.raises(OSError, match="health server bind failed"):
        asyncio.run(
            container_runtime.run_safe_idle(
                _DummyMatrix(),
                _DummyApp(),
                state_file=str(state),
                health_port=0,
            )
        )

    assert not state.exists()
    assert not tuple(state.parent.glob(f".{state.name}.*.tmp"))


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
