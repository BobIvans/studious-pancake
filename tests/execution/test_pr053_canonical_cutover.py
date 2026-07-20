from __future__ import annotations

from pathlib import Path

import pytest

from src.execution.shadow import (
    CompilerDiagnostics,
    ReconciliationResult,
    ShadowReason,
    ShadowReconciler,
    SimulationReport,
    SimulationRequest,
)

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_transaction_plan_no_positional_legacy_constructor() -> None:
    source = _read("src/execution/models.py")

    assert "@dataclass(frozen=True, slots=True, init=False)" not in source
    assert "Legacy positional layout" not in source
    assert "def __init__(self, opportunity_id" not in source


def test_active_compiler_has_no_legacy_or_synthetic_branch() -> None:
    source = _read("src/execution/transaction_compiler.py")

    for forbidden in (
        "_compile_legacy",
        "_normalize_legacy_plan",
        "legacy_instruction",
        "flash loan plan required",
        "stable_bytes()",
        'b"unsigned:"',
    ):
        assert forbidden not in source


def test_shadow_source_has_no_log_or_prefix_repayment_proof() -> None:
    source = _read("src/execution/shadow.py")

    assert ".removeprefix(" not in source
    assert '"repay" in' not in source
    assert "'repay' in" not in source


def test_shadow_rejects_non_canonical_unsigned_envelope() -> None:
    request = SimulationRequest(
        opportunity_id="opp",
        attempt_id="attempt",
        plan_hash="p" * 64,
        message_hash="a" * 64,
        serialized_transaction=bytes.fromhex("756e7369676e65643a") + b"message",
        expected_signer_count=1,
        monitored_native_accounts=(),
    )

    with pytest.raises(ValueError, match=ShadowReason.MESSAGE_HASH_MISMATCH.value):
        request.rpc_payload()


def test_repay_log_line_does_not_prove_flash_loan_repayment() -> None:
    request = SimulationRequest(
        opportunity_id="opp",
        attempt_id="attempt",
        plan_hash="p" * 64,
        message_hash="a" * 64,
        serialized_transaction=b"\x80canonical-versioned-transaction",
        expected_signer_count=1,
        monitored_native_accounts=("payer",),
        compiler_diagnostics=CompilerDiagnostics(static_account_keys=("payer",)),
    )
    report = SimulationReport(
        request=request,
        endpoint="replay://local",
        context_slot=10,
        api_version=None,
        err=None,
        logs=("Program log: marginfi repay complete",),
        inner_instructions=None,
        units_consumed=1,
        fee=0,
        loaded_addresses={"writable": (), "readonly": ()},
        pre_balances=(1_000,),
        post_balances=(1_000,),
        pre_token_balances=(),
        post_token_balances=(),
        response_hash="r" * 64,
        reason=None,
    )

    result: ReconciliationResult = ShadowReconciler().reconcile(
        report,
        required_repayment=1,
        observed_repayment=None,
    )

    assert result.reason is ShadowReason.REPAYMENT_NOT_PROVEN
    assert result.repayment.observed == 0
    assert result.repayment.proven is False
