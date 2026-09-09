"""Offline real compiler/finalizer -> PR115 regressions; only RPC is a fixture.

Account bytes are synthetic legacy SPL layout vectors, not deployed evidence.
No keypair, signer, transport, or submission capability is created.
"""

from __future__ import annotations

import base64
import copy
from dataclasses import asdict, replace
from typing import Any

import pytest
from solders.hash import Hash
from solders.instruction import Instruction
from solders.pubkey import Pubkey

from src.execution.exact_simulation import (
    ExactSimulationError,
    ExactSimulationFinalizer,
    ExactSimulationPolicy,
)
from src.execution.models import BlockhashContext, PlannedInstruction, TransactionPlan
from src.execution.state_evidence_pr115 import (
    PR115DecodePolicy,
    PR115StateEvidenceError,
    SPL_TOKEN_PROGRAM_ID,
    SYSTEM_PROGRAM_ID,
    build_pr115_proof_from_report,
)

pytestmark = pytest.mark.unit
PAYER = Pubkey.from_bytes(bytes([5]) * 32)
TOKEN = Pubkey.from_bytes(bytes([6]) * 32)


def _native(lamports: int) -> dict[str, Any]:
    return dict(
        lamports=lamports,
        owner=SYSTEM_PROGRAM_ID,
        executable=False,
        data=["", "base64"],
        rentEpoch=0,
    )


def _token(amount: int) -> dict[str, Any]:
    data = bytearray(165)
    data[:32] = bytes([7]) * 32
    data[32:64] = bytes([5]) * 32
    data[64:72] = amount.to_bytes(8, "little")
    data[108] = 1  # initialized legacy SPL account
    return dict(
        lamports=2_039_280,
        owner=SPL_TOKEN_PROGRAM_ID,
        executable=False,
        data=[base64.b64encode(data).decode("ascii"), "base64"],
        rentEpoch=0,
    )


class FixtureRpc:
    def __init__(self, post: Any) -> None:
        self.post = post
        self.calls: list[tuple[str, list[Any]]] = []
        self.simulations = 0

    async def call(self, method: str, params: list[Any]) -> Any:
        self.calls.append((method, params))
        if method == "getBlockHeight":
            return 50
        if method == "isBlockhashValid":
            return {"context": {"slot": 20}, "value": True}
        if method == "getFeeForMessage":
            return {"context": {"slot": 23}, "value": 5000}
        assert method == "simulateTransaction", "fixture denies every other RPC method"
        self.simulations += 1
        return {
            "context": {"slot": 20 + self.simulations},
            "value": {
                "err": None,
                "logs": [],
                "unitsConsumed": 100_000,
                "loadedAccountsDataSize": 165,
                "accounts": (
                    self.post
                    if self.simulations == 2
                    else [_native(100_000), _token(100)]
                ),
            },
        }


async def _finalize(post: Any, *, policy=None):
    rpc = FixtureRpc(post)
    plan = TransactionPlan(
        opportunity_id="mpr2602-raw-vector",
        payer=PAYER,
        instructions=(
            PlannedInstruction(
                Instruction(Pubkey.default(), b"offline", []),
                role="application",
                name="offline-vector",
            ),
        ),
        required_signers=(PAYER,),
        quote_slot=19,
        market_state_slot=19,
        oracle_slot=19,
        monitored_accounts=(TOKEN,),
    )
    blockhash = BlockhashContext(
        blockhash=Hash.from_bytes(bytes(range(32))),
        last_valid_block_height=100,
        source_slot=20,
        fetched_at=0.0,
        commitment="confirmed",
    )
    return (
        await ExactSimulationFinalizer(rpc, policy=policy).finalize(plan, blockhash),
        rpc,
    )


def _decode(report, *, pre=None, slot=20):
    return build_pr115_proof_from_report(
        report,
        pre_state_accounts=pre if pre is not None else [_native(100_000), _token(100)],
        pre_state_slot=slot,
        policy=PR115DecodePolicy(
            expected_owner_by_address={
                str(PAYER): SYSTEM_PROGRAM_ID,
                str(TOKEN): SPL_TOKEN_PROGRAM_ID,
            }
        ),
    )


