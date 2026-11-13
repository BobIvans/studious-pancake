"""Synthetic Meteora DLMM account fixtures (offline, no mainnet bytes).

Built from the pinned Anchor IDL snapshot in
``docs/integrations/offline/solana-p0/vendor-reference/meteora/lb_clmm.idl.json``
(discriminators verified byte-identical to ``sha256("account:<Name>")[:8]``).
"""

from __future__ import annotations

import base64
import hashlib
import struct

from solders.pubkey import Pubkey

from src.providers.meteora_dlmm_native import (
    BIN_LEN,
    BIN_ARRAY_LEN,
    LB_PAIR_LEN,
    METEORA_DLMM_PROGRAM_ID,
)
from tests.native_cpmm_fixtures import address


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


def lb_pair_bytes(
    *,
    active_id: int = 5,
    bin_step: int = 10,
    status: int = 0,
    mints: tuple[str, str] | None = None,
    token_flags: tuple[int, int] = (0, 0),
    base_factor: int = 500,
    base_fee_power_factor: int = 1,
    version: int = 0,
) -> tuple[bytes, str, tuple[str, str]]:
    mints = mints or (address(31), address(32))
    pair, _ = Pubkey.find_program_address(
        [
            b"lb_pair",
            bytes(Pubkey.from_string(mints[0])),
            bytes(Pubkey.from_string(mints[1])),
            struct.pack("<H", bin_step),
            struct.pack("<H", 0),  # base_factor_seed
        ],
        Pubkey.from_string(METEORA_DLMM_PROGRAM_ID),
    )
    reserve_x, _ = Pubkey.find_program_address(
        [b"vault", bytes(Pubkey.from_string(mints[0]))],
        Pubkey.from_string(METEORA_DLMM_PROGRAM_ID),
    )
    reserve_y, _ = Pubkey.find_program_address(
        [b"vault", bytes(Pubkey.from_string(mints[1]))],
        Pubkey.from_string(METEORA_DLMM_PROGRAM_ID),
    )
    data = bytearray(LB_PAIR_LEN)
    data[:8] = _discriminator("LbPair")
    # StaticParameters (offset 8): base_factor, filter/decay/reduction periods.
    struct.pack_into("<H", data, 8, base_factor)
    struct.pack_into("<H", data, 16, 5_000)  # variable_fee_control (rel 8)
    struct.pack_into("<I", data, 20, 10_000)  # max_volatility_accumulator (rel 12)
    data[34] = base_fee_power_factor  # base_fee_power_factor (rel 26)
    data[72] = 253  # bump_seed
    struct.pack_into("<H", data, 73, 0)  # bin_step_seed
    data[75] = 0  # pair_type: Permissionless
    struct.pack_into("<i", data, 76, active_id)
    struct.pack_into("<H", data, 80, bin_step)
    data[82] = status
    data[88:120] = bytes(Pubkey.from_string(mints[0]))
    data[120:152] = bytes(Pubkey.from_string(mints[1]))
    data[152:184] = bytes(reserve_x)
    data[184:216] = bytes(reserve_y)
    struct.pack_into("<Q", data, 216, 1_000)  # protocol_fee.amount_x
    struct.pack_into("<Q", data, 224, 2_000)  # protocol_fee.amount_y
    oracle, _ = Pubkey.find_program_address(
        [b"oracle", bytes(pair)], Pubkey.from_string(METEORA_DLMM_PROGRAM_ID)
    )
    data[552:584] = bytes(oracle)
    struct.pack_into("<q", data, 712, 1_700_000_000)  # last_updated_at
    data[880] = token_flags[0]
    data[881] = token_flags[1]
    data[882] = version
    return bytes(data), str(pair), mints


def bin_array_bytes(
    pair_address: str,
    index: int,
    *,
    bins: dict[int, tuple[int, int, int, int]] | None = None,
    version: int = 0,
) -> bytes:
    """``bins`` maps in-array slot 0..69 -> (amount_x, amount_y, price, liquidity)."""
    data = bytearray(BIN_ARRAY_LEN)
    data[:8] = _discriminator("BinArray")
    struct.pack_into("<q", data, 8, index)
    data[16] = version
    data[24:56] = bytes(Pubkey.from_string(pair_address))
    for slot, (ax, ay, price, liq) in (bins or {}).items():
        base = 56 + BIN_LEN * slot
        struct.pack_into("<Q", data, base, ax)
        struct.pack_into("<Q", data, base + 8, ay)
        struct.pack_into(
            "<QQ", data, base + 16, price & 0xFFFFFFFFFFFFFFFF, price >> 64
        )
        struct.pack_into("<QQ", data, base + 32, liq & 0xFFFFFFFFFFFFFFFF, liq >> 64)
    return bytes(data)
