from __future__ import annotations

import struct

import pytest
from solders.instruction import Instruction
from solders.pubkey import Pubkey

from src.providers.marginfi import (
    MarginfiAccountReader,
    MarginfiFlashLoanProvider,
    MarginfiRejection,
    MarginfiRejectionCode,
    RpcAccount,
    load_marginfi_contract_pin,
)
from src.providers.marginfi.layouts import ceil_i80f48_product

PROGRAM = "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
GROUP = "4qp6Fx6tnZkY5Wropq9wUYgtFxXKwE6viZxFHg3rdAG8"
MARGIN_ACCOUNT = "Fk4G5NB5e1NyULQCCpTNLWCmChCW2UbDwpkEofqAiHk2"
AUTHORITY = "11111111111111111111111111111111"
BANK = "HmpMfL8942fYJdwdVdzi7okQCXh6gwX1v6hN1Eks7gbC"
VAULT = "7hQfMh9N7Xmkuzw3jHMqUiEAn1ng4Vr4QtgEwrz5QZc"
ORACLE = "SysvarC1ock11111111111111111111111111111111"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
DESTINATION = "7UX3bG2AvfbbWAC4Wqd9m6mUXtwewfP7btrnvcNSG2h"
REPAYMENT = "9zHgUoJgGrKh4ZwVgtxYzBYzvD9Jq3qQnF2Y5xp9bzpS"
LOADER = "BPFLoaderUpgradeab1e11111111111111111111111"


def _write_pubkey(body: bytearray, offset: int, value: str) -> None:
    body[offset : offset + 32] = bytes(Pubkey.from_string(value))


def _account_data(pin, name: str, body: bytearray) -> bytes:
    assert len(body) == pin.account_size(name)
    return pin.account_discriminator(name) + bytes(body)


def _group_data(pin, *, paused: bool = False) -> bytes:
    body = bytearray(pin.account_size("marginfi_group"))
    _write_pubkey(body, 0, AUTHORITY)
    if paused:
        body[248] = 1
        struct.pack_into("<q", body, 256, 1_699_999_000)
        struct.pack_into("<q", body, 264, 1_699_999_100)
    return _account_data(pin, "marginfi_group", body)


def _margin_account_data(pin, *, active_bank: str | None = None) -> bytes:
    body = bytearray(pin.account_size("marginfi_account"))
    _write_pubkey(body, 0, GROUP)
    _write_pubkey(body, 32, AUTHORITY)
    if active_bank is not None:
        body[64] = 1
        _write_pubkey(body, 65, active_bank)
    return _account_data(pin, "marginfi_account", body)


def _bank_data(pin, *, fee_raw: int = 1 << 45, state: int = 1) -> bytes:
    body = bytearray(pin.account_size("bank"))
    _write_pubkey(body, 0, USDC)
    body[32] = 6
    _write_pubkey(body, 33, GROUP)
    _write_pubkey(body, 104, VAULT)
    body[472:488] = int(fee_raw).to_bytes(16, "little", signed=True)
    body[600] = state
    body[601] = 3
    _write_pubkey(body, 602, ORACLE)
    struct.pack_into("<Q", body, 768, 10_000_000)
    body[777] = 0
    struct.pack_into("<Q", body, 832, 0)
    return _account_data(pin, "bank", body)


def _vault_data(*, amount: int = 2_000_000) -> bytes:
    body = bytearray(165)
    _write_pubkey(body, 0, USDC)
    vault_authority = Pubkey.find_program_address(
        [b"liquidity_vault_auth", bytes(Pubkey.from_string(BANK))],
        Pubkey.from_string(PROGRAM),
    )[0]
    body[32:64] = bytes(vault_authority)
    struct.pack_into("<Q", body, 64, amount)
    return bytes(body)


