from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from src.durability import AttemptKey
from src.economics.capital import CapitalCandidate, NativeCostBreakdown
from src.economics.durable_reservations import WalletBalanceSnapshot
from src.paper_shadow.atomic_vertical import AtomicVerticalCandidate, AtomicVerticalResult
from src.paper_shadow.exact_attempt_pr152 import (
    ExactAttemptRequest,
    ExactAttemptStatus,
    ExactPaperAttemptOrchestrator,
    ProviderExecutionEvidence,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


class FakeReason:
    value = "accepted"


@dataclass
class FakeDecision:
    required_native_lamports: int = 5_000
    allowed: bool = True
    reservation_id: str | None = "reservation-1"
    reason: FakeReason = FakeReason()

    def to_json(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "required_native_lamports": str(self.required_native_lamports),
            "reservation_id": self.reservation_id,
        }


@dataclass
class FakeAttempt:
    attempt_id: str = "attempt-1"
    reserved_lamports: int = 5_000


class FakeStore:
    def __init__(self, attempt: FakeAttempt) -> None:
        self.attempt = attempt

    def get_attempt(self, attempt_id: str) -> FakeAttempt | None:
        return self.attempt if attempt_id == self.attempt.attempt_id else None


class FakeCoordinator:
    def __init__(self) -> None:
        self.attempt = FakeAttempt()
        self.store = FakeStore(self.attempt)
        self.reserve_calls = 0
        self.released = False

    def reserve(self, *args: object, **kwargs: object) -> object:
        self.reserve_calls += 1
        return SimpleNamespace(
            decision=FakeDecision(),
            attempt=self.attempt,
            wallet_snapshot=kwargs["wallet_snapshot"],
            active_durable_reserved_lamports=0,
            recovery_attempt_ids=(),
        )

    def evaluate_for_attempt(self, candidate: CapitalCandidate, **kwargs: object) -> object:
        required = candidate.native_costs.base_network_fee_lamports
        return SimpleNamespace(
            decision=FakeDecision(required_native_lamports=required),
            attempt=self.attempt,
        )

    def release_pre_submission_reservation(self, *args: object, **kwargs: object) -> bool:
        self.released = True
        return True


@dataclass
class FakeVertical:
    fee_lamports: int = 5_000
    error: Exception | None = None
    jupiter_pin: str = SHA_A

    async def run(self, candidate: AtomicVerticalCandidate) -> AtomicVerticalResult:
        if self.error is not None:
            raise self.error
        message_hash = "f" * 64
        return cast(
            AtomicVerticalResult,
            SimpleNamespace(
                planner_result=SimpleNamespace(
                    provenance=SimpleNamespace(
                        jupiter_contract_pin=self.jupiter_pin,
                        marginfi_pin_hash=SHA_B,
                    )
                ),
                finalized=SimpleNamespace(
                    report=SimpleNamespace(fee_context_slot=101)
                ),
                trace=SimpleNamespace(
                    opportunity_id="opportunity-1",
                    planner_digest="d" * 64,
                    reconciliation_hash="e" * 64,
                    message_hash=message_hash,
                    final_fee_lamports=self.fee_lamports,
                ),
            ),
        )


def _capital() -> CapitalCandidate:
    return CapitalCandidate(
        candidate_id="opportunity-1",
        guaranteed_min_out_lamports=2_000_000,
        flash_repayment_lamports=1_000_000,
        requested_flash_loan_lamports=1_000_000,
        native_costs=NativeCostBreakdown(base_network_fee_lamports=5_000),
    )


def _evidence(*, expires_at_ns: int = 2_000) -> ProviderExecutionEvidence:
    return ProviderExecutionEvidence(
        jupiter_contract_pin=SHA_A,
        marginfi_program_hash=SHA_B,
        account_snapshot_hash=SHA_C,
        rooted_slot=100,
        captured_at_ns=1_000,
        expires_at_ns=expires_at_ns,
        jupiter_execution_allowed=True,
        marginfi_execution_allowed=True,
    )


def _factory(reservation: object) -> AtomicVerticalCandidate:
    return cast(
        AtomicVerticalCandidate,
        SimpleNamespace(
            request=SimpleNamespace(
                opportunity_id="opportunity-1",
                jupiter_contract_pin=SHA_A,
                capital=reservation,
            ),
            decoded_account_hashes=(SHA_C,),
        ),
    )


def _request(*, expires_at_ns: int = 2_000) -> ExactAttemptRequest:
    return ExactAttemptRequest(
        attempt_key=AttemptKey("opportunity-1", SHA_C, 1),
        capital_candidate=_capital(),
        wallet_snapshot=WalletBalanceSnapshot(
            wallet_pubkey="wallet",
            native_lamports=100_000,
            context_slot=100,
        ),
        provider_evidence=_evidence(expires_at_ns=expires_at_ns),
        discovery_slot=100,
        candidate_factory=_factory,
        reserve_idempotency_key="reserve-1",
        release_idempotency_key="release-1",
        final_fee_idempotency_key="fee-1",
    )


@pytest.mark.asyncio
async def test_pr152_ready_attempt_binds_reservation_message_fee_and_reconciliation() -> None:
    coordinator = FakeCoordinator()
    result = await ExactPaperAttemptOrchestrator(
        coordinator=cast(object, coordinator),
        vertical=FakeVertical(),
        clock_ns=lambda: 1_500,
    ).run(_request())

    assert result.status is ExactAttemptStatus.READY_FOR_DURABLE_PAPER
    assert result.message_hash == "f" * 64
    assert result.reconciliation_hash == "e" * 64
    assert result.sender_imported is False
    assert result.submission_allowed is False
    assert len(result.result_hash) == 64


@pytest.mark.asyncio
async def test_pr152_expired_provider_evidence_blocks_before_reservation() -> None:
    coordinator = FakeCoordinator()
    result = await ExactPaperAttemptOrchestrator(
        coordinator=cast(object, coordinator),
        vertical=FakeVertical(),
        clock_ns=lambda: 2_001,
    ).run(_request(expires_at_ns=2_000))

    assert result.status is ExactAttemptStatus.PROVIDER_BLOCKED
    assert "PR152_PROVIDER_EVIDENCE_EXPIRED" in result.blockers
    assert coordinator.reserve_calls == 0


@pytest.mark.asyncio
async def test_pr152_vertical_failure_releases_reserved_capital() -> None:
    coordinator = FakeCoordinator()
    result = await ExactPaperAttemptOrchestrator(
        coordinator=cast(object, coordinator),
        vertical=FakeVertical(error=RuntimeError("raw secret-shaped error")),
        clock_ns=lambda: 1_500,
    ).run(_request())

    assert result.status is ExactAttemptStatus.VERTICAL_BLOCKED
    assert result.reservation_released is True
    assert coordinator.released is True
    assert "secret-shaped" not in repr(result.blockers)


@pytest.mark.asyncio
async def test_pr152_final_fee_above_reservation_releases_capital() -> None:
    coordinator = FakeCoordinator()
    result = await ExactPaperAttemptOrchestrator(
        coordinator=cast(object, coordinator),
        vertical=FakeVertical(fee_lamports=10_000),
        clock_ns=lambda: 1_500,
    ).run(_request())

    assert result.status is ExactAttemptStatus.FINAL_FEE_BLOCKED
    assert result.reservation_released is True
    assert coordinator.released is True


@pytest.mark.asyncio
async def test_pr152_final_provider_pin_mismatch_fails_closed() -> None:
    coordinator = FakeCoordinator()
    result = await ExactPaperAttemptOrchestrator(
        coordinator=cast(object, coordinator),
        vertical=FakeVertical(jupiter_pin="9" * 64),
        clock_ns=lambda: 1_500,
    ).run(_request())

    assert result.status is ExactAttemptStatus.VERTICAL_BLOCKED
    assert result.reservation_released is True


def test_pr152_module_has_no_signer_or_sender_imports() -> None:
    source = Path("src/paper_shadow/exact_attempt_pr152.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any("signer" in name or "sender" in name for name in imports)
