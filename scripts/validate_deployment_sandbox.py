#!/usr/bin/env python3
"""Validate the PR-134 production sandbox deployment profile.

The validator intentionally uses only the Python standard library. It does not
try to be a general Docker Compose parser; instead it checks the repository's
reviewed deployment artifact for mandatory fail-closed controls and rejects
known dangerous escape hatches.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class DeploymentSandboxError(ValueError):
    """Raised when the production sandbox profile violates PR-134 policy."""


REQUIRED_POLICY_TOP_LEVEL = {
    "schema_version",
    "service",
    "runtime_user",
    "image_reference",
    "filesystem",
    "linux_security",
    "limits",
    "secrets",
    "network",
    "health",
    "required_environment",
}

REQUIRED_COMPOSE_TOKENS = (
    "read_only: true",
    'user: "10001:10001"',
    "init: true",
    "cap_drop:",
    "- ALL",
    "security_opt:",
    "no-new-privileges:true",
    "seccomp=./deploy/production/seccomp-runtime.json",
    "apparmor=flashloan-bot-runtime",
    "tmpfs:",
    "/run/flashloan-bot:rw,noexec,nosuid,nodev",
    "/tmp:rw,noexec,nosuid,nodev",
    "pids_limit: 256",
    "mem_limit: 768m",
    'cpus: "1.0"',
    "ulimits:",
    "secrets:",
    "runtime.env",
    "healthcheck:",
    'PAPER_TRADING_ONLY: "true"',
    'LIVE_TRADING_ENABLED: "false"',
    'JITO_ENABLED: "false"',
    'KAMINO_LIQUIDATION_ENABLED: "false"',
)

FORBIDDEN_COMPOSE_TOKENS = (
    "privileged: true",
    "network_mode: host",
    "pid: host",
    "ipc: host",
    "cap_add:",
    "security_opt:\n      - seccomp=unconfined",
    "apparmor=unconfined",
)

_ACCEPTED_WRITABLE_VOLUME_TARGETS = {
    "/var/lib/flashloan-bot",
    "/var/log/flashloan-bot",
}


def load_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DeploymentSandboxError(f"{path}: invalid JSON") from exc
    if not isinstance(loaded, dict):
        raise DeploymentSandboxError(f"{path}: top-level value must be an object")
    return loaded


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DeploymentSandboxError(message)


def validate_policy(policy: dict[str, Any]) -> None:
    """Validate the reviewed PR-134 sandbox policy manifest."""

    missing = REQUIRED_POLICY_TOP_LEVEL - set(policy)
    _require(not missing, f"policy missing required sections: {sorted(missing)}")
    _require(policy["schema_version"] == "pr134.container_sandbox.v1", "bad schema")
    _require(policy["runtime_user"] == "10001:10001", "runtime user must be fixed")
    _require(
        policy["live_submission_default"] == "hard-disabled",
        "live must default off",
    )

    image_reference = _dict(policy, "image_reference")
    _require(
        image_reference.get("require_digest_pin") is True,
        "image digest pin required",
    )
    _require(image_reference.get("forbid_latest_tag") is True, "latest tag forbidden")

    filesystem = _dict(policy, "filesystem")
    _require(
        filesystem.get("read_only_root_filesystem") is True,
        "root filesystem must be read-only",
    )
    approved = set(_list(filesystem, "approved_writable_targets"))
    _require("/run/flashloan-bot" in approved, "runtime tmpfs must be approved")
    _require("/tmp" in approved, "tmpfs must be approved")
    _require(
        filesystem.get("forbid_arbitrary_host_mounts") is True,
        "arbitrary host mounts must be forbidden",
    )

    linux_security = _dict(policy, "linux_security")
    for key in (
        "drop_all_capabilities",
        "no_new_privileges",
        "seccomp_profile_required",
        "apparmor_profile_required",
    ):
        _require(linux_security.get(key) is True, f"{key} must be true")
    for key in ("privileged", "host_pid", "host_ipc", "host_network"):
        _require(linux_security.get(key) is False, f"{key} must be false")

    limits = _dict(policy, "limits")
    _require(_positive_int(limits.get("pids_limit")), "pids limit required")
    _require(_positive_int(limits.get("nofile_soft")), "nofile soft limit required")
    _require(_positive_int(limits.get("nofile_hard")), "nofile hard limit required")
    _require(limits["nofile_hard"] >= limits["nofile_soft"], "nofile hard < soft")
    _require(
        str(limits.get("memory_limit", "")).endswith("m"),
        "memory limit required",
    )
    _require(
        str(limits.get("cpus", "")) not in {"", "0", "0.0"},
        "CPU limit required",
    )

    secrets = _dict(policy, "secrets")
    _require(secrets.get("secret_mount_required") is True, "secret mount required")
    _require(
        secrets.get("forbid_plaintext_environment_secrets") is True,
        "plaintext environment secrets must be forbidden",
    )

    network = _dict(policy, "network")
    _require(network.get("egress_policy_required") is True, "egress policy required")
    _require(
        network.get("deny_arbitrary_internet") is True,
        "arbitrary internet denied",
    )
    _require(
        network.get("split_signer_from_network_runtime") is True,
        "signer/network split required",
    )

    health = _dict(policy, "health")
    _require(health.get("healthcheck_required") is True, "healthcheck required")
    _require(
        health.get("readiness_must_use_real_runtime") is True,
        "readiness must use real runtime",
    )

    required_env = _dict(policy, "required_environment")
    for key in (
        "PAPER_TRADING_ONLY",
        "LIVE_TRADING_ENABLED",
        "JITO_ENABLED",
        "KAMINO_LIQUIDATION_ENABLED",
    ):
        _require(key in required_env, f"missing required environment {key}")
    _require(required_env["PAPER_TRADING_ONLY"] == "true", "paper mode must be true")
    for key in (
        "LIVE_TRADING_ENABLED",
        "JITO_ENABLED",
        "KAMINO_LIQUIDATION_ENABLED",
    ):
        _require(required_env[key] == "false", f"{key} must be false")


def validate_compose_text(compose_text: str) -> None:
    """Check the reviewed compose profile for required sandbox controls."""

    for token in REQUIRED_COMPOSE_TOKENS:
        _require(token in compose_text, f"compose missing required token: {token}")
    _reject_privilege_escape_tokens(compose_text)
    _validate_writable_volumes_are_approved(compose_text)


def _reject_privilege_escape_tokens(compose_text: str) -> None:
    lowered = compose_text.lower()
    for token in FORBIDDEN_COMPOSE_TOKENS:
        _require(
            token.lower() not in lowered,
            f"compose contains forbidden token: {token}",
        )
    for line in compose_text.splitlines():
        if line.startswith("    read_only: false"):
            raise DeploymentSandboxError("service root filesystem must stay read-only")


def _validate_writable_volumes_are_approved(compose_text: str) -> None:
    lines = compose_text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "read_only: false":
            continue
        window = "\n".join(lines[max(0, index - 6) : index + 1])
        target = _volume_target_from_window(window)
        _require(
            target in _ACCEPTED_WRITABLE_VOLUME_TARGETS,
            f"unapproved writable volume target: {target or '<unknown>'}",
        )


def _volume_target_from_window(window: str) -> str | None:
    for line in window.splitlines():
        stripped = line.strip()
        if stripped.startswith("target: "):
            return stripped.removeprefix("target: ")
    return None


def _dict(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    value = mapping.get(key)
    _require(isinstance(value, dict), f"{key} must be an object")
    return value


def _list(mapping: dict[str, Any], key: str) -> list[Any]:
    value = mapping.get(key)
    _require(isinstance(value, list), f"{key} must be a list")
    return value


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_files(policy_path: Path, compose_path: Path) -> None:
    validate_policy(load_json(policy_path))
    validate_compose_text(compose_path.read_text(encoding="utf-8"))


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
    args = parser.parse_args(argv)
    validate_files(args.policy, args.compose)
    print("PR-134 deployment sandbox policy validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
