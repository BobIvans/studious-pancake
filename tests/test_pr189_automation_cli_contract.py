from __future__ import annotations

import pytest

from src.cli_contract_pr189 import (
    CommandExitCode,
    CommandMode,
    CommandResult,
    CommandVerdict,
    error_result,
    result,
)


def test_blocked_inspection_is_explicit_but_exits_zero() -> None:
    outcome = result(
        command="paper-vertical",
        mode=CommandMode.INSPECT,
        ready=False,
        reason_codes=("BLOCKED_DEPENDENCIES",),
    )
    assert outcome.verdict is CommandVerdict.BLOCKED
    assert outcome.ready is False
    assert outcome.exit_code == CommandExitCode.OK
    assert outcome.check_passed is None


def test_blocked_check_is_nonzero_without_optional_flag() -> None:
    outcome = result(
        command="paper-vertical",
        mode=CommandMode.CHECK,
        ready=False,
        reason_codes=("BLOCKED_DEPENDENCIES",),
    )
    assert outcome.exit_code == CommandExitCode.BLOCKED
    assert outcome.check_passed is False


def test_passed_check_is_zero_and_ready() -> None:
    outcome = result(
        command="qualification-verdict",
        mode=CommandMode.CHECK,
        ready=True,
    )
    assert outcome.verdict is CommandVerdict.PASSED
    assert outcome.ready is True
    assert outcome.exit_code == CommandExitCode.OK
    assert outcome.check_passed is True


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        (CommandVerdict.STALE, CommandExitCode.STALE),
        (CommandVerdict.UNAVAILABLE, CommandExitCode.DEPENDENCY_UNAVAILABLE),
        (CommandVerdict.SECURITY_VIOLATION, CommandExitCode.SECURITY_VIOLATION),
        (CommandVerdict.ERROR, CommandExitCode.MALFORMED_OR_INTERNAL_ERROR),
    ],
)
def test_check_exit_taxonomy(verdict: CommandVerdict, expected: int) -> None:
    outcome = result(
        command="readiness",
        mode=CommandMode.CHECK,
        ready=False,
        verdict=verdict,
        reason_codes=("REASON",),
    )
    assert outcome.exit_code == expected


def test_inspection_does_not_hide_security_violation() -> None:
    outcome = result(
        command="provider-readiness",
        mode=CommandMode.INSPECT,
        ready=False,
        verdict=CommandVerdict.SECURITY_VIOLATION,
        reason_codes=("CREDENTIAL_LEAK",),
    )
    assert outcome.exit_code == CommandExitCode.SECURITY_VIOLATION


def test_payload_exit_code_must_match_mode_and_verdict() -> None:
    with pytest.raises(ValueError, match="does not match"):
        CommandResult(
            command="paper-vertical",
            command_mode=CommandMode.CHECK,
            verdict=CommandVerdict.BLOCKED,
            ready=False,
            exit_code=0,
            reason_codes=("BLOCKED",),
        )


def test_non_ready_result_requires_reason_code() -> None:
    with pytest.raises(ValueError, match="requires reason_codes"):
        CommandResult(
            command="paper-vertical",
            command_mode=CommandMode.CHECK,
            verdict=CommandVerdict.BLOCKED,
            ready=False,
            exit_code=3,
            reason_codes=(),
        )


def test_error_result_redacts_exception_text() -> None:
    outcome = error_result(
        command="release-soak",
        mode=CommandMode.CHECK,
        reason_code="PR189_COMMAND_INPUT_OR_RUNTIME_ERROR",
        error_type="ValueError",
    )
    payload = outcome.to_dict()
    assert payload["details"] == {"error_type": "ValueError"}
    assert "secret" not in str(payload).lower()