@pytest.mark.asyncio
async def test_actual_finalizer_report_decodes_final_native_and_token_states():
    finalized, rpc = await _finalize([_native(95_000), _token(175)])
    proof = _decode(finalized.report)
    assert proof.native_deltas[0].delta_lamports == -5000
    assert proof.token_deltas[0].delta_amount == 75
    assert proof.message_hash == finalized.compiled.message_hash
    assert proof.simulation_response_hash == finalized.report.final.response_hash
    assert proof.post_state_slot == 22
    assert proof.monitored_accounts == (str(PAYER), str(TOKEN))
    simulations = [
        params for method, params in rpc.calls if method == "simulateTransaction"
    ]
    assert len(simulations) == 2
    assert simulations[0][0] != simulations[1][0]
    assert all(params[1]["sigVerify"] is False for params in simulations)
    assert all(
        params[1]["accounts"]["addresses"] == [str(PAYER), str(TOKEN)]
        for params in simulations
    )


@pytest.mark.asyncio
async def test_final_evidence_does_not_alias_mutable_rpc_response():
    post = [_native(95_000), _token(175)]
    finalized, _ = await _finalize(post)
    before = _decode(finalized.report).to_dict()
    post[0]["lamports"] = 9_999_999
    post[1]["data"][0] = _token(9_999_999)["data"][0]
    post.reverse()
    assert _decode(finalized.report).to_dict() == before


@pytest.mark.asyncio
async def test_preserved_raw_evidence_is_deeply_immutable_to_consumers():
    finalized, _ = await _finalize([_native(95_000), _token(175)])
    accounts = finalized.report.final.returned_accounts
    with pytest.raises(TypeError):
        accounts[0]["lamports"] = 1
    with pytest.raises(TypeError):
        accounts[1]["data"][0] = ""
    assert _decode(finalized.report).token_deltas[0].delta_amount == 75


@pytest.mark.asyncio
async def test_ordered_account_owner_binding_rejects_swapped_rpc_states():
    finalized, _ = await _finalize([_token(175), _native(95_000)])
    with pytest.raises(PR115StateEvidenceError, match="wrong_owner"):
        _decode(finalized.report)


@pytest.mark.asyncio
async def test_null_returned_account_cannot_prove_success_without_lifecycle():
    finalized, _ = await _finalize([_native(95_000), None])
    with pytest.raises(PR115StateEvidenceError, match="missing_account"):
        _decode(finalized.report)


@pytest.mark.asyncio
@pytest.mark.parametrize("post", [None, [], [_native(95_000)]])
async def test_finalizer_rejects_absent_or_incomplete_target_account_collection(post):
    with pytest.raises(ExactSimulationError, match="targeted account snapshots"):
        await _finalize(copy.deepcopy(post))


@pytest.mark.asyncio
async def test_pre_state_cannot_come_from_after_final_simulation():
    finalized, _ = await _finalize([_native(95_000), _token(175)])
    with pytest.raises(PR115StateEvidenceError, match="context_slot_violation"):
        _decode(finalized.report, slot=23)


@pytest.mark.asyncio
async def test_raw_retention_cap_does_not_trust_rpc_loaded_bytes_claim():
    account = _token(175)
    account["data"][0] = "A" * 4096
    with pytest.raises(ExactSimulationError, match="raw account evidence byte limit"):
        await _finalize(
            [_native(95_000), account],
            policy=ExactSimulationPolicy(max_raw_account_evidence_bytes=2048),
        )


@pytest.mark.asyncio
async def test_retained_evidence_remains_serializable_and_hash_only_legacy_is_rejected():
    finalized, _ = await _finalize([_native(95_000), _token(175)])
    serialized = asdict(finalized.report)
    assert serialized["final"]["returned_account_json"]
    legacy_final = replace(finalized.report.final, returned_account_json=None)
    with pytest.raises(PR115StateEvidenceError, match="did not preserve raw accounts"):
        _decode(replace(finalized.report, final=legacy_final))


@pytest.mark.asyncio
async def test_nested_raw_account_metadata_retains_canonical_hash():
    post = [_native(95_000), _token(175)]
    post[0]["fixtureMetadata"] = {"observed": ["offline", {"capture": 1}]}
    finalized, _ = await _finalize(post)
    assert _decode(finalized.report).native_deltas[0].delta_lamports == -5000
    with pytest.raises(TypeError):
        finalized.report.final.returned_accounts[0]["fixtureMetadata"]["observed"][1][
            "capture"
        ] = 2


@pytest.mark.asyncio
@pytest.mark.parametrize("malformation", ["deep", "non_string_key", "non_object"])
async def test_malformed_retained_evidence_is_typed_rejection(malformation):
    account = _token(175)
    if malformation == "deep":
        nested: Any = "offline"
        for _ in range(40):
            nested = [nested]
        account["extra"] = nested
    elif malformation == "non_string_key":
        account[17] = "not JSON object keys"
    else:
        account = "not an account"
    with pytest.raises(ExactSimulationError, match="not canonical JSON"):
        await _finalize([_native(95_000), account])
