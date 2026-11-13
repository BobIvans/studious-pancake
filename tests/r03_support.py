"""Shared offline fixtures/support for R03 unsigned-builder tests.

Everything here is synthetic and offline: no network, no signing, no real
accounts.  Public protocol constants (program ids, PDAs) come from the pinned
sources.
"""

from __future__ import annotations

from pathlib import Path

from solders.pubkey import Pubkey

from src.lending.jupiter_lend import JupiterLendFlashloanAccounts
from src.lending.unsigned_builders.contract import SequenceItem
from src.multichain.sui import SuiObjectKind, SuiObjectRef, SuiStateFrame

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "r03"


def load_fixture(name: str) -> dict:
    import json

    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


# Deterministic synthetic pubkeys (never real accounts).
SYNTHETIC = {
    "signer": "6QWeT6FpJrm8AF1btu6WH2k2Xhq6t5vbheKVfQavmenB",
    "borrow_ata": "6URwbPipuA4MJLG7LCRRZuWnms3JZ9cRG3z9indXWz6t",
    "mint": "6YMEjhBqVTMaSRWcmVkLrnHZ22FWEDJEpTeonAg8GKRb",
    "reserves_liquidity": "6cGXszer5keoaWm8Co5G9f4KGBThuGz4NsKTqYij1ekJ",
    "borrow_position": "6gBq2J7rg3x2ic1de6QBSXq5WLfuaLfswGz7tvmKkz51",
    "rate_model": "6k78AbasGMFFrhG95Pj6jQbqkVt7FQMhVgemxJovWKPi",
    "vault": "6p2RJu3sreYUznWeWh422HNbzf6JvU3X46KS1grXFeiR",
    "liquidity": "6swiTCWtSwqi8sm9wzNwKA9NEpJWbXjLcVz654u7zz38",
    "generic_route": "6ws1bVyu3F8wGy1fPHhrc2v8UyWiGbRAAuek8SwikKMq",
    "p0_account": "71nJjoSudYSAR4GApb2mtugtj8iuwf6yjKKQBpzKVegY",
    "generic_a": "75hbt6uvDqjPZ9WgFtMhBnTeyHw7cinoHiz4FD2vEz1F",
    "generic_b": "79cu2QNvp92chEmBhBgcUfERDT9KHnUcr8eiJb5WzKKx",
    "generic_c": "7DYCAhqwQSKqqL1h8V1XmY1BTcMWxrASQYKNMy87jeef",
}

JUPITER_AMOUNT = 1_000_000


def jupiter_accounts(
    *,
    flashloan_admin: str = "ALXWtv2P4GqH1B7Lq731joag52yRBRqmHV4naiXPTYWL",
    signer: str | None = None,
) -> JupiterLendFlashloanAccounts:
    """Synthetic account binding; the admin PDA is the public pinned constant."""

    return JupiterLendFlashloanAccounts(
        signer=Pubkey.from_string(signer or SYNTHETIC["signer"]),
        flashloan_admin=Pubkey.from_string(flashloan_admin),
        signer_borrow_token_account=Pubkey.from_string(SYNTHETIC["borrow_ata"]),
        mint=Pubkey.from_string(SYNTHETIC["mint"]),
        flashloan_token_reserves_liquidity=Pubkey.from_string(
            SYNTHETIC["reserves_liquidity"]
        ),
        flashloan_borrow_position_on_liquidity=Pubkey.from_string(
            SYNTHETIC["borrow_position"]
        ),
        rate_model=Pubkey.from_string(SYNTHETIC["rate_model"]),
        vault=Pubkey.from_string(SYNTHETIC["vault"]),
        liquidity=Pubkey.from_string(SYNTHETIC["liquidity"]),
        liquidity_program=Pubkey.from_string(
            "jupeiUmn818Jg1ekPURTpr4mFo29p46vygyykFJ3wZC"
        ),
        token_program=Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
    )


def sequence_item(program_id: str, data_hex: str) -> SequenceItem:
    return SequenceItem(program_id=program_id, data_hex=data_hex)


# NAVI synthetic deployed-config identity (structure-conformance fixture only).
NAVI_PACKAGE = "0x" + "aa" * 32
NAVI_STORAGE = "0x" + "bb" * 32
NAVI_FLASHLOAN_CONFIG = "0x" + "cc" * 32
NAVI_POOL = "0x" + "dd" * 32
NAVI_REPAY_COIN = "0x" + "e1" * 32
NAVI_COIN_TYPE = "0x2::sui::SUI"
SUI_CLOCK_FULL = "0x" + "0" * 63 + "6"
SUI_SYSTEM_STATE_FULL = "0x" + "0" * 63 + "5"


def navi_frame(
    *, repay_coin_kind: SuiObjectKind = SuiObjectKind.OWNED
) -> SuiStateFrame:
    """Synthetic Sui state frame with all required shared/owned objects."""

    def shared(object_id: str) -> SuiObjectRef:
        return SuiObjectRef(
            object_id=object_id,
            version=7,
            digest="d" * 64,
            kind=SuiObjectKind.SHARED,
            type_tag="fixture",
        )

    return SuiStateFrame(
        chain_key="sui",
        checkpoint=42,
        epoch=3,
        objects=(
            shared(NAVI_FLASHLOAN_CONFIG),
            shared(NAVI_POOL),
            shared(NAVI_STORAGE),
            shared(SUI_CLOCK_FULL),
            shared(SUI_SYSTEM_STATE_FULL),
            SuiObjectRef(
                object_id=NAVI_REPAY_COIN,
                version=9,
                digest="d" * 64,
                kind=repay_coin_kind,
                type_tag="0x2::coin::Coin<0x2::sui::SUI>",
            ),
        ),
    )


def sha256_hex(seed: str) -> str:
    import hashlib

    return hashlib.sha256(seed.encode("utf-8")).hexdigest()
