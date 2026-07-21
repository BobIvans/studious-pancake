from __future__ import annotations

import base64
from dataclasses import replace

import pytest
from solders.pubkey import Pubkey

from src.planning.instruction_firewall import (
    InstructionFirewallError,
    InstructionFirewallPolicy,
    InstructionFirewallReason,
    InstructionRole,
    SPL_TOKEN_PROGRAM_ID,
    SYSTEM_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    validate_jupiter_instruction_bundle,
    validate_raw_provider_instruction,
)
from src.providers.jupiter.router import (
    JupiterInstructionBundle,
    JupiterRawInstruction,
    RawAccountMeta,
)


def _pk(seed: int) -> Pubkey:
    return Pubkey.from_bytes(bytes([seed]) * 32)


PAYER = _pk(1)
POOL = _pk(2)
ATTACKER = _pk(3)
JUPITER_PROGRAM = _pk(4)
ALT = _pk(5)
ALT_MEMBER = _pk(6)


def _meta(
    pubkey: Pubkey,
    *,
    signer: bool = False,
    writable: bool = False,
) -> RawAccountMeta:
    return RawAccountMeta(
        pubkey=str(pubkey),
        is_signer=signer,
        is_writable=writable,
    )


def _raw(
    program_id: str | Pubkey,
    data: bytes,
    name: str,
    *,
    accounts: tuple[RawAccountMeta, ...] | None = None,
) -> JupiterRawInstruction:
    return JupiterRawInstruction(
        program_id=str(program_id),
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
        payer=str(PAYER),
        jupiter_program_ids=(str(JUPITER_PROGRAM),),
    )


def _bundle(*, cleanup: JupiterRawInstruction | None = None) -> JupiterInstructionBundle:
    return JupiterInstructionBundle(
        input_mint=str(_pk(10)),
        output_mint=str(_pk(11)),
        in_amount=1_000,
        out_amount=1_010,
        other_amount_threshold=1_000,
        swap_mode="ExactIn",
        slippage_bps=50,
        route_plan=({"label": "firewalled"},),
        compute_unit_price_instructions=(),
        setup_instructions=(),
        swap_instruction=_raw(JUPITER_PROGRAM, b"swap-route", "jupiter_swap"),
        cleanup_instruction=cleanup,
        other_instructions=(),
        tip_instruction=None,
        addresses_by_lookup_table_address={str(ALT): (str(ALT_MEMBER),)},
        blockhash_with_metadata={"blockhash": str(_pk(12))},
        received_at=1_750_000_000.0,
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


def test_pr114_rejects_writable_payer_account_in_opaque_program() -> None:
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


def test_pr114_bundle_firewall_rejects_malicious_cleanup() -> None:
    bundle = _bundle(
        cleanup=_raw(SPL_TOKEN_PROGRAM_ID, bytes([9]), "close_account")
    )

    with pytest.raises(InstructionFirewallError) as caught:
        validate_jupiter_instruction_bundle(bundle, _policy())

    assert caught.value.reason in {
        InstructionFirewallReason.DANGEROUS_TEXT_MARKER,
        InstructionFirewallReason.DANGEROUS_TOKEN_INSTRUCTION,
    }


def test_pr114_bundle_rejects_provider_tip_even_before_program_allowlist() -> None:
    bundle = replace(
        _bundle(),
        tip_instruction=_raw(JUPITER_PROGRAM, b"tip", "provider_tip"),
    )

    with pytest.raises(InstructionFirewallError) as caught:
        validate_jupiter_instruction_bundle(bundle, _policy())

    assert caught.value.reason is InstructionFirewallReason.PROVIDER_COMPUTE_OR_TIP
