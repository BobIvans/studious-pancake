from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from src.security.runtime_memory import (
    CrashArtifactError,
    RuntimeMemoryHardeningError,
    RuntimeMemoryPolicy,
    build_allowlisted_support_bundle,
    build_safe_crash_artifact,
    harden_process_memory,
)


class _Backend:
    platform = "linux"

    def __init__(self) -> None:
        self.core = (1024, 1024)
        self.dumpable = 1

    def set_core_limit_zero(self) -> None:
        self.core = (0, 0)

    def get_core_limit(self) -> tuple[int, int]:
        return self.core

    def set_dumpable(self, value: int) -> None:
        self.dumpable = value

    def get_dumpable(self) -> int:
        return self.dumpable


def _proc_status(tmp_path: Path, tracer_pid: int = 0) -> Path:
    path = tmp_path / "status"
    path.write_text(f"Name:\tpython\nTracerPid:\t{tracer_pid}\n", encoding="utf-8")
    return path


def test_hardening_sets_and_verifies_core_dumpability_and_tracer(
    tmp_path: Path,
) -> None:
    backend = _Backend()

    status = harden_process_memory(
        backend=backend,
        proc_status_path=_proc_status(tmp_path),
    )

    assert status.verified is True
    assert status.core_soft_limit == 0
    assert status.core_hard_limit == 0
    assert status.dumpable == 0
    assert status.tracer_pid == 0
    assert status.reason_codes == ()


def test_active_tracer_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(RuntimeMemoryHardeningError, match="ACTIVE_TRACER_DETECTED"):
        harden_process_memory(
            backend=_Backend(),
            proc_status_path=_proc_status(tmp_path, tracer_pid=42),
        )


def test_backend_error_message_is_not_propagated(tmp_path: Path) -> None:
    class Broken(_Backend):
        def set_dumpable(self, value: int) -> None:
            raise OSError("credential=do-not-leak")

    with pytest.raises(RuntimeMemoryHardeningError) as exc_info:
        harden_process_memory(
            backend=Broken(),
            proc_status_path=_proc_status(tmp_path),
        )

    assert "credential=do-not-leak" not in str(exc_info.value)
    assert "DUMPABLE_DISABLE_FAILED" in str(exc_info.value)


def test_real_linux_hardening_works_in_disposable_subprocess() -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux-only prctl verification")
    script = """
from src.security.runtime_memory import harden_process_memory
status = harden_process_memory()
assert status.verified
assert status.core_soft_limit == 0
assert status.core_hard_limit == 0
assert status.dumpable == 0
assert status.tracer_pid == 0
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_crash_artifact_drops_exception_message_args_and_traceback() -> None:
    secret = "provider-secret-should-never-appear"
    try:
        raise RuntimeError(secret)
    except RuntimeError as exc:
        artifact = build_safe_crash_artifact(
            exc,
            component="provider-auth",
            operation="credentialed-probe",
            reason_code="PROVIDER_AUTH_FAILED",
            correlation_id="run-123",
        ).to_dict()

    rendered = repr(artifact)
    assert secret not in rendered
    assert artifact["exception_type"] == "RuntimeError"
    assert "traceback" not in artifact
    assert "message" not in artifact
    assert "args" not in artifact


def test_support_bundle_is_allowlist_only() -> None:
    bundle = build_allowlisted_support_bundle(
        {
            "component": "runtime",
            "operation": "startup",
            "reason_code": "MEMORY_HARDENING_OK",
            "release_hash": "a" * 64,
            "policy_hash": "b" * 64,
            "config_generation": 7,
            "timestamp_unix_ns": 123,
        }
    )
    assert bundle["schema_version"] == "pr192.support-bundle.v1"
    assert bundle["config_generation"] == 7

    for forbidden in (
        "environment",
        "authorization_header",
        "transaction_bytes",
        "signature",
        "wallet_topology",
        "traceback",
        "locals",
    ):
        with pytest.raises(CrashArtifactError, match="non-allowlisted"):
            build_allowlisted_support_bundle({forbidden: "secret"})


def test_non_linux_production_policy_fails_closed(tmp_path: Path) -> None:
    backend = _Backend()
    backend.platform = "darwin"
    with pytest.raises(RuntimeMemoryHardeningError, match="LINUX_REQUIRED"):
        harden_process_memory(
            policy=RuntimeMemoryPolicy.production_default(),
            backend=backend,
            proc_status_path=_proc_status(tmp_path),
        )
