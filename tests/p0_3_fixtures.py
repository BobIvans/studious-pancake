"""P0-3 synthetic raw-account corpus for Raydium CLMM and Meteora DLMM.

None of these bytes came from mainnet. Expected quote values in the test
modules are hand-derived from the pinned vendor formulas written out
independently there (differential fixtures, offline only).
"""

from __future__ import annotations

from solders.pubkey import Pubkey

from tests.native_cpmm_fixtures import account, address, pub, put
from src.providers.raydium_clmm_native import (
    POOL_STATE_LEN,
    TICK_ARRAY_STATE_LEN,
    TICK_STATE_LEN,
    array_start_index,
)
from src.providers.meteora_dlmm_native import (
    MAX_BIN_ARRAY_SIZE,
    bin_array_lower_upper_bin_id,
    bin_id_to_bin_array_index,
)
from src.providers.raydium_cpmm_native import content_hash
from src.strategy.exact_cpmm_capacity import MAINNET_GENESIS, SPL_TOKEN_PROGRAM

LOADER = "BPFLoaderUpgradeab1e11111111111111111111111"
CLMM_PROGRAM = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"
DLMM_PROGRAM = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
SLOT = 100
BLOCK_TIME = 1000


def anchor(name: str, size: int) -> bytearray:
    import hashlib

    data = bytearray(size)
    data[:8] = hashlib.sha256(f"account:{name}".encode()).digest()[:8]
    return data


def _program_and_runtime(accounts: dict, program_id: str, code: bytes) -> None:
    programdata = address(80)
    program = bytearray(36)
    put(program, 0, 2, 4)
    pub(program, 4, programdata)
    accounts[program_id] = account(program, LOADER, True)
    binary = bytearray(45) + code
    put(binary, 0, 3, 4)
    put(binary, 4, 10)
    accounts[programdata] = account(binary, LOADER)
    clock = bytearray(40)
    put(clock, 0, SLOT)
    put(clock, 16, 25)
    put(clock, 32, BLOCK_TIME, 8)
    accounts["SysvarC1ock11111111111111111111111111111111"] = account(
        clock, "Sysvar1111111111111111111111111111111111111"
    )


def _mint(accounts: dict, mint: str, decimals: int) -> None:
    data = bytearray(82)
    data[44] = decimals
    data[45] = 1
    accounts[mint] = account(data, SPL_TOKEN_PROGRAM)


def _token_account(accounts: dict, mint: str, owner: str, amount: int) -> None:
    data = bytearray(165)
    pub(data, 0, mint)
    pub(data, 32, owner)
    put(data, 64, amount)
    data[108] = 1
    accounts[owner] = account(data, SPL_TOKEN_PROGRAM)


def _finalize(payload: dict) -> dict:
    response = {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {
            "context": {"slot": payload["slot"]},
            "value": [a["value"] for a in payload["accounts"]],
        },
    }
    payload["account_response_hash"] = content_hash(response)
    return payload


# ---------------------------------------------------------------------------
# Raydium CLMM
# ---------------------------------------------------------------------------