class Rpc:
    def __init__(
        self,
        pin,
        *,
        paused: bool = False,
        active_bank: str | None = None,
        bank_state: int = 1,
        fee_raw: int = 1 << 45,
        vault_amount: int = 2_000_000,
        followup_slot: int = 124,
    ):
        self.first_slot = 123
        self.followup_slot = followup_slot
        self.map = {
            PROGRAM: RpcAccount(
                PROGRAM,
                LOADER,
                b"",
                executable=True,
            ),
            GROUP: RpcAccount(
                GROUP,
                PROGRAM,
                _group_data(pin, paused=paused),
            ),
            MARGIN_ACCOUNT: RpcAccount(
                MARGIN_ACCOUNT,
                PROGRAM,
                _margin_account_data(pin, active_bank=active_bank),
            ),
            BANK: RpcAccount(
                BANK,
                PROGRAM,
                _bank_data(pin, fee_raw=fee_raw, state=bank_state),
            ),
            VAULT: RpcAccount(VAULT, TOKEN, _vault_data(amount=vault_amount)),
        }

    def get_multiple_accounts(self, addresses, *, min_context_slot=None):
        if min_context_slot is None:
            return self.first_slot, tuple(self.map.get(value) for value in addresses)
        assert min_context_slot == self.first_slot
        return self.followup_slot, tuple(self.map.get(value) for value in addresses)


def _snapshot(pin, **rpc_kwargs):
    return MarginfiAccountReader(
        pin,
        Rpc(pin, **rpc_kwargs),
        clock=lambda: 1_700_000_000,
    ).read(
        group=GROUP,
        margin_account=MARGIN_ACCOUNT,
        authority=AUTHORITY,
        bank=BANK,
        symbol="USDC",
        amount=1_000,
    )


def test_pinned_discriminators_match_upstream_source() -> None:
    pin = load_marginfi_contract_pin()
    assert pin.account_discriminator("marginfi_group").hex() == "b617adf097ceb643"
    assert pin.account_discriminator("marginfi_account").hex() == "43b2826d7e721c2a"
    assert pin.account_discriminator("bank").hex() == "8e31a6f2324261bc"
    assert pin.account_size("marginfi_group") == 1056
    assert pin.account_size("marginfi_account") == 2304
    assert pin.account_size("bank") == 1856


def test_reader_decodes_binary_accounts_and_vault_liquidity() -> None:
    pin = load_marginfi_contract_pin()
    snapshot = _snapshot(pin)
    assert snapshot.slot == 124
    assert snapshot.group == GROUP
    assert snapshot.margin_account.active_balances == (BANK,)
    assert snapshot.margin_account.target_bank_was_active is False
    assert snapshot.bank.mint == USDC
    assert snapshot.bank.mint_decimals == 6
    assert snapshot.bank.token_program == TOKEN
    assert snapshot.bank.available_liquidity == 2_000_000
    assert snapshot.bank.origination_fee_raw_i80f48 == 1 << 45
    assert snapshot.bank.oracle_keys == (ORACLE,)
    assert snapshot.state_fingerprint


