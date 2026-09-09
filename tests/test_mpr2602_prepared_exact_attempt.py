"""Prepared identity on the real PR-152 path, using offline raw WSOL vectors.

Only account/RPC inputs are synthetic. Reader, provider, planner, compiler,
exact finalizer, decoder, economics, capital and PR-02 authority are production
components. These tests do not establish deployed conformance or live readiness.
"""

from __future__ import annotations

import base64
import copy
from dataclasses import replace
import json

import pytest
from solders.pubkey import Pubkey

from src.durability import AttemptKey
from src.economics.capital import CapitalCandidate, CapitalPolicy, NativeCostBreakdown
from src.economics.durable_reservations import (
    DurableCapitalCoordinator,
    WalletBalanceSnapshot,
)
from src.execution.economic_reconciliation import AssetKey, NATIVE_SOL_ASSET
from src.execution.economic_reconciliation.mega_pr02_proof import (
    ConservativeAssetQuote,
    ConservativeValuationSnapshot,
)
from src.execution.exact_simulation import ExactSimulationFinalizer
from src.paper_shadow.atomic_vertical import AtomicPlannerSimulationReconciliationVertical
from src.paper_shadow.exact_attempt_pr152 import (
    ExactAttemptRequest,
    ExactAttemptStatus,
    ExactPaperAttemptOrchestrator,
    ProviderExecutionEvidence,
)
from src.paper_shadow.mpr2602_runtime import validate_prepared_plan_hash
from src.planning.atomic_marginfi_jupiter import AtomicMarginfiJupiterPlanner
from src.providers.marginfi import (
    MarginfiAccountReader,
    MarginfiFlashLoanProvider,
    RpcAccount,
    load_marginfi_contract_pin,
)
from tests.test_mpr2602_full_flashloan_vertical import (
    BRIDGE_TOKEN,
    RAW_BANK,
    RAW_GROUP,
    RAW_MARGIN,
    RAW_PAYER,
    RAW_VAULT,
    TOKEN,
    USDC,
    WALLET_TOKEN,
    WSOL,
    offline_vertical_fixture,
)
from tests.test_pr02_unified_lifecycle_authority import authority, digest

pytestmark = pytest.mark.unit
RENT = 2_039_280


def _wsol_account(address, account):
    account = copy.deepcopy(account)
    data = bytearray(base64.b64decode(account["data"][0]))
    if address == RAW_BANK:
        data[8:40] = bytes(Pubkey.from_string(WSOL))
        data[40] = 9
    elif address in (RAW_VAULT, WALLET_TOKEN):
        data[:32] = bytes(Pubkey.from_string(WSOL))
        data[109:113] = (1).to_bytes(4, "little")
        data[113:121] = RENT.to_bytes(8, "little")
        account["lamports"] = RENT + int.from_bytes(data[64:72], "little")
    elif address == BRIDGE_TOKEN:
        data[:32] = bytes(Pubkey.from_string(USDC))
        data[109:121] = bytes(12)
        account["lamports"] = RENT
    account["data"] = [base64.b64encode(data).decode(), "base64"]
    return account


