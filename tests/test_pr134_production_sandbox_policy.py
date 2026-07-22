from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts.validate_deployment_sandbox import (
    DeploymentSandboxError,
    load_json,
    validate_compose_text,
    validate_policy,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "deploy/production/container_sandbox_policy.json"
COMPOSE_PATH = REPO_ROOT / "deploy/production/docker-compose.sandbox.yml"
SECCOMP_PATH = REPO_ROOT / "deploy/production/seccomp-runtime.json"
RUNTIME_ENV_EXAMPLE = REPO_ROOT / "deploy/production/runtime.env.example"
RUN_TMPFS_ENTRY = (
    "      - /run/flashloan-bot:rw,noexec,nosuid,nodev,"
    "size=16m,uid=10001,gid=10001,mode=0750\n"
)


def _policy() -> dict[str, object]:
    return load_json(POLICY_PATH)


def test_pr134_policy_and_compose_are_validated() -> None:
    validate_policy(_policy())
    validate_compose_text(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_pr134_policy_requires_read_only_root_and_fixed_non_root_user() -> None:
    policy = _policy()
    filesystem = copy.deepcopy(policy["filesystem"])
    assert isinstance(filesystem, dict)
    filesystem["read_only_root_filesystem"] = False
    policy["filesystem"] = filesystem

    with pytest.raises(DeploymentSandboxError, match="read-only"):
        validate_policy(policy)

    policy = _policy()
    policy["runtime_user"] = "0:0"
    with pytest.raises(DeploymentSandboxError, match="runtime user"):
        validate_policy(policy)


def test_pr134_policy_requires_linux_hardening_controls() -> None:
    policy = _policy()
    linux_security = copy.deepcopy(policy["linux_security"])
    assert isinstance(linux_security, dict)
    linux_security["drop_all_capabilities"] = False
    policy["linux_security"] = linux_security

    with pytest.raises(DeploymentSandboxError, match="drop_all_capabilities"):
        validate_policy(policy)

    policy = _policy()
    linux_security = copy.deepcopy(policy["linux_security"])
    assert isinstance(linux_security, dict)
    linux_security["privileged"] = True
    policy["linux_security"] = linux_security
    with pytest.raises(DeploymentSandboxError, match="privileged"):
        validate_policy(policy)


def test_pr134_policy_requires_live_hard_disabled_environment() -> None:
    policy = _policy()
    required_environment = copy.deepcopy(policy["required_environment"])
    assert isinstance(required_environment, dict)
    required_environment["LIVE_TRADING_ENABLED"] = "true"
    policy["required_environment"] = required_environment

    with pytest.raises(DeploymentSandboxError, match="LIVE_TRADING_ENABLED"):
        validate_policy(policy)


def test_pr134_compose_rejects_privilege_escape_hatches() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    with pytest.raises(DeploymentSandboxError, match="privileged"):
        validate_compose_text(compose + "\nprivileged: true\n")

    with pytest.raises(DeploymentSandboxError, match="cap_add"):
        validate_compose_text(compose + "\ncap_add:\n  - NET_ADMIN\n")

    with pytest.raises(DeploymentSandboxError, match="network_mode"):
        validate_compose_text(compose + "\nnetwork_mode: host\n")


def test_pr134_compose_requires_tmpfs_and_no_new_privileges() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    with pytest.raises(DeploymentSandboxError, match="no-new-privileges"):
        validate_compose_text(compose.replace("      - no-new-privileges:true\n", ""))

    with pytest.raises(DeploymentSandboxError, match="/run/flashloan-bot"):
        validate_compose_text(compose.replace(RUN_TMPFS_ENTRY, ""))


def test_pr134_seccomp_profile_is_not_unconfined() -> None:
    profile = load_json(SECCOMP_PATH)

    assert profile["defaultAction"] == "SCMP_ACT_ERRNO"
    assert isinstance(profile["syscalls"], list)
    assert profile["syscalls"]


def test_pr134_runtime_env_example_contains_only_disabled_live_defaults() -> None:
    text = RUNTIME_ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "LIVE_TRADING_ENABLED=false" in text
    assert "JITO_ENABLED=false" in text
    assert "KAMINO_LIQUIDATION_ENABLED=false" in text
    assert "Do not store real credentials here" in text
    assert "HELIUS_API_KEY=" in text
    assert "JUPITER_API_KEY=" in text
