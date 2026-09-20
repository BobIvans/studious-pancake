"""Allowlisted argument-vector subprocess execution."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Mapping, Sequence


class SubprocessSecurityError(ValueError):
    """A subprocess request violated the explicit execution policy."""


@dataclass(frozen=True, slots=True)
class SubprocessPolicy:
    executable: Path
    allowed_argument_prefixes: tuple[str, ...]
    working_directory: Path
    environment_allowlist: frozenset[str]
    timeout_seconds: float
    max_output_bytes: int

    def __post_init__(self) -> None:
        if (
            not self.executable.is_absolute()
            or not self.working_directory.is_absolute()
        ):
            raise ValueError("executable and working directory must be absolute")
        if self.timeout_seconds <= 0 or self.max_output_bytes <= 0:
            raise ValueError("subprocess limits must be positive")


def run_allowlisted(
    policy: SubprocessPolicy,
    arguments: Sequence[str],
    *,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    if not policy.executable.is_file():
        raise SubprocessSecurityError("allowlisted executable does not exist")
    if not policy.working_directory.is_dir():
        raise SubprocessSecurityError("allowlisted working directory does not exist")
    for argument in arguments:
        if "\x00" in argument or len(argument) > 4096:
            raise SubprocessSecurityError("subprocess argument is invalid or oversized")
        if policy.allowed_argument_prefixes and not any(
            argument.startswith(prefix) for prefix in policy.allowed_argument_prefixes
        ):
            raise SubprocessSecurityError("subprocess argument is not allowlisted")
    source_env = os.environ if environment is None else environment
    safe_env = {
        key: source_env[key]
        for key in policy.environment_allowlist
        if key in source_env
    }
    completed = subprocess.run(
        [str(policy.executable), *arguments],
        cwd=policy.working_directory,
        env=safe_env,
        shell=False,
        timeout=policy.timeout_seconds,
        capture_output=True,
        check=False,
    )
    if (
        len(completed.stdout) > policy.max_output_bytes
        or len(completed.stderr) > policy.max_output_bytes
    ):
        raise SubprocessSecurityError("subprocess output exceeds limit")
    return completed
