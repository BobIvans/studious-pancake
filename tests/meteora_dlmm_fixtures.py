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


def lb_pair_bytes_v2(  # noqa: ANN201 - fixture builder
    *,
    filter_period: int = 60,
    decay_period: int = 300,
    reduction_factor: int = 5_000,
    min_bin_id: int = -7000,
    max_bin_id: int = 7000,
    protocol_share: int = 2_000,
    function_type: int = 1,
    collect_fee_mode: int = 0,
    volatility_reference: int = 0,
    index_reference: int = 0,
    variable_last_update_timestamp: int = 0,
    **kwargs,
):
    """Extended LbPair builder: static/variable fee-parameter passthrough."""
    data, pair, mints = lb_pair_bytes(**kwargs)
    buffer = bytearray(data)
    struct.pack_into("<H", buffer, 10, filter_period)
    struct.pack_into("<H", buffer, 12, decay_period)
    struct.pack_into("<H", buffer, 14, reduction_factor)
    struct.pack_into("<i", buffer, 24, min_bin_id)
    struct.pack_into("<i", buffer, 28, max_bin_id)
    struct.pack_into("<H", buffer, 32, protocol_share)
    buffer[35] = function_type
    buffer[36] = collect_fee_mode
    struct.pack_into("<I", buffer, 44, volatility_reference)
    struct.pack_into("<i", buffer, 48, index_reference)
    struct.pack_into("<q", buffer, 56, variable_last_update_timestamp)
    return bytes(buffer), pair, mints


def bin_array_bitmap_extension_bytes(
    pair_address: str,
    *,
    positive_bits: dict[int, set[int]] | None = None,
    negative_bits: dict[int, set[int]] | None = None,
) -> bytes:
    """BinArrayBitmapExtension bytes (slot 0..11 -> set of bit offsets)."""
    data = bytearray(8 + 32 + 64 * 12 * 2)
    data[:8] = _discriminator("BinArrayBitmapExtension")
    data[8:40] = bytes(Pubkey.from_string(pair_address))
    for slot, bits in (positive_bits or {}).items():
        for bit in bits:
            word = 40 + 64 * slot + 8 * (bit // 64)
            struct.pack_into(
                "<Q",
                data,
                word,
                struct.unpack_from("<Q", data, word)[0] | (1 << (bit % 64)),
            )
    for slot, bits in (negative_bits or {}).items():
        for bit in bits:
            word = 760 + 64 * slot + 8 * (bit // 64)
            struct.pack_into(
                "<Q",
                data,
                word,
                struct.unpack_from("<Q", data, word)[0] | (1 << (bit % 64)),
            )
    return bytes(data)


def token_2022_mint_bytes(
    *,
    transfer_fee_epoch: int | None = None,
    transfer_fee_bps: int | None = None,
    transfer_fee_maximum: int | None = None,
    transfer_hook_program: str | None = None,
    unknown_tag: int | None = None,
) -> tuple[bytes, str]:
    """Token-2022 mint with a minimal TLV region."""
    mint = address(60)
    extensions = bytearray()
    if transfer_fee_epoch is not None:
        payload = struct.pack(
            "<QQH6x",
            transfer_fee_epoch,
            transfer_fee_maximum or 0,
            transfer_fee_bps or 0,
        )
        extensions += struct.pack("<HH", 12, len(payload)) + payload
    if transfer_hook_program is not None:
        payload = bytes(Pubkey.from_string(transfer_hook_program))
        extensions += struct.pack("<HH", 14, len(payload)) + payload
    if unknown_tag is not None:
        payload = struct.pack("<Q", 1)
        extensions += struct.pack("<HH", unknown_tag, len(payload)) + payload
    data = bytearray(82)
    data[0:4] = b"\x00\x00\x00\x01"  # mint authority option + authority placeholder
    data[44 + 32 - 32 : 44] = b"\x00" * 0
    data = bytearray(82 + ((len(extensions) + 7) // 8) * 8 + 2 + 0)
    data[0:4] = b"\x00\x00\x00\x01"
    data[4:36] = bytes(Pubkey.from_string(address(61)))
    struct.pack_into("<Q", data, 36, 1_000_000)  # supply
    data[44] = 9  # decimals
    data[82 : 82 + len(extensions)] = extensions
    total_len = 82 + len(extensions)
    struct.pack_into("<H", data, len(data) - 2, total_len - 82)
    return bytes(data), mint