def test_provider_builds_current_account_metas_and_option_bool_repay() -> None:
    pin = load_marginfi_contract_pin()
    provider = MarginfiFlashLoanProvider(pin)
    prepared = provider.prepare(
        snapshot=_snapshot(pin),
        amount=1_000,
        destination_token_account=DESTINATION,
        repayment_source_token_account=REPAYMENT,
        min_final_balance=1_135,
        safety_surplus=10,
    )
    assert prepared.origination_fee == 125
    assert prepared.required_repayment == 1_125
    assert prepared.risk_accounts == (BANK, ORACLE)

    borrow = prepared.borrow_instruction
    assert [str(meta.pubkey) for meta in borrow.accounts[:8]] == [
        GROUP,
        MARGIN_ACCOUNT,
        AUTHORITY,
        BANK,
        DESTINATION,
        str(
            Pubkey.find_program_address(
                [b"liquidity_vault_auth", bytes(Pubkey.from_string(BANK))],
                Pubkey.from_string(PROGRAM),
            )[0]
        ),
        VAULT,
        TOKEN,
    ]
    assert [str(meta.pubkey) for meta in borrow.accounts[8:]] == [BANK, ORACLE]
    assert bytes(borrow.data).hex() == "047e74353005d41fe803000000000000"

    repay = prepared.repay_instruction
    assert [str(meta.pubkey) for meta in repay.accounts] == [
        GROUP,
        MARGIN_ACCOUNT,
        AUTHORITY,
        BANK,
        REPAYMENT,
        VAULT,
        TOKEN,
    ]
    assert bytes(repay.data).hex() == "4fd1acb1de33ad9765040000000000000101"

    final = provider.finalize(
        prepared,
        [
            borrow,
            Instruction(Pubkey.default(), b"swap-a", []),
            Instruction(Pubkey.default(), b"swap-b", []),
            repay,
        ],
    )
    start = final.instructions[0]
    assert [str(meta.pubkey) for meta in start.accounts] == [
        MARGIN_ACCOUNT,
        AUTHORITY,
        "Sysvar1nstructions1111111111111111111111111",
    ]
    assert bytes(start.data).hex() == "0e8321dc51bab46b0500000000000000"
    assert final.start_index == 0
    assert final.end_index == 5
    assert final.instructions[final.end_index] == prepared.end_template


def test_reader_rejects_pause_non_operational_bank_stale_slot_and_low_liquidity() -> (
    None
):
    pin = load_marginfi_contract_pin()
    cases = [
        ({"paused": True}, MarginfiRejectionCode.PROTOCOL_PAUSED),
        ({"bank_state": 0}, MarginfiRejectionCode.BANK_DISABLED),
        ({"followup_slot": 122}, MarginfiRejectionCode.SLOT_INCONSISTENT),
        ({"vault_amount": 999}, MarginfiRejectionCode.INSUFFICIENT_LIQUIDITY),
    ]
    for kwargs, expected in cases:
        with pytest.raises(MarginfiRejection) as error:
            _snapshot(pin, **kwargs)
        assert error.value.code == expected


def test_old_synthetic_discriminator_and_json_fixture_fail_closed() -> None:
    pin = load_marginfi_contract_pin()
    rpc = Rpc(pin)
    old_json_fixture = bytes.fromhex("43b774c54f1500e6") + b'{"group":"fake"}'
    rpc.map[MARGIN_ACCOUNT] = RpcAccount(
        MARGIN_ACCOUNT,
        PROGRAM,
        old_json_fixture,
    )
    with pytest.raises(MarginfiRejection) as error:
        MarginfiAccountReader(
            pin,
            rpc,
            clock=lambda: 1_700_000_000,
        ).read(
            group=GROUP,
            margin_account=MARGIN_ACCOUNT,
            authority=AUTHORITY,
            bank=BANK,
            symbol="USDC",
            amount=1_000,
        )
    assert error.value.code in {
        MarginfiRejectionCode.DATA_LENGTH_MISMATCH,
        MarginfiRejectionCode.DISCRIMINATOR_MISMATCH,
    }


def test_existing_target_position_is_not_modified_by_repay_all() -> None:
    pin = load_marginfi_contract_pin()
    provider = MarginfiFlashLoanProvider(pin)
    with pytest.raises(MarginfiRejection) as error:
        provider.prepare(
            snapshot=_snapshot(pin, active_bank=BANK),
            amount=1_000,
            destination_token_account=DESTINATION,
            repayment_source_token_account=REPAYMENT,
            min_final_balance=2_000,
        )
    assert error.value.code == MarginfiRejectionCode.EXISTING_POSITION


def test_fee_rounding_is_integer_and_conservative() -> None:
    assert ceil_i80f48_product(1_000, 1 << 45) == 125
    assert ceil_i80f48_product(1, 1) == 1
    with pytest.raises(MarginfiRejection):
        ceil_i80f48_product(1, -1)
