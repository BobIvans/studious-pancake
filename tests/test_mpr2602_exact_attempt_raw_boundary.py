"""PR152 consumer-boundary fixtures, not full protocol/external qualification."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.execution.state_evidence_pr115 import (
    PR115DecodePolicy,
    PR115MarginfiDecodePolicy,
)
from src.execution.economic_reconciliation.mega_pr02_proof import (
    EconomicProofQualification,
    QualificationStatus,
    QualificationReason,
)
from src.execution.economic_reconciliation.models import AssetKey, ReconciliationStatus
from src.paper_shadow.atomic_vertical import AtomicVerticalCandidate
from src.paper_shadow.exact_attempt_pr152 import (
    ExactPaperAttemptOrchestrator,
    ExactAttemptStatus,
)
from tests.test_mpr2602_prepared_exact_attempt import _attempt
from tests.test_pr152_exact_sender_free_attempt import (
    _request,
    FakeCoordinator,
    FakeVertical,
    SHA_C,
)

WSOL = "So11111111111111111111111111111111111111112"
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


def _raw():
    snapshot = SimpleNamespace(
        state_fingerprint=SHA_C,
        slot=100,
        group="group",
        margin_account=SimpleNamespace(address="margin", authority="wallet"),
        bank=SimpleNamespace(
            address="bank",
            liquidity_vault="vault",
            mint=WSOL,
            mint_decimals=9,
            token_program=TOKEN,
        ),
    )
    planner = SimpleNamespace(
        opportunity_id="opportunity-1",
        jupiter_contract_pin="a" * 64,
        marginfi_snapshot=snapshot,
        payer="wallet",
        borrow_amount=1_000_000,
    )
    policy = PR115DecodePolicy(
        marginfi=PR115MarginfiDecodePolicy(
            source_commit="a" * 40,
            layout_sha256="b" * 64,
            margin_account="margin",
            group="group",
            authority="wallet",
            bank="bank",
            vault="vault",
            principal=1_000_000,
        )
    )
    # Raw bytes are deliberately not qualified in this boundary fixture. The
    # downstream real decoder must still validate them before any real handoff.
    return AtomicVerticalCandidate(
        request=planner,
        blockhash=None,
        settlement_asset=AssetKey(WSOL, TOKEN, 9),
        pre_state_accounts=({},),
        pre_state_slot=100,
        decode_policy=policy,
        valuation=SimpleNamespace(valuation_hash="1" * 64),
        marginfi_registry=SimpleNamespace(registry_hash="2" * 64),
    )


def _orchestrator(vertical=None):
    return ExactPaperAttemptOrchestrator(
        coordinator=FakeCoordinator(),
        vertical=vertical or FakeVertical(),
        clock_ns=lambda: 1500,
    )


def _qualification(net=1, qualified=True):
    return EconomicProofQualification(
        status=(
            QualificationStatus.QUALIFIED_PROFIT
            if qualified
            else QualificationStatus.PROVEN_LOSS
        ),
        reason=(
            QualificationReason.QUALIFIED_STRICT_POSITIVE_VALUE
            if qualified
            else QualificationReason.NEGATIVE_CROSS_ASSET_NET
        ),
        qualified=qualified,
        report_status=ReconciliationStatus.PROVEN_PROFIT,
        quote_currency="fixture",
        quote_net=net,
        min_profit_quote_units=1,
        valuation_hash="1" * 64,
        registry_hash="2" * 64,
        diagnostic="consumer boundary fixture",
    )


def test_raw_candidate_admission_uses_planner_snapshot_not_caller_decoded_hashes():
    _orchestrator()._validate_candidate(_raw(), _request())
    with pytest.raises(ValueError, match="caller economics"):
        _orchestrator()._validate_candidate(
            replace(_raw(), decoded_account_hashes=(SHA_C,)), _request()
        )


@pytest.mark.parametrize(
    "change",
    [
        "snapshot",
        "slot",
        "policy-bank",
        "policy-principal",
        "usdc",
        "decimals",
        "amount",
    ],
)
def test_raw_candidate_rejects_snapshot_policy_and_unit_drift(change):
    candidate = _raw()
    if change == "snapshot":
        candidate.request.marginfi_snapshot.state_fingerprint = "9" * 64
    elif change == "slot":
        candidate = replace(candidate, pre_state_slot=99)
    elif change in {"policy-bank", "policy-principal"}:
        policy = replace(
            candidate.decode_policy.marginfi,
            **({"bank": "attacker"} if change == "policy-bank" else {"principal": 3}),
        )
        candidate = replace(
            candidate, decode_policy=replace(candidate.decode_policy, marginfi=policy)
        )
    elif change == "usdc":
        candidate.request.marginfi_snapshot.bank.mint = (
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        )
    elif change == "decimals":
        candidate.request.marginfi_snapshot.bank.mint_decimals = 6
    else:
        candidate.request.borrow_amount = 3
    with pytest.raises(ValueError):
        _orchestrator()._validate_candidate(candidate, _request())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "qualification",
    [
        None,
        _qualification(net=-5, qualified=False),
        _qualification(net=-5),
        _qualification(net=0),
    ],
)
async def test_unqualified_or_negative_cross_asset_result_never_reaches_handoff(
    qualification,
    tmp_path,
):
    store, orchestrator, request, rpc, _holder = _attempt(tmp_path)
    production_vertical = orchestrator.vertical

    class BoundaryVertical:
        async def run(self, candidate):
            result = await production_vertical.run(candidate)
            return replace(result, qualification=qualification)

    orchestrator.vertical = BoundaryVertical()
    try:
        result = await orchestrator.run(request)
        # Prove the qualification boundary ran, rather than passing because an
        # unrelated reservation/authority check rejected an incomplete fake.
        assert rpc.calls == 2
        assert result.status is ExactAttemptStatus.VERTICAL_BLOCKED
        assert result.blockers == ("PR152_VERTICAL_VALUEERROR",)
        assert result.reservation_released
        assert (
            store.db.execute("SELECT COUNT(*) FROM pr02_terminal_records").fetchone()[0]
            == 1
        )
    finally:
        store.close()


@pytest.mark.asyncio
async def test_positive_qualification_boundary_checks_provenance_without_claiming_full_vertical():
    candidate = _raw()
    result = await FakeVertical().run(candidate)
    result.qualification = _qualification()
    result.raw_evidence_hash = "3" * 64
    result.evidence_origin = "decoder_owned_offline"
    result.reconciliation = SimpleNamespace(status=ReconciliationStatus.PROVEN_PROFIT)
    ExactPaperAttemptOrchestrator._validate_vertical(result, _request(), candidate)
    result.qualification = replace(result.qualification, valuation_hash="4" * 64)
    with pytest.raises(ValueError, match="provenance"):
        ExactPaperAttemptOrchestrator._validate_vertical(result, _request(), candidate)


@pytest.mark.asyncio
async def test_raw_boundary_runs_vertical_failure_and_releases_without_leaking_error(
    tmp_path,
):
    class FailingVertical:
        calls = 0

        async def run(self, candidate):
            self.calls += 1
            raise RuntimeError("fixture private diagnostic")

    store, orchestrator, request, rpc, _holder = _attempt(tmp_path)
    vertical = FailingVertical()
    orchestrator.vertical = vertical
    try:
        result = await orchestrator.run(request)
        assert vertical.calls == 1
        assert rpc.calls == 0
        assert result.status is ExactAttemptStatus.VERTICAL_BLOCKED
        assert result.blockers == ("PR152_VERTICAL_RUNTIMEERROR",)
        assert result.reservation_released
        assert result.prepared_plan_hash is not None
        assert "private" not in repr(result.blockers)
        assert (
            store.db.execute("SELECT COUNT(*) FROM pr02_terminal_records").fetchone()[0]
            == 1
        )
        assert (
            store.db.execute("SELECT COUNT(*) FROM pr02_outbox_event").fetchone()[0]
            == 1
        )
    finally:
        store.close()


@pytest.mark.asyncio
async def test_raw_boundary_rejects_final_provider_pin_drift():
    candidate = _raw()
    result = await FakeVertical(jupiter_pin="9" * 64).run(candidate)
    with pytest.raises(ValueError, match="Jupiter provenance"):
        ExactPaperAttemptOrchestrator._validate_vertical(result, _request(), candidate)
