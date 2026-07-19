"""Opt-in, read-only RPC shape assertions for a real MarginFi account.

This is deliberately not labelled full protocol conformance. PR-027/PR-028 add
pinned deployment, IDL, binary layout, and instruction-level conformance.
"""

from __future__ import annotations

import base64
import os

import pytest
import requests
from solders.pubkey import Pubkey

pytestmark = pytest.mark.live


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.skip(f"set {name} to run the read-only MarginFi RPC assertion")
    return value


def test_marginfi_readonly_account_snapshot_has_real_rpc_shape() -> None:
    rpc_url = _required_env("MARGINFI_READONLY_RPC_URL")
    account = _required_env("MARGINFI_READONLY_ACCOUNT")
    expected_owner = os.getenv("MARGINFI_READONLY_EXPECTED_OWNER", "").strip()

    Pubkey.from_string(account)
    response = requests.post(
        rpc_url,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [
                account,
                {"encoding": "base64", "commitment": "confirmed"},
            ],
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()

    assert payload.get("jsonrpc") == "2.0"
    assert "error" not in payload
    result = payload.get("result")
    assert isinstance(result, dict)
    context = result.get("context")
    assert isinstance(context, dict)
    assert int(context.get("slot", 0)) > 0

    value = result.get("value")
    assert isinstance(value, dict), "configured account was not found"
    owner = value.get("owner")
    assert isinstance(owner, str) and owner
    Pubkey.from_string(owner)
    if expected_owner:
        Pubkey.from_string(expected_owner)
        assert owner == expected_owner

    encoded = value.get("data")
    assert isinstance(encoded, list) and len(encoded) >= 2
    assert encoded[1] == "base64"
    raw = base64.b64decode(encoded[0], validate=True)
    assert len(raw) >= 8
    assert raw[:8] != b"\x00" * 8
    assert value.get("executable") is False
    assert int(value.get("lamports", -1)) >= 0
