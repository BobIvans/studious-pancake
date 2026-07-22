from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.validate_memory_confidentiality import (
    MemoryConfidentialityValidationError,
    validate_compose,
    validate_entrypoint,
    validate_files,
    validate_policy,
    validate_seccomp,
)
from src import secure_cli
from src.security.runtime_memory import RuntimeMemoryHardeningError


def _status() -> SimpleNamespace:
    return SimpleNamespace(
        to_dict=lambda: {
            "schema_version": "pr192.runtime-memory.v1",
            "platform": "linux",
            "core_soft_limit": 0,
            "core_hard_limit": 0,
            "dumpable": 0,
            "tracer_pid": 0,
            "verified": True,
            "reason_codes": [],
        }
    )


def test_secure_cli_hardens_before_importing_and_delegating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def harden(*, policy):
        calls.append("harden")
        return _status()

    def load_cli():
        calls.append("import")
        return SimpleNamespace(main=lambda args: calls.append("delegate") or 17)

    monkeypatch.setattr(secure_cli, "harden_process_memory", harden)
    monkeypatch.setattr(secure_cli, "_load_canonical_cli", load_cli)
    monkeypatch.delenv("FLASHLOAN_MEMORY_HARDENING_REQUIRED", raising=False)

    assert secure_cli.main(["status"]) == 17
    assert calls == ["harden", "import", "delegate"]


def test_secure_cli_fail_closed_does_not_import_canonical_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported = False

    def fail(*, policy):
        raise RuntimeMemoryHardeningError("runtime memory hardening failed: TEST")

    def load_cli():
        nonlocal imported
        imported = True
        return SimpleNamespace(main=lambda args: 0)

    monkeypatch.setattr(secure_cli, "harden_process_memory", fail)
    monkeypatch.setattr(secure_cli, "_load_canonical_cli", load_cli)
    monkeypatch.setenv("FLASHLOAN_MEMORY_HARDENING_REQUIRED", "true")

    assert secure_cli.main(["container"]) == secure_cli.EXIT_MEMORY_HARDENING_ERROR
    assert imported is False


def test_deployment_validator_accepts_reviewed_control_shape() -> None:
    validate_policy(
        {
            "memory_confidentiality": {
                "core_limit_zero": True,
                "process_non_dumpable": True,
                "ptrace_forbidden": True,
                "process_vm_read_forbidden": True,
                "crash_artifacts_allowlist_only": True,
                "support_bundles_allowlist_only": True,
                "signer_stricter_profile_required": True,
                "swap_policy": "encrypted-or-disabled",
                "host_coredump_storage": "disabled-or-restricted",
            }
        }
    )
    validate_compose(
        """
FLASHLOAN_MEMORY_HARDENING_REQUIRED: "true"
ulimits:
  core:
    soft: 0
    hard: 0
cap_drop:
  - ALL
security_opt:
  - no-new-privileges:true
  - seccomp=./deploy/production/seccomp-runtime.json
"""
    )
    validate_seccomp(
        {
            "defaultAction": "SCMP_ACT_ERRNO",
            "syscalls": [
                {"action": "SCMP_ACT_ALLOW", "names": ["prctl", "prlimit64"]}
            ],
        }
    )
    validate_entrypoint('flashloan-bot = "src.secure_cli:main"')


def test_deployment_validator_rejects_process_inspection() -> None:
    with pytest.raises(
        MemoryConfidentialityValidationError, match="process inspection"
    ):
        validate_seccomp(
            {
                "defaultAction": "SCMP_ACT_ERRNO",
                "syscalls": [
                    {
                        "action": "SCMP_ACT_ALLOW",
                        "names": ["prctl", "prlimit64", "ptrace"],
                    }
                ],
            }
        )


def test_repository_artifacts_validate_when_present() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = {
        "policy_path": root / "deploy/production/container_sandbox_policy.json",
        "compose_path": root / "deploy/production/docker-compose.sandbox.yml",
        "seccomp_path": root / "deploy/production/seccomp-runtime.json",
        "pyproject_path": root / "pyproject.toml",
    }
    if not all(path.exists() for path in paths.values()):
        pytest.skip("minimal isolated unit workspace")
    validate_files(**paths)
