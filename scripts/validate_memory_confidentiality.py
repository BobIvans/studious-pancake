#!/usr/bin/env python3
"""Validate PR-192 production memory/crash confidentiality artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class MemoryConfidentialityValidationError(ValueError):
    """Raised when deployment artifacts do not prove PR-192 controls."""


FORBIDDEN_INSPECTION_SYSCALLS = frozenset(
    {
        "ptrace",
        "process_vm_readv",
        "process_vm_writev",
        "kcmp",
        "perf_event_open",
    }
)
REQUIRED_RUNTIME_SYSCALLS = frozenset({"prctl", "prlimit64"})


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MemoryConfidentialityValidationError(message)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MemoryConfidentialityValidationError(
            f"unable to load reviewed JSON artifact: {path}"
        ) from exc
    _require(isinstance(value, dict), f"{path} must contain a JSON object")
    return value


def validate_policy(policy: dict[str, Any]) -> None:
    memory = policy.get("memory_confidentiality")
    _require(isinstance(memory, dict), "memory_confidentiality policy missing")
    for key in (
        "core_limit_zero",
        "process_non_dumpable",
        "ptrace_forbidden",
        "process_vm_read_forbidden",
        "crash_artifacts_allowlist_only",
        "support_bundles_allowlist_only",
        "signer_stricter_profile_required",
    ):
        _require(memory.get(key) is True, f"{key} must be true")
    _require(
        memory.get("swap_policy") == "encrypted-or-disabled",
        "swap policy must be encrypted-or-disabled",
    )
    _require(
        memory.get("host_coredump_storage") == "disabled-or-restricted",
        "host coredump storage must be disabled-or-restricted",
    )


def validate_compose(compose_text: str) -> None:
    for token in (
        'FLASHLOAN_MEMORY_HARDENING_REQUIRED: "true"',
        "ulimits:",
        "core:",
        "soft: 0",
        "hard: 0",
        "cap_drop:",
        "- ALL",
        "no-new-privileges:true",
        "seccomp=./deploy/production/seccomp-runtime.json",
    ):
        _require(token in compose_text, f"compose missing PR-192 token: {token}")
    lowered = compose_text.lower()
    for token in ("pid: host", "cap_add:", "seccomp=unconfined", "apparmor=unconfined"):
        _require(token not in lowered, f"compose enables memory inspection: {token}")


def validate_seccomp(profile: dict[str, Any]) -> None:
    _require(profile.get("defaultAction") == "SCMP_ACT_ERRNO", "seccomp must default deny")
    syscalls = profile.get("syscalls")
    _require(isinstance(syscalls, list), "seccomp syscalls must be a list")
    allowed: set[str] = set()
    for rule in syscalls:
        if not isinstance(rule, dict) or rule.get("action") != "SCMP_ACT_ALLOW":
            continue
        names = rule.get("names")
        if isinstance(names, list):
            allowed.update(name for name in names if isinstance(name, str))
    missing = REQUIRED_RUNTIME_SYSCALLS - allowed
    _require(not missing, f"seccomp blocks runtime hardening syscalls: {sorted(missing)}")
    exposed = FORBIDDEN_INSPECTION_SYSCALLS & allowed
    _require(not exposed, f"seccomp allows process inspection syscalls: {sorted(exposed)}")


def validate_entrypoint(pyproject_text: str) -> None:
    _require(
        'flashloan-bot = "src.secure_cli:main"' in pyproject_text,
        "installed runtime must enter through src.secure_cli",
    )


def validate_files(
    *,
    policy_path: Path,
    compose_path: Path,
    seccomp_path: Path,
    pyproject_path: Path,
) -> None:
    validate_policy(_load_object(policy_path))
    validate_compose(compose_path.read_text(encoding="utf-8"))
    validate_seccomp(_load_object(seccomp_path))
    validate_entrypoint(pyproject_path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("deploy/production/container_sandbox_policy.json"),
    )
    parser.add_argument(
        "--compose",
        type=Path,
        default=Path("deploy/production/docker-compose.sandbox.yml"),
    )
    parser.add_argument(
        "--seccomp",
        type=Path,
        default=Path("deploy/production/seccomp-runtime.json"),
    )
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    args = parser.parse_args(argv)
    validate_files(
        policy_path=args.policy,
        compose_path=args.compose,
        seccomp_path=args.seccomp,
        pyproject_path=args.pyproject,
    )
    print("PR-192 runtime memory confidentiality validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
