from __future__ import annotations

import base64
from typing import Any

import pytest

from src.execution.state_evidence_pr115 import (
    PR115StateEvidenceError,
    SPL_TOKEN_PROGRAM_ID,
    SYSTEM_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    build_pr115_simulation_owned_economic_proof,
)

pytestmark = pytest.mark.unit

MESSAGE_HASH = "a" * 64
SIM_RESPONSE_HASH = "b" * 64
ADDRESS = "11111111111111111111111111111112"


def _account(
    *,
    lamports: int,
    owner: str = SYSTEM_PROGRAM_ID,
    data: bytes = b"",
    executable: bool = False,
) -> dict[str, Any]:
    return {
        "lamports": lamports,
        "owner": owner,
        "executable": executable,
        "data": [base64.b64encode(data).decode("ascii"), "base64"],
        "rentEpoch": 0,
    }


def _token_account(amount: int) -> bytes:
    data = bytearray(165)
    data[0:32] = bytes([1]) * 32
    data[32:64] = bytes([2]) * 32
    data[64:72] = amount.to_bytes(8, "little")
    return bytes(data)


def test_pr115_derives_native_delta_from_raw_accounts_only() -> None:
    proof = build_pr115_simulation_owned_economic_proof(
        monitored_accounts=(ADDRESS,),
        pre_state_accounts=(_account(lamports=10_000),),
        post_state_accounts=(_account(lamports=12_500),),
        message_hash=MESSAGE_HASH,
        simulation_response_hash=SIM_RESPONSE_HASH,
        pre_state_slot=40,
        post_state_slot=41,
        min_context_slot=39,
        pre_root_slot=40,
        post_root_slot=41,
    )

    assert proof.message_hash == MESSAGE_HASH
    assert proof.native_deltas[0].delta_lamports == 2_500
    assert proof.native_deltas[0].pre_lamports == 10_000
    assert proof.native_deltas[0].post_lamports == 12_500
    assert len(proof.pre_state_hash) == 64
    assert len(proof.post_state_hash) == 64
    assert len(proof.raw_evidence_hash) == 64
    assert proof.to_dict()["native_deltas"][0]["delta_lamports"] == 2_500


def test_pr115_decodes_legacy_spl_token_amounts_from_raw_bytes() -> None:
    proof = build_pr115_simulation_owned_economic_proof(
        monitored_accounts=(ADDRESS,),
        pre_state_accounts=(
            _account(
                lamports=2_039_280,
                owner=SPL_TOKEN_PROGRAM_ID,
                data=_token_account(100),
            ),
        ),
        post_state_accounts=(
            _account(
                lamports=2_039_280,
                owner=SPL_TOKEN_PROGRAM_ID,
                data=_token_account(175),
            ),
        ),
        message_hash=MESSAGE_HASH,
        simulation_response_hash=SIM_RESPONSE_HASH,
        pre_state_slot=50,
        post_state_slot=50,
        min_context_slot=49,
    )

    assert proof.native_deltas == ()
    assert proof.token_deltas[0].delta_amount == 75
    assert len(proof.token_deltas[0].mint_hash) == 64


def test_pr115_copied_hashes_do_not_authorize_different_raw_accounts() -> None:
    with pytest.raises(PR115StateEvidenceError, match="copied_hash_mismatch"):
        build_pr115_simulation_owned_economic_proof(
            monitored_accounts=(ADDRESS,),
            pre_state_accounts=(_account(lamports=1),),
            post_state_accounts=(_account(lamports=2),),
            message_hash=MESSAGE_HASH,
            simulation_response_hash=SIM_RESPONSE_HASH,
            pre_state_slot=10,
            post_state_slot=11,
            min_context_slot=9,
            expected_post_account_hashes=("0" * 64,),
        )


@pytest.mark.parametrize(
    ("pre_accounts", "post_accounts", "message"),
    (
        ((None,), (_account(lamports=1),), "missing_account"),
        (
            (_account(lamports=1),),
            (_account(lamports=2), _account(lamports=3)),
            "unrequested_account",
        ),
        (
            (_account(lamports=1, owner=TOKEN_2022_PROGRAM_ID),),
            (_account(lamports=2, owner=TOKEN_2022_PROGRAM_ID),),
            "unsupported_token_2022",
        ),
        (
            (_account(lamports=1),),
            (_account(lamports=2, executable=True),),
            "unexpected_executable",
        ),
    ),
)
def test_pr115_rejects_unproven_raw_account_shapes(
    pre_accounts: tuple[dict[str, Any] | None, ...],
    post_accounts: tuple[dict[str, Any] | None, ...],
    message: str,
) -> None:
    with pytest.raises(PR115StateEvidenceError, match=message):
        build_pr115_simulation_owned_economic_proof(
            monitored_accounts=(ADDRESS,),
            pre_state_accounts=pre_accounts,
            post_state_accounts=post_accounts,
            message_hash=MESSAGE_HASH,
            simulation_response_hash=SIM_RESPONSE_HASH,
            pre_state_slot=10,
            post_state_slot=11,
            min_context_slot=9,
        )


def test_pr115_rejects_duplicate_accounts_and_stale_slots() -> None:
    with pytest.raises(PR115StateEvidenceError, match="duplicate_address"):
        build_pr115_simulation_owned_economic_proof(
            monitored_accounts=(ADDRESS, ADDRESS),
            pre_state_accounts=(_account(lamports=1), _account(lamports=1)),
            post_state_accounts=(_account(lamports=2), _account(lamports=2)),
            message_hash=MESSAGE_HASH,
            simulation_response_hash=SIM_RESPONSE_HASH,
            pre_state_slot=10,
            post_state_slot=11,
            min_context_slot=9,
        )

    with pytest.raises(PR115StateEvidenceError, match="context_slot_violation"):
        build_pr115_simulation_owned_economic_proof(
            monitored_accounts=(ADDRESS,),
            pre_state_accounts=(_account(lamports=1),),
            post_state_accounts=(_account(lamports=2),),
            message_hash=MESSAGE_HASH,
            simulation_response_hash=SIM_RESPONSE_HASH,
            pre_state_slot=8,
            post_state_slot=11,
            min_context_slot=9,
        )