def _wsol_vertical():
    original, candidate, original_rpc = offline_vertical_fixture()
    plan = original.planner.plan(candidate.request)
    monitored = (RAW_PAYER, *(str(k) for k in plan.transaction_plan.monitored_accounts))
    pre = {
        address: _wsol_account(address, account)
        for address, account in zip(monitored, candidate.pre_state_accounts)
    }
    pin = load_marginfi_contract_pin()

    class Accounts:
        def get_multiple_accounts(self, addresses, *, min_context_slot=None):
            values = []
            for address in addresses:
                if address == pin.program_id:
                    values.append(RpcAccount(address, pin.raw["program_owner"], b"", executable=True))
                else:
                    raw = pre[address]
                    values.append(RpcAccount(address, raw["owner"], base64.b64decode(raw["data"][0]), raw["lamports"]))
            return 22, tuple(values)

    snapshot = MarginfiAccountReader(pin, Accounts(), clock=lambda: 1000.0).read(
        group=RAW_GROUP,
        margin_account=RAW_MARGIN,
        authority=RAW_PAYER,
        bank=RAW_BANK,
        symbol="WSOL",
        amount=1000,
    )
    request = replace(
        candidate.request,
        marginfi_snapshot=snapshot,
        leg_a=replace(candidate.request.leg_a, input_mint=WSOL, output_mint=USDC),
        leg_b=replace(candidate.request.leg_b, input_mint=USDC, output_mint=WSOL),
        marginfi_source_vectors=replace(
            candidate.request.marginfi_source_vectors,
            snapshot_fingerprint=snapshot.state_fingerprint,
        ),
    )
    settlement = AssetKey(WSOL, TOKEN, 9)
    bridge = AssetKey(USDC, TOKEN, 6)
    candidate = replace(
        candidate,
        request=request,
        settlement_asset=settlement,
        approved_assets=(settlement, bridge),
        pre_state_accounts=tuple(pre[address] for address in monitored),
        valuation=ConservativeValuationSnapshot(
            "offline-test-unit",
            (
                ConservativeAssetQuote(settlement, 1, "c" * 64, 22),
                ConservativeAssetQuote(NATIVE_SOL_ASSET, 1, "d" * 64, 22),
                ConservativeAssetQuote(bridge, 1, "e" * 64, 22),
            ),
            22, 2, 0,
        ),
    )

    class Rpc:
        calls = 0
        mutate = None

        async def call(self, method, params):
            result = await original_rpc.call(method, params)
            if method == "simulateTransaction":
                self.calls += 1
                result = copy.deepcopy(result)
                result["value"]["accounts"] = [
                    _wsol_account(address, account)
                    for address, account in zip(monitored, result["value"]["accounts"])
                ]
                if self.mutate is not None:
                    self.mutate()
            return result

    rpc = Rpc()
    vertical = AtomicPlannerSimulationReconciliationVertical(
        AtomicMarginfiJupiterPlanner(
            MarginfiFlashLoanProvider(pin), original.planner._policy, clock=lambda: 1000.0
        ),
        ExactSimulationFinalizer(rpc),
    )
    return vertical, candidate, rpc


def _attempt(tmp_path, *, with_authority=True):
    store, clock = authority(tmp_path)
    vertical, candidate, rpc = _wsol_vertical()
    provenance = vertical.planner.plan(candidate.request).provenance
    coordinator = DurableCapitalCoordinator(
        store=store.lifecycle,
        policy=CapitalPolicy(
            protected_reserve_lamports=0,
            minimum_net_profit_lamports=1,
            contingency_lamports=0,
        ),
    )
    holder = {}

    def factory(reservation):
        prepared = replace(candidate, request=replace(candidate.request, capital=reservation))
        holder["candidate"] = prepared
        return prepared

    request = ExactAttemptRequest(
        attempt_key=AttemptKey(candidate.request.opportunity_id, digest("wsol-seed"), 1),
        capital_candidate=CapitalCandidate(
            candidate_id=candidate.request.opportunity_id,
            guaranteed_min_out_lamports=21125,
            flash_repayment_lamports=1125,
            requested_flash_loan_lamports=1000,
            native_costs=NativeCostBreakdown(base_network_fee_lamports=5000),
        ),
        wallet_snapshot=WalletBalanceSnapshot(
            wallet_pubkey=RAW_PAYER,
            native_lamports=100000,
            context_slot=22,
            captured_at_ns=clock.utc_ns,
            cluster_genesis=store.cluster_genesis,
            source="offline-source-vector",
        ),
        provider_evidence=ProviderExecutionEvidence(
            candidate.request.jupiter_contract_pin,
            provenance.marginfi_pin_hash,
            candidate.request.marginfi_snapshot.state_fingerprint,
            22, clock.utc_ns, clock.utc_ns + 10000, True, True,
        ),
        discovery_slot=22,
        candidate_factory=factory,
        reserve_idempotency_key="wsol-reserve",
        release_idempotency_key="wsol-release",
        final_fee_idempotency_key="wsol-fee",
    )
    orchestrator = ExactPaperAttemptOrchestrator(
        coordinator=coordinator,
        vertical=vertical,
        clock_ns=lambda: clock.utc_ns,
        authority=store if with_authority else None,
    )
    return store, orchestrator, request, rpc, holder


