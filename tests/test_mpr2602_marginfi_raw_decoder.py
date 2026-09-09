"""Source-derived d4c70c84 vectors, explicitly not SDK/deployed observations.

Offsets are independently written from repr(C) user_account.rs and bank.rs;
tests do not call production layout encoders or inject economic observations.
"""

from __future__ import annotations

import base64
import copy
from dataclasses import replace
import hashlib
import json

import pytest
from solders.hash import Hash
from solders.instruction import Instruction
from solders.pubkey import Pubkey

from src.execution.exact_simulation import ExactSimulationFinalizer
from src.execution.models import BlockhashContext, PlannedInstruction, TransactionPlan
from src.execution.state_evidence_pr115 import (
    PR115DecodePolicy,
    PR115MarginfiDecodePolicy,
    PR115StateEvidenceError,
    SPL_TOKEN_PROGRAM_ID,
    SYSTEM_PROGRAM_ID,
    build_pr115_proof_from_report,
    build_pr115_simulation_owned_economic_proof,
)
from src.providers.marginfi.pin import load_marginfi_contract_pin

pytestmark = pytest.mark.unit
PAYER, MARGIN, BANK, GROUP, VAULT, MINT, ORACLE = [
    str(Pubkey.from_bytes(bytes([i]) * 32)) for i in range(1, 8)
]
PROGRAM = "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
ADDRESSES = (PAYER, MARGIN, BANK, GROUP, VAULT)


def _key(data, offset, address):
    data[offset : offset + 32] = bytes(Pubkey.from_string(address))


def _raw(data, owner=PROGRAM, lamports=2_039_280):
    return dict(
        owner=owner,
        executable=False,
        lamports=lamports,
        data=[base64.b64encode(data).decode(), "base64"],
        rentEpoch=0,
    )