def build_clmm_accounts(
    *,
    config_key: str,
    pool_key: str,
    mint0: str,
    mint1: str,
    vault0: str,
    vault1: str,
    tick_spacing: int,
    liquidity: int,
    sqrt_price_x64: int,
    tick_current: int,
    pool_bump: int,
    fee_on: int = 0,
    status: int = 0,
    trade_fee_rate: int = 2500,
    protocol_fee_rate: int = 100_000,
    fund_fee_rate: int = 40_000,
    ticks: dict[int, tuple[int, int]],
    bitmap_bits: list[int],
    include_array_starts: list[int],
    decimals0: int = 9,
    decimals1: int = 6,
    dynamic_fee_nonzero: bool = False,
) -> dict:
    """``ticks`` maps tick index -> (liquidity_net, liquidity_gross)."""
    accounts: dict = {}
    _program_and_runtime(accounts, CLMM_PROGRAM, b"synthetic-clmm-code")

    config = anchor("AmmConfig", 117)
    config[8] = 254
    put(config, 9, 0, 2)
    pub(config, 11, address(90))
    put(config, 43, protocol_fee_rate, 4)
    put(config, 47, trade_fee_rate, 4)
    put(config, 51, tick_spacing, 2)
    put(config, 53, fund_fee_rate, 4)
    accounts[config_key] = account(config, CLMM_PROGRAM)

    _mint(accounts, mint0, decimals0)
    _mint(accounts, mint1, decimals1)
    _token_account(accounts, mint0, vault0, 10**12)
    _token_account(accounts, mint1, vault1, 10**12)

    pool = anchor("PoolState", POOL_STATE_LEN)
    pool[8] = pool_bump
    pub(pool, 9, config_key)
    pub(pool, 41, address(91))
    pub(pool, 73, mint0)
    pub(pool, 105, mint1)
    pub(pool, 137, vault0)
    pub(pool, 169, vault1)
    pool[233] = decimals0
    pool[234] = decimals1
    put(pool, 235, tick_spacing, 2)
    put(pool, 237, liquidity, 16)
    put(pool, 253, sqrt_price_x64, 16)
    put(pool, 269, tick_current & 0xFFFFFFFF, 4)
    pool[389] = status
    pool[390] = fee_on
    for bit in bitmap_bits:
        word, offset = divmod(bit, 64)
        put(pool, 904 + word * 8, 1 << offset)
    if dynamic_fee_nonzero:
        pool[1096] = 1
    accounts[pool_key] = account(pool, CLMM_PROGRAM)

    arrays: dict[int, dict[int, tuple[int, int, int]]] = {}
    for tick_index, (net, gross) in sorted(ticks.items()):
        start = array_start_index(tick_index, tick_spacing)
        slot = (tick_index - start) // tick_spacing
        arrays.setdefault(start, {})[slot] = (tick_index, net, gross)
    for start in sorted(set(include_array_starts)):
        data = anchor("TickArrayState", TICK_ARRAY_STATE_LEN)
        pub(data, 8, pool_key)
        put(data, 40, start & 0xFFFFFFFF, 4)
        count = 0
        for slot, entry in sorted(arrays.get(start, {}).items()):
            tick_index, net, gross = entry
            base = 44 + slot * TICK_STATE_LEN
            put(data, base, tick_index & 0xFFFFFFFF, 4)
            put(data, base + 4, net & ((1 << 128) - 1), 16)
            put(data, base + 20, gross, 16)
            count += 1
        data[10604] = count
        array_key, _ = Pubkey.find_program_address(
            [
                b"tick_array",
                bytes(Pubkey.from_string(pool_key)),
                (start & 0xFFFFFFFF).to_bytes(4, "big"),
            ],
            Pubkey.from_string(CLMM_PROGRAM),
        )
        accounts[str(array_key)] = account(data, CLMM_PROGRAM)
    return accounts


def clmm_capture(
    accounts: dict, pool_key: str, *, slot: int = SLOT, block_time: int = BLOCK_TIME
) -> dict:
    payload = {
        "schema": "shadow.raydium-clmm-native-capture.v1",
        "decoder_revision": "p0-3.raydium-clmm-native.v1",
        "source_revision": "raydium-clmm@6d7a0f82d2f293c553c69aaf943377367c6c4cc6",
        "evidence_kind": "synthetic-fixture",
        "genesis_hash": MAINNET_GENESIS,
        "commitment": "finalized",
        "slot": slot,
        "pool_ids": [pool_key],
        "manifest_sha256": "b" * 64,
        "observed_at_ns": (block_time + 1) * 10**9,
        "available_at_ns": (block_time + 2) * 10**9,
        "block": {
            "blockhash": address(10),
            "previousBlockhash": address(11),
            "parentSlot": slot - 1,
            "blockTime": block_time,
        },
        "accounts": [{"address": k, "value": v} for k, v in sorted(accounts.items())],
        "account_response_metadata": {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {"context": {"slot": slot}},
        },
    }
    return _finalize(payload)


# ---------------------------------------------------------------------------
# Meteora DLMM
# ---------------------------------------------------------------------------


