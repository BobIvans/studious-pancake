from __future__ import annotations

import base64

import pytest

from src.planning.instruction_firewall import (
    InstructionFirewallError,
    InstructionFirewallPolicy,
    InstructionFirewallReason,
    InstructionRole,
    SPL_TOKEN_PROGRAM_ID,
    SYSTEM_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    validate_raw_provider_instruction,
)
from src.providers.jupiter.router import JupiterRawInstruction, RawAccountMeta

PAYER = "So11111111111111111111111111111111111111112"
POOL = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
ATTACKER = "Es9vMFrzaCERmJfrF4H2FYD4KCoFfheKkg7gVcEzxYcb"
JUPITER_PROGRAM = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"


def _meta(
    pubkey: str,
    *,
    signer: bool = False,
    writable: bool = False,
) -> RawAccountMeta:
    return RawAccountMeta(
        pubkey=pubkey,
        is_signer=signer,
        is_writable=writable,
    )


def _raw(
    program_id: str,
    data: bytes,
    name: str,
    *,
    accounts: tuple[RawAccountMeta, ...] | None = None,
) -> JupiterRawInstruction:
    return JupiterRawInstruction(
        program_id=program_id,
        accounts=accounts
        or (
            _meta(PAYER, signer=True),
            _meta(POOL, writable=True),
        ),
        data_b64=base64.b64encode(data).decode("ascii"),
        name=name,
    )


def _policy() -> InstructionFirewallPolicy:
    return InstructionFirewallPolicy(
        payer=PAYER,
        jupiter_program_ids=(JUPITER_PROGRAM,),
    )


def test_pr114_program_allowlist_alone_cannot_admit_token_set_authority() -> None:
    instruction = _raw(SPL_TOKEN_PROGRAM_ID, bytes([6]), "set_authority")

    with pytest.raises(InstructionFirewallError) as caught:
        validate_raw_provider_instruction(
            instruction,
            _policy(),
            role=InstructionRole.SETUP,
        )

    assert caught.value.reason in {
        InstructionFirewallReason.DANGEROUS_TEXT_MARKER,
        InstructionFirewallReason.DANGEROUS_TOKEN_INSTRUCTION,
    }


def test_pr114_rejects_system_transfer_from_provider_payload() -> None:
    transfer_tag = (2).to_bytes(4, "little")
    lamports = (1_000_000).to_bytes(8, "little")
    instruction = _raw(
        SYSTEM_PROGRAM_ID,
        transfer_tag + lamports,
        "system_move_lamports",
        accounts=(
            _meta(PAYER, signer=True),
            _meta(ATTACKER, writable=True),
        ),
    )

    with pytest.raises(InstructionFirewallError) as caught:
        validate_raw_provider_instruction(
            instruction,
            _policy(),
            role=InstructionRole.CLEANUP,
        )

    assert caught.value.reason is InstructionFirewallReason.SYSTEM_TRANSFER_FORBIDDEN


def test_pr114_rejects_writable_payer_account_in_pinned_program() -> None:
    instruction = _raw(
        JUPITER_PROGRAM,
        b"opaque-route",
        "opaque_swap",
        accounts=(
            _meta(PAYER, signer=True, writable=True),
            _meta(POOL, writable=True),
        ),
    )

    with pytest.raises(InstructionFirewallError) as caught:
        validate_raw_provider_instruction(
            instruction,
            _policy(),
            role=InstructionRole.SWAP,
        )

    assert caught.value.reason is InstructionFirewallReason.WRITABLE_PAYER_FORBIDDEN


def test_pr114_token_2022_fails_closed_until_extension_policy_exists() -> None:
    instruction = _raw(TOKEN_2022_PROGRAM_ID, bytes([12]), "transfer_checked")

    with pytest.raises(InstructionFirewallError) as caught:
        validate_raw_provider_instruction(
            instruction,
            _policy(),
            role=InstructionRole.SWAP,
        )

    assert caught.value.reason is InstructionFirewallReason.TOKEN_2022_UNSUPPORTED


def test_pr114_accepts_pinned_jupiter_swap_without_wallet_mutation() -> None:
    finding = validate_raw_provider_instruction(
        _raw(JUPITER_PROGRAM, b"swap-route", "jupiter_swap"),
        _policy(),
        role=InstructionRole.SWAP,
    )

    assert finding.semantic_class == "jupiter-pinned-program"
    assert finding.role is InstructionRole.SWAP