def vectors():
    margin = bytearray(2312)
    margin[:8] = bytes.fromhex("43b2826d7e721c2a")
    _key(margin, 8, GROUP)
    _key(margin, 40, PAYER)
    bank = bytearray(1864)
    bank[:8] = bytes.fromhex("8e31a6f2324261bc")
    _key(bank, 8, MINT)
    bank[40] = 6
    _key(bank, 41, GROUP)
    for offset in (80, 96):
        bank[offset : offset + 16] = (1 << 48).to_bytes(16, "little", signed=True)
    _key(bank, 112, VAULT)
    bank[480:496] = (1 << 45).to_bytes(16, "little", signed=True)
    bank[608] = 1
    bank[609] = 3
    _key(bank, 610, ORACLE)
    group = bytearray(1064)
    group[:8] = bytes.fromhex("b617adf097ceb643")
    _key(group, 8, PAYER)
    vault = bytearray(165)
    _key(vault, 0, MINT)
    authority, _ = Pubkey.find_program_address(
        [b"liquidity_vault_auth", bytes(Pubkey.from_string(BANK))],
        Pubkey.from_string(PROGRAM),
    )
    vault[32:64] = bytes(authority)
    vault[64:72] = (1_000_000).to_bytes(8, "little")
    vault[108] = 1
    pre = [
        _raw(b"", SYSTEM_PROGRAM_ID, 100_000),
        _raw(margin),
        _raw(bank),
        _raw(group),
        _raw(vault, SPL_TOKEN_PROGRAM_ID),
    ]
    vault[64:72] = (1_000_125).to_bytes(8, "little")
    post = copy.deepcopy(pre)
    post[0]["lamports"] = 95_000
    post[4] = _raw(vault, SPL_TOKEN_PROGRAM_ID)
    pin = load_marginfi_contract_pin()
    layout_hash = hashlib.sha256(
        json.dumps(pin.raw, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    context = PR115MarginfiDecodePolicy(
        pin.source_commit, layout_hash, MARGIN, GROUP, PAYER, BANK, VAULT, 1000
    )
    return pre, post, context


def decode(pre, post, context):
    return build_pr115_simulation_owned_economic_proof(
        monitored_accounts=ADDRESSES,
        pre_state_accounts=pre,
        post_state_accounts=post,
        pre_state_slot=20,
        post_state_slot=22,
        min_context_slot=19,
        message_hash="a" * 64,
        simulation_response_hash="b" * 64,
        policy=PR115DecodePolicy(marginfi=context),
    )


def mutate_data(accounts, index, offset, value):
    data = bytearray(base64.b64decode(accounts[index]["data"][0]))
    data[offset : offset + len(value)] = value
    accounts[index]["data"][0] = base64.b64encode(data).decode()


def test_source_vector_decodes_margin_and_vault_invariants_and_owner_keys():
    pre, post, context = vectors()
    proof = decode(pre, post, context)
    repayment = proof.marginfi_repayment
    assert repayment is not None
    assert repayment.principal == 1000
    assert repayment.conservative_fee_amount == 125
    assert repayment.post_target_liability_shares == 0
    assert repayment.post_vault_amount - repayment.pre_vault_amount == 125
    assert proof.native_deltas[0].delta_lamports == -5000
    assert proof.token_deltas[0].mint == MINT
    assert proof.token_deltas[0].authority != PAYER  # lender vault is not wallet profit
    assert (
        proof.to_dict()["marginfi_repayment"]["source_commit"] == context.source_commit
    )


@pytest.mark.asyncio
async def test_actual_finalizer_to_marginfi_decoder_without_report_patching():
    pre, post, context = vectors()

    class Rpc:
        count = 0

        async def call(self, method, params):
            if method == "getBlockHeight":
                return 50
            if method == "isBlockhashValid":
                return {"context": {"slot": 20}, "value": True}
            if method == "getFeeForMessage":
                return {"context": {"slot": 22}, "value": 5000}
            assert method == "simulateTransaction"
            assert params[1]["accounts"]["addresses"] == list(ADDRESSES)
            self.count += 1
            return {
                "context": {"slot": 20 + self.count},
                "value": {
                    "err": None,
                    "logs": [],
                    "unitsConsumed": 100_000,
                    "accounts": post,
                    "loadedAccountsDataSize": 5405,
                },
            }

    payer = Pubkey.from_string(PAYER)
    plan = TransactionPlan(
        opportunity_id="source-state-vector",
        payer=payer,
        instructions=(
            PlannedInstruction(
                Instruction(Pubkey.default(), b"offline", []),
                role="application",
                name="state-vector",
            ),
        ),
        required_signers=(payer,),
        quote_slot=19,
        market_state_slot=19,
        oracle_slot=19,
        monitored_accounts=tuple(
            Pubkey.from_string(address) for address in ADDRESSES[1:]
        ),
    )
    blockhash = BlockhashContext(
        Hash.from_bytes(bytes(range(32))), 100, 20, 0.0, "confirmed"
    )
    finalized = await ExactSimulationFinalizer(Rpc()).finalize(plan, blockhash)
    proof = build_pr115_proof_from_report(
        finalized.report,
        pre_state_accounts=pre,
        pre_state_slot=20,
        policy=PR115DecodePolicy(marginfi=context),
    )
    assert proof.message_hash == finalized.compiled.message_hash
    assert proof.marginfi_repayment.post_vault_amount == 1_000_125


@pytest.mark.parametrize(
    "mutation",
    [
        "source",
        "layout",
        "margin_owner",
        "discriminator",
        "group",
        "authority",
        "bank_group",
        "bank_vault",
        "vault_owner",
        "vault_mint",
        "vault_authority",
        "retained_flashloan_flag",
        "liability",
        "negative_shares",
        "inactive_liability",
        "preexisting_target",
        "unrelated_position",
        "share_value",
        "missing",
        "fee_shortfall",
        "vault_delegate",
        "protocol_rent",
    ],
)
def test_malformed_or_unrepaid_raw_state_is_rejected(mutation):
    pre, post, context = vectors()
    if mutation == "source":
        context = replace(context, source_commit="0" * 40)
    elif mutation == "layout":
        context = replace(context, layout_sha256="0" * 64)
    elif mutation == "margin_owner":
        post[1]["owner"] = SYSTEM_PROGRAM_ID
    elif mutation == "discriminator":
        mutate_data(post, 1, 0, b"BADBYTES")
    elif mutation == "group":
        mutate_data(post, 1, 8, bytes(32))
    elif mutation == "authority":
        mutate_data(post, 1, 40, bytes(32))
    elif mutation == "bank_group":
        mutate_data(post, 2, 41, bytes(32))
    elif mutation == "bank_vault":
        mutate_data(post, 2, 112, bytes(32))
    elif mutation == "vault_owner":
        post[4]["owner"] = PROGRAM
    elif mutation == "vault_mint":
        mutate_data(post, 4, 0, bytes(32))
    elif mutation == "vault_authority":
        mutate_data(post, 4, 32, bytes(32))
    elif mutation == "retained_flashloan_flag":
        mutate_data(post, 1, 1800, bytes([2]))
    elif mutation in (
        "liability",
        "negative_shares",
        "inactive_liability",
        "preexisting_target",
        "unrelated_position",
    ):
        states = pre if mutation == "preexisting_target" else post
        mutate_data(
            states, 1, 72, bytes([0 if mutation == "inactive_liability" else 1])
        )
        key = ORACLE if mutation == "unrelated_position" else BANK
        mutate_data(states, 1, 73, bytes(Pubkey.from_string(key)))
        amount = -1 if mutation == "negative_shares" else 1
        mutate_data(states, 1, 128, amount.to_bytes(16, "little", signed=True))
    elif mutation == "share_value":
        mutate_data(post, 2, 80, bytes(16))
    elif mutation == "missing":
        post[1] = None
    elif mutation == "fee_shortfall":
        mutate_data(post, 4, 64, (1_000_124).to_bytes(8, "little"))
    elif mutation == "vault_delegate":
        mutate_data(post, 4, 72, bytes([1]))
    elif mutation == "protocol_rent":
        post[1]["lamports"] += 1
    with pytest.raises(PR115StateEvidenceError):
        decode(pre, post, context)


def test_boolean_allow_marginfi_does_not_supply_protocol_authority():
    pre, post, _ = vectors()
    with pytest.raises(PR115StateEvidenceError, match="unsupported_account_owner"):
        build_pr115_simulation_owned_economic_proof(
            monitored_accounts=ADDRESSES,
            pre_state_accounts=pre,
            post_state_accounts=post,
            pre_state_slot=20,
            post_state_slot=22,
            min_context_slot=19,
            message_hash="a" * 64,
            simulation_response_hash="b" * 64,
            policy=PR115DecodePolicy(allow_marginfi_accounts=True),
        )


def test_fee_rounding_uses_integer_ceiling():
    pre, post, context = vectors()
    for states in (pre, post):
        mutate_data(states, 2, 480, (1).to_bytes(16, "little", signed=True))
    mutate_data(post, 4, 64, (1_000_001).to_bytes(8, "little"))
    assert decode(pre, post, context).marginfi_repayment.conservative_fee_amount == 1
    mutate_data(post, 4, 64, (1_000_000).to_bytes(8, "little"))
    with pytest.raises(PR115StateEvidenceError, match="vault_fee_not_returned"):
        decode(pre, post, context)