@pytest.mark.asyncio
async def test_real_exact_attempt_binds_prepared_plan_before_qualified_handoff(tmp_path):
    store, orchestrator, request, rpc, holder = _attempt(tmp_path)
    try:
        result = await orchestrator.run(request)
        assert result.ready, result.blockers
        assert rpc.calls == 2
        assert result.vertical.qualification.qualified
        assert result.vertical.qualification.quote_net == 15000
        assert result.exact_fee.accepted
        validate_prepared_plan_hash(holder["candidate"], result.prepared_plan_hash)
        payload = json.loads(store.db.execute("SELECT payload_json FROM pr02_intents WHERE intent_kind='paper_attempt'").fetchone()[0])
        assert payload["prepared_plan_hash"] == result.prepared_plan_hash
        assert result.result_hash != replace(result, prepared_plan_hash="f" * 64).result_hash
        assert not result.sender_imported and not result.submission_allowed
        # A qualified exact handoff is deliberately not a committed success.
        assert store.db.execute("SELECT COUNT(*) FROM pr02_terminal_records").fetchone()[0] == 0
    finally:
        store.close()


@pytest.mark.asyncio
async def test_prepared_replay_and_drift_do_not_repeat_rpc_or_release_owner(tmp_path):
    store, orchestrator, request, rpc, holder = _attempt(tmp_path)
    try:
        first = await orchestrator.run(request)
        assert first.ready, first.blockers
        replay = await orchestrator.run(request)
        assert replay.blockers == ("MPR2602_PREPARED_REPLAY_REQUIRES_RECONCILIATION",)
        assert not replay.reservation_released
        original_factory = request.candidate_factory

        def changed_factory(reservation):
            prepared = original_factory(reservation)
            leg = replace(prepared.request.leg_a, route_plan=({"label": "changed-route"},))
            return replace(prepared, request=replace(prepared.request, leg_a=leg))

        changed = await orchestrator.run(replace(request, candidate_factory=changed_factory))
        assert changed.blockers == ("MPR2602_PREPARED_AUTHORITY_CONFLICT",)
        assert not changed.reservation_released
        assert rpc.calls == 2
        assert store.db.execute("SELECT state FROM durable_reservations").fetchone()[0] == "active"
        assert store.db.execute("SELECT COUNT(*) FROM pr02_intents WHERE intent_kind='paper_attempt'").fetchone()[0] == 1
    finally:
        store.close()


@pytest.mark.asyncio
async def test_mutation_during_real_simulation_commits_one_atomic_rejection(tmp_path):
    store, orchestrator, request, rpc, holder = _attempt(tmp_path)
    mutated = []
    try:
        def mutate():
            holder["candidate"].request.leg_a.route_plan[0]["label"] = "changed-in-flight"
            mutated.append(True)

        rpc.mutate = mutate
        result = await orchestrator.run(request)
        assert mutated
        assert result.status is ExactAttemptStatus.VERTICAL_BLOCKED
        assert result.reservation_released
        assert result.prepared_plan_hash
        assert result.exact_fee is None
        assert store.db.execute("SELECT state FROM durable_reservations").fetchone()[0] == "released"
        assert store.db.execute("SELECT COUNT(*) FROM pr02_terminal_records").fetchone()[0] == 1
        assert store.db.execute("SELECT COUNT(*) FROM pr02_outbox_event WHERE topic='paper.attempt.terminal'").fetchone()[0] == 1
    finally:
        store.close()


@pytest.mark.asyncio
async def test_raw_attempt_without_shared_authority_cannot_simulate(tmp_path):
    store, orchestrator, request, rpc, _holder = _attempt(tmp_path, with_authority=False)
    try:
        result = await orchestrator.run(request)
        assert result.status is ExactAttemptStatus.VERTICAL_BLOCKED
        assert result.reservation_released
        assert rpc.calls == 0
        assert store.db.execute("SELECT COUNT(*) FROM pr02_intents").fetchone()[0] == 0
    finally:
        store.close()
