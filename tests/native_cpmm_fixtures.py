"""Synthetic raw-account corpus. None of these bytes came from mainnet."""

import base64
import hashlib
from solders.pubkey import Pubkey

from src.direct_venue.cpmm_math import RAYDIUM_FEE_SOURCE_REVISION
from src.providers.raydium_cpmm_native import (
    AUTHORITY,
    AUTH_BUMP,
    CLOCK,
    LOADER,
    PROGRAM,
    SCHEMA,
    SYSVAR_OWNER,
    content_hash,
)
from src.strategy.exact_cpmm_capacity import (
    MAINNET_GENESIS,
    PINNED_DECODER_REVISION,
    RAYDIUM_CPMM_PROGRAM_ID,
    SPL_TOKEN_PROGRAM,
    WSOL_MINT,
)


def address(n):
    return str(Pubkey.from_bytes(bytes([n]) * 32))


def put(data, offset, value, size=8):
    data[offset : offset + size] = value.to_bytes(size, "little")


def pub(data, offset, value):
    data[offset : offset + 32] = bytes(Pubkey.from_string(value))


def anchor(name, size):
    data = bytearray(size)
    data[:8] = hashlib.sha256(f"account:{name}".encode()).digest()[:8]
    return data


def account(data, owner, executable=False):
    return {
        "data": [base64.b64encode(data).decode(), "base64"],
        "owner": owner,
        "executable": executable,
        "lamports": 1_000_000,
        "rentEpoch": 0,
        "space": len(data),
    }


def mint_data(decimals=9, lp=False):
    data = bytearray(82)
    data[44] = decimals
    data[45] = 1
    if lp:
        put(data, 0, 1, 4)
        pub(data, 4, str(AUTHORITY))
    return data


def synthetic_capture(*, fourth=False):
    accounts = {}
    programdata = address(80)
    program = bytearray(36)
    put(program, 0, 2, 4)
    pub(program, 4, programdata)
    accounts[RAYDIUM_CPMM_PROGRAM_ID] = account(program, LOADER, True)
    binary = bytearray(45) + b"synthetic-program-code"
    put(binary, 0, 3, 4)
    put(binary, 4, 10)
    accounts[programdata] = account(binary, LOADER)
    clock = bytearray(40)
    put(clock, 0, 100)
    put(clock, 32, 1000)
    accounts[CLOCK] = account(clock, SYSVAR_OWNER)
    config_key, bump = Pubkey.find_program_address([b"amm_config", bytes(2)], PROGRAM)
    config_key = str(config_key)
    config = anchor("AmmConfig", 236)
    config[8] = bump
    put(config, 12, 2500)
    put(config, 20, 120_000)
    put(config, 28, 40_000)
    put(config, 108, 1000)
    accounts[config_key] = account(config, RAYDIUM_CPMM_PROGRAM_ID)
    a, b, c, d = WSOL_MINT, address(3), address(4), address(5)
    definitions = [(a, b, 333, 9170), (b, c, 2350, 6118), (c, a, 8573, 266)]
    if fourth:
        definitions[-1:] = [(c, d, 8573, 10000), (d, a, 9000, 266)]
    pools = []
    for i, (token0, token1, r0, r1) in enumerate(definitions):
        if bytes(Pubkey.from_string(token0)) > bytes(Pubkey.from_string(token1)):
            token0, token1, r0, r1 = token1, token0, r1, r0
        pool_id = address(50 + i)
        pools.append(pool_id)
        vaults = (address(20 + i * 2), address(21 + i * 2))
        lp = address(30 + i)
        oracle_key, _ = Pubkey.find_program_address(
            [b"observation", bytes(Pubkey.from_string(pool_id))], PROGRAM
        )
        oracle_key = str(oracle_key)
        pool = anchor("PoolState", 637)
        pub(pool, 8, config_key)
        for offset, key in [
            (40, address(90)),
            (72, vaults[0]),
            (104, vaults[1]),
            (136, lp),
            (168, token0),
            (200, token1),
            (232, SPL_TOKEN_PROGRAM),
            (264, SPL_TOKEN_PROGRAM),
            (296, oracle_key),
        ]:
            pub(pool, offset, key)
        pool[328] = AUTH_BUMP
        pool[330:333] = bytes([9, 9, 9])
        put(pool, 341, 7)
        put(pool, 349, 11)
        put(pool, 357, 13)
        put(pool, 365, 17)
        put(pool, 397, 19)
        put(pool, 405, 23)
        pool[390] = 1
        accounts[pool_id] = account(pool, RAYDIUM_CPMM_PROGRAM_ID)
        for j, (token, reserve) in enumerate(((token0, r0), (token1, r1))):
            accounts[token] = account(mint_data(), SPL_TOKEN_PROGRAM)
            vault = bytearray(165)
            pub(vault, 0, token)
            pub(vault, 32, str(AUTHORITY))
            put(vault, 64, reserve + (39 if j == 0 else 51))
            vault[108] = 1
            if token == WSOL_MINT:
                put(vault, 109, 1, 4)
                put(vault, 113, 500_000)
            accounts[vaults[j]] = account(vault, SPL_TOKEN_PROGRAM)
        accounts[lp] = account(mint_data(lp=True), SPL_TOKEN_PROGRAM)
        oracle = anchor("ObservationState", 4075)
        pub(oracle, 11, pool_id)
        accounts[oracle_key] = account(oracle, RAYDIUM_CPMM_PROGRAM_ID)
    payload = {
        "schema": SCHEMA,
        "evidence_kind": "synthetic-fixture",
        "decoder_revision": PINNED_DECODER_REVISION,
        "source_revision": RAYDIUM_FEE_SOURCE_REVISION,
        "genesis_hash": MAINNET_GENESIS,
        "commitment": "finalized",
        "slot": 100,
        "pool_ids": sorted(pools),
        "manifest_sha256": "a" * 64,
        "observed_at_ns": 1001 * 10**9,
        "available_at_ns": 1002 * 10**9,
        "block": {
            "blockhash": address(10),
            "previousBlockhash": address(11),
            "parentSlot": 99,
            "blockTime": 1000,
        },
        "accounts": [{"address": k, "value": v} for k, v in sorted(accounts.items())],
        "account_response_metadata": {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {"context": {"slot": 100}},
        },
    }
    rehash(payload)
    return payload


def rehash(payload):
    response = {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {
            "context": {"slot": payload["slot"]},
            "value": [a["value"] for a in payload["accounts"]],
        },
    }
    payload["account_response_metadata"]["result"]["context"]["slot"] = payload["slot"]
    payload["account_response_hash"] = content_hash(response)


def mutate_account(payload, key, change):
    entry = next(e for e in payload["accounts"] if e["address"] == key)
    data = bytearray(base64.b64decode(entry["value"]["data"][0]))
    change(data)
    entry["value"]["data"][0] = base64.b64encode(data).decode()
    rehash(payload)
