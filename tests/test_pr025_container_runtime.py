from __future__ import annotations

import json
import os
from pathlib import Path
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
