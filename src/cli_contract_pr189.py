"""PR-189 automation-safe command contract and exit semantics."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "pr189.command-result.v1"


class CommandMode(StrEnum):
    INSPECT = "inspect"
    CHECK = "check"
    EXECUTE = "execute"


class CommandVerdict(StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    SECURITY_VIOLATION = "security_violation"
    ERROR = "error"


class CommandExitCode(IntEnum):
    OK = 0
    MALFORMED_OR_INTERNAL_ERROR = 2
    BLOCKED = 3
    STALE = 4
    DEPENDENCY_UNAVAILABLE = 5
    SECURITY_VIOLATION = 6


_CHECK_EXIT_CODES = {
    CommandVerdict.PASSED: CommandExitCode.OK,
    CommandVerdict.BLOCKED: CommandExitCode.BLOCKED,
    CommandVerdict.STALE: CommandExitCode.STALE,
    CommandVerdict.UNAVAILABLE: CommandExitCode.DEPENDENCY_UNAVAILABLE,
    CommandVerdict.SECURITY_VIOLATION: CommandExitCode.SECURITY_VIOLATION,
    CommandVerdict.ERROR: CommandExitCode.MALFORMED_OR_INTERNAL_ERROR,
}


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: str
    command_mode: CommandMode
    verdict: CommandVerdict
    ready: bool
    exit_code: int
    reason_codes: tuple[str, ...]
    details: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.command.strip():
            raise ValueError("command is required")
        if isinstance(self.exit_code, bool) or self.exit_code not in {
            int(item) for item in CommandExitCode
        }:
            raise ValueError("exit_code is outside the PR-189 contract")
        if self.ready != (self.verdict is CommandVerdict.PASSED):
            raise ValueError("ready must match the passed verdict")
        if not self.reason_codes and not self.ready:
            raise ValueError("non-ready command result requires reason_codes")
        expected = exit_code_for(self.command_mode, self.verdict)
        if self.exit_code != expected:
            raise ValueError("payload exit_code does not match mode/verdict")

    @property
    def check_passed(self) -> bool | None:
        if self.command_mode is CommandMode.INSPECT:
            return None
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "command": self.command,
            "command_mode": self.command_mode.value,
            "verdict": self.verdict.value,
            "ready": self.ready,
            "check_passed": self.check_passed,
            "exit_code": self.exit_code,
            "reason_codes": list(self.reason_codes),
            "details": dict(self.details),
        }


def exit_code_for(mode: CommandMode, verdict: CommandVerdict) -> int:
    if mode is CommandMode.INSPECT and verdict not in {
        CommandVerdict.ERROR,
        CommandVerdict.SECURITY_VIOLATION,
    }:
        return int(CommandExitCode.OK)
    return int(_CHECK_EXIT_CODES[verdict])


def result(
    *,
    command: str,
    mode: CommandMode,
    ready: bool,
    reason_codes: Sequence[str] = (),
    details: Mapping[str, Any] | None = None,
    verdict: CommandVerdict | None = None,
) -> CommandResult:
    effective_verdict = verdict or (
        CommandVerdict.PASSED if ready else CommandVerdict.BLOCKED
    )
    normalized_reasons = tuple(
        dict.fromkeys(str(item) for item in reason_codes if item)
    )
    if ready and normalized_reasons:
        raise ValueError("passed command result cannot contain blocker reason_codes")
    if not ready and not normalized_reasons:
        normalized_reasons = ("PR189_UNSPECIFIED_BLOCKER",)
    return CommandResult(
        command=command,
        command_mode=mode,
        verdict=effective_verdict,
        ready=ready,
        exit_code=exit_code_for(mode, effective_verdict),
        reason_codes=normalized_reasons,
        details={} if details is None else details,
    )


def error_result(
    *,
    command: str,
    mode: CommandMode,
    reason_code: str,
    error_type: str,
) -> CommandResult:
    return result(
        command=command,
        mode=mode,
        ready=False,
        verdict=CommandVerdict.ERROR,
        reason_codes=(reason_code,),
        details={"error_type": error_type},
    )