def build_dlmm_accounts(
    *,
    pair_key: str,
    mint_x: str,
    mint_y: str,
    reserve_x: str,
    reserve_y: str,
    bin_step: int = 10,
    base_factor: int = 25,
    protocol_share: int = 1000,
    variable_fee_control: int = 0,
    collect_fee_mode: int = 0,
    function_type: int = 1,
    pair_type: int = 0,
    status: int = 0,
    active_id: int = 0,
    min_bin_id: int = -1000,
    max_bin_id: int = 1000,
    volatility_accumulator: int = 0,
    volatility_reference: int = 0,
    index_reference: int = 0,
    last_update_timestamp: int = BLOCK_TIME - 10,
    bins: dict[int, tuple[int, int, int]],
    bitmap_bits: list[int],
    include_bin_array_indexes: list[int],
    activation_point: int = 0,
    activation_type: int = 0,
    token_flags: int = 0,
    reserve_x_amount: int | None = None,
    reserve_y_amount: int | None = None,
    protocol_fee_x: int = 0,
    protocol_fee_y: int = 0,
) -> dict:
    """``bins`` maps bin id -> (amount_x, amount_y, price_q128)."""
    accounts: dict = {}
    _program_and_runtime(accounts, DLMM_PROGRAM, b"synthetic-dlmm-code")

    _mint(accounts, mint_x, 9)
    _mint(accounts, mint_y, 6)
    x_amount = reserve_x_amount
    y_amount = reserve_y_amount
    if x_amount is None or y_amount is None:
        total_x = protocol_fee_x
        total_y = protocol_fee_y
        included = set(include_bin_array_indexes)
        for bin_id, (ax, ay, _price) in bins.items():
            if bin_id_to_bin_array_index(bin_id) in included:
                total_x += ax
                total_y += ay
        if x_amount is None:
            x_amount = total_x
        if y_amount is None:
            y_amount = total_y
    _token_account(accounts, mint_x, reserve_x, x_amount)
    _token_account(accounts, mint_y, reserve_y, y_amount)

    pair = anchor("LbPair", 904)
    put(pair, 8, base_factor, 2)
    put(pair, 10, 60, 2)
    put(pair, 12, 600, 2)
    put(pair, 14, 5000, 2)
    put(pair, 16, variable_fee_control, 4)
    put(pair, 20, 2_000_000, 4)
    put(pair, 24, min_bin_id & 0xFFFFFFFF, 4)
    put(pair, 28, max_bin_id & 0xFFFFFFFF, 4)
    put(pair, 32, protocol_share, 2)
    pair[34] = 0
    pair[35] = function_type
    pair[36] = collect_fee_mode
    put(pair, 40, volatility_accumulator, 4)
    put(pair, 44, volatility_reference, 4)
    put(pair, 48, index_reference & 0xFFFFFFFF, 4)
    put(pair, 56, last_update_timestamp & ((1 << 64) - 1), 8)
    pair[72] = 253
    put(pair, 73, 1, 2)
    pair[75] = pair_type
    put(pair, 76, active_id & 0xFFFFFFFF, 4)
    put(pair, 80, bin_step, 2)
    pair[82] = status
    pair[83] = 0
    pair[86] = activation_type
    pair[87] = 0
    pub(pair, 88, mint_x)
    pub(pair, 120, mint_y)
    pub(pair, 152, reserve_x)
    pub(pair, 184, reserve_y)
    put(pair, 216, protocol_fee_x)
    put(pair, 224, protocol_fee_y)
    for bit in bitmap_bits:
        word, offset = divmod(bit, 64)
        existing = int.from_bytes(pair[584 + word * 8 : 584 + word * 8 + 8], "little")
        put(pair, 584 + word * 8, existing | (1 << offset))
    pair[880] = token_flags
    pair[881] = token_flags
    pair[882] = 0
    put(pair, 816, activation_point, 8)
    accounts[pair_key] = account(pair, DLMM_PROGRAM)

    arrays: dict[int, dict[int, tuple[int, int, int]]] = {}
    for bin_id, (ax, ay, price) in sorted(bins.items()):
        index = bin_id_to_bin_array_index(bin_id)
        lower, _upper = bin_array_lower_upper_bin_id(index)
        slot = (
            bin_id - lower
            if bin_id > 0
            else MAX_BIN_ARRAY_SIZE - ((lower + MAX_BIN_ARRAY_SIZE - 1) - bin_id) - 1
        )
        arrays.setdefault(index, {})[slot] = (ax, ay, price)
    for index in sorted(set(include_bin_array_indexes)):
        data = anchor("BinArray", 10136)
        put(data, 8, index & ((1 << 64) - 1), 8)
        pub(data, 24, pair_key)
        for slot, (ax, ay, price) in sorted(arrays.get(index, {}).items()):
            base = 56 + slot * 144
            put(data, base, ax)
            put(data, base + 8, ay)
            put(data, base + 16, price, 16)
        array_key, _ = Pubkey.find_program_address(
            [
                b"bin_array",
                bytes(Pubkey.from_string(pair_key)),
                (index & ((1 << 64) - 1)).to_bytes(8, "little"),
            ],
            Pubkey.from_string(DLMM_PROGRAM),
        )
        accounts[str(array_key)] = account(data, DLMM_PROGRAM)
    return accounts


