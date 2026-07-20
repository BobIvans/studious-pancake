"""Opt-in, read-only mainnet conformance for the PR-028 MarginFi decoder.

Required environment variables identify a real group, margin account, authority,
and target bank. The test performs no signing and sends no transaction.
"""

from __future__ import annotations

import base64
import os

import pytest
import requests
from solders.pubkey import Pubkey

from src.providers.marginfi import (
    MarginfiAccountReader,
    RpcAccount,
    load_marginfi_contract_pin,
)


pytestmark = pytest.mark.live


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.skip(f"set {name} to run read-only MarginFi conformance")
    return value


class RequestsReadonlyRpc:
    def __init__(self, url: str):
        self.url = url

    def get_multiple_accounts(self, addresses, *, min_context_slot=None):
        config = {"encoding": "base64", "commitment": "confirmed"}
        if min_context_slot is not None:
            config["minContextSlot"] = int(min_context_slot)
        response = requests.post(
            self.url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getMultipleAccounts",
                "params": [list(addresses), config],
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        assert payload.get("jsonrpc") == "2.0"
        assert "error" not in payload, payload.get("error")
        result = payload.get("result")
        assert isinstance(result, dict)
        context = result.get("context")
        assert isinstance(context, dict)
        slot = int(context.get("slot", 0))
        assert slot > 0
        values = result.get("value")
        assert isinstance(values, list)
        assert len(values) == len(addresses)
        accounts = []
        for address, value in zip(addresses, values, strict=True):
            if value is None:
                accounts.append(None)
                continue
            encoded = value.get("data")
            assert isinstance(encoded, list) and len(encoded) >= 2
            assert encoded[1] == "base64"
            raw = base64.b64decode(encoded[0], validate=True)
            accounts.append(
                RpcAccount(
                    address=str(address),
                    owner=str(value["owner"]),
                    data=raw,
                    lamports=int(value["lamports"]),
                    executable=bool(value["executable"]),
                )
            )
        return slot, tuple(accounts)


def test_marginfi_mainnet_binary_and_relationship_conformance() -> None:
    rpc_url = _required_env("MARGINFI_READONLY_RPC_URL")
    group = _required_env("MARGINFI_READONLY_GROUP")
    margin_account = _required_env("MARGINFI_READONLY_MARGIN_ACCOUNT")
    authority = _required_env("MARGINFI_READONLY_AUTHORITY")
    bank = _required_env("MARGINFI_READONLY_BANK")
    symbol = os.getenv("MARGINFI_READONLY_SYMBOL", "USDC").strip().upper()
    amount = int(os.getenv("MARGINFI_READONLY_AMOUNT", "1"))

    for value in (group, margin_account, authority, bank):
        Pubkey.from_string(value)

    pin = load_marginfi_contract_pin()
    assert pin.source_commit == "d4c70c84f8a9692405a2c32cbd7095bb1fe3f428"
    assert pin.program_id == "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"

    snapshot = MarginfiAccountReader(
        pin,
        RequestsReadonlyRpc(rpc_url),
    ).read(
        group=group,
        margin_account=margin_account,
        authority=authority,
        bank=bank,
        symbol=symbol,
        amount=amount,
    )

    assert snapshot.slot > 0
    assert snapshot.group == group
    assert snapshot.margin_account.group == group
    assert snapshot.margin_account.authority == authority
    assert snapshot.bank.address == bank
    assert snapshot.bank.group == group
    assert snapshot.bank.operational_state == "operational"
    assert snapshot.bank.available_liquidity is not None
    assert snapshot.bank.available_liquidity >= amount
    assert snapshot.bank.oracle_keys
    assert snapshot.bank.origination_fee_raw_i80f48 >= 0
    assert snapshot.state_fingerprint
