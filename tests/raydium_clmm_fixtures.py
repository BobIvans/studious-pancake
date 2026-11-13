"""Synthetic Raydium CLMM account fixtures (offline, no mainnet bytes).

Same discipline as ``tests/native_cpmm_fixtures.py``: every byte is generated
from the pinned layouts in ``src/providers/raydium_clmm_native.py`` and the
vendored Apache-2.0 snapshots; nothing here came from a live chain. Mutations
feed the negative fixture matrix.
"""

from __future__ import annotations

import base64
import hashlib
import struct

from solders.pubkey import Pubkey

from src.providers.raydium_clmm_native import (
    AMM_CONFIG_LEN,
    CLMM_PROGRAM,
    POOL_STATE_LEN,
    TICK_ARRAY_STATE_LEN,
    TICK_STATE_LEN,
    sqrt_price_at_tick,
)
from tests.native_cpmm_fixtures import address

RAYDIUM_CLMM_PROGRAM_ID = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"


def _discriminator(name: str) -> bytes:
    return hashlib.sha256(f"account:{name}".encode()).digest()[:8]


def rpc_account(address_key: str, owner: str, data: bytes) -> dict:
    return {
        "address": address_key,
        "executable": False,
        "owner": owner,
        "lamports": 1_000_000,
        "data": [base64.b64encode(data).decode(), "base64"],
    }


def clmm_amm_config_bytes(
    *,
    trade_fee_rate: int = 2_500,
    protocol_fee_rate: int = 1_000,
    fund_fee_rate: int = 0,
    tick_spacing: int = 1,
) -> bytes:
    data = bytearray(AMM_CONFIG_LEN)
    data[:8] = _discriminator("AmmConfig")
    data[8] = 254  # bump
    struct.pack_into("<H", data, 9, 0)  # index
    data[11:43] = bytes(Pubkey.from_string(address(11)))  # owner
    struct.pack_into("<I", data, 43, protocol_fee_rate)
    struct.pack_into("<I", data, 47, trade_fee_rate)
    struct.pack_into("<H", data, 51, tick_spacing)
    struct.pack_into("<I", data, 53, fund_fee_rate)
    return bytes(data)


def clmm_pool_bytes(
    *,
    config_address: str,
    mints: tuple[str, str] | None = None,
    tick_spacing: int = 1,
    liquidity: int = 1_000_000_000_000,
    tick_current: int = 100,
    status: int = 0,
    fee_on: int = 0,
    bitmap_bits: tuple[int, ...] = (513,),
    sqrt_price_x64: int | None = None,
) -> tuple[bytes, str, tuple[str, str]]:
    """Build PoolState bytes; returns (bytes, pool_address, ordered mints)."""
    mints = mints or (address(21), address(22))
    assert mints[0] < mints[1], "pool mints are ordered mint0 < mint1"
    pool, _ = Pubkey.find_program_address(
        [
            b"pool",
            bytes(Pubkey.from_string(config_address)),
            bytes(Pubkey.from_string(mints[0])),
            bytes(Pubkey.from_string(mints[1])),
        ],
        CLMM_PROGRAM,
    )
    vaults = tuple(
        str(
            Pubkey.find_program_address(
                [b"pool_vault", bytes(pool), bytes(Pubkey.from_string(mint))],
                CLMM_PROGRAM,
            )[0]
        )
        for mint in mints
    )
    observation, _ = Pubkey.find_program_address(
        [b"observation", bytes(pool)], CLMM_PROGRAM
    )
    data = bytearray(POOL_STATE_LEN)
    data[:8] = _discriminator("PoolState")
    data[8] = 251  # bump
    data[9:41] = bytes(Pubkey.from_string(config_address))
    data[41:73] = bytes(Pubkey.from_string(address(23)))  # owner
    data[73:105] = bytes(Pubkey.from_string(mints[0]))
    data[105:137] = bytes(Pubkey.from_string(mints[1]))
    data[137:169] = bytes(Pubkey.from_string(vaults[0]))
    data[169:201] = bytes(Pubkey.from_string(vaults[1]))
    data[201:233] = bytes(observation)
    data[233] = 9  # mint_decimals_0
    data[234] = 9  # mint_decimals_1
    struct.pack_into("<H", data, 235, tick_spacing)
    struct.pack_into("<QQ", data, 237, liquidity & 0xFFFFFFFFFFFFFFFF, liquidity >> 64)
    sp = (
        sqrt_price_x64
        if sqrt_price_x64 is not None
        else sqrt_price_at_tick(tick_current)
    )
    struct.pack_into("<QQ", data, 253, sp & 0xFFFFFFFFFFFFFFFF, sp >> 64)
    struct.pack_into("<i", data, 269, tick_current)
    struct.pack_into("<Q", data, 309, 1_000)  # protocol_fees_token_0
    struct.pack_into("<Q", data, 317, 2_000)  # protocol_fees_token_1
    data[389] = status
    data[390] = fee_on
    for bit in bitmap_bits:
        word, offset = divmod(bit, 64)
        struct.pack_into("<Q", data, 904 + 8 * word, 1 << offset)
    struct.pack_into("<Q", data, 1080, 1_700_000_000)  # open_time
    struct.pack_into("<Q", data, 1088, 700)  # recent_epoch
    return bytes(data), str(pool), mints


def clmm_tick_array_bytes(
    pool_address: str,
    start_tick_index: int,
    *,
    tick_spacing: int = 1,
    initialized: dict[int, tuple[int, int]] | None = None,
) -> bytes:
    """``initialized`` maps array-relative slot -> (liquidity_net, liquidity_gross)."""
    data = bytearray(TICK_ARRAY_STATE_LEN)
    data[:8] = _discriminator("TickArrayState")
    data[8:40] = bytes(Pubkey.from_string(pool_address))
    struct.pack_into("<i", data, 40, start_tick_index)
    for slot, (net, gross) in (initialized or {}).items():
        base = 44 + TICK_STATE_LEN * slot
        struct.pack_into("<i", data, base, start_tick_index + slot * tick_spacing)
        data[base + 4 : base + 20] = (net & ((1 << 128) - 1)).to_bytes(16, "little")
        struct.pack_into("<Q", data, base + 20, gross)
    data[10124] = len(initialized or {})
    struct.pack_into("<Q", data, 10125, 700)  # recent_epoch
    return bytes(data)