def build_dlmm_bitmap_extension(
    pair_key: str, positive_bits: list[int], negative_bits: list[int]
) -> tuple[str, dict]:
    """BinArrayBitmapExtension PDA with selected chunk bits set.

    ``positive_bits``/``negative_bits`` are absolute bin array indexes whose
    chunk bit is set (array index -> chunk offset/bit per the pinned findSetBit
    mapping).
    """
    from src.providers.meteora_dlmm_native import (
        _extension_bitmap_offset,
        _extension_bin_array_offset,
    )

    data = anchor("BinArrayBitmapExtension", 1576)
    pub(data, 8, pair_key)
    for base, bits in ((40, positive_bits), (808, negative_bits)):
        for index in bits:
            if (index > 0) != (base == 40):
                raise ValueError("bit list does not match sign side")
            chunk = _extension_bitmap_offset(index)
            offset = _extension_bin_array_offset(index)
            word, bit = divmod(offset, 64)
            existing = int.from_bytes(
                data[base + chunk * 64 + word * 8 : base + chunk * 64 + word * 8 + 8],
                "little",
            )
            put(data, base + chunk * 64 + word * 8, existing | (1 << bit))
    key, _ = Pubkey.find_program_address(
        [b"bitmap", bytes(Pubkey.from_string(pair_key))],
        Pubkey.from_string(DLMM_PROGRAM),
    )
    return str(key), account(data, DLMM_PROGRAM)


def dlmm_capture(
    accounts: dict,
    pair_key: str,
    bin_array_ids: list[str],
    *,
    slot: int = SLOT,
    block_time: int = BLOCK_TIME,
    extension_id: str | None = None,
) -> dict:
    payload = {
        "schema": "shadow.meteora-dlmm-native-capture.v1",
        "decoder_revision": "p0-3.meteora-dlmm-native.v1",
        "source_revision": "dlmm-sdk@1532e540db41ac405dbf4c5bb2ddfceaa1f98ff1",
        "evidence_kind": "synthetic-fixture",
        "genesis_hash": MAINNET_GENESIS,
        "commitment": "finalized",
        "slot": slot,
        "pool_ids": [pair_key],
        "bin_array_ids": bin_array_ids,
        "manifest_sha256": "c" * 64,
        "observed_at_ns": (block_time + 1) * 10**9,
        "available_at_ns": (block_time + 2) * 10**9,
        "block": {
            "blockhash": address(10),
            "previousBlockhash": address(11),
            "parentSlot": slot - 1,
            "blockTime": block_time,
        },
        "accounts": [{"address": k, "value": v} for k, v in sorted(accounts.items())],
        "account_response_metadata": {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {"context": {"slot": slot}},
        },
    }
    if extension_id is not None:
        payload["bin_array_bitmap_extension_id"] = extension_id
    return _finalize(payload)
