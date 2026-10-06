"""Strict Raydium CPMM account decoding for bounded, read-only shadow replay.

Layouts are pinned to the fee owner's upstream revision. This decodes evidence;
the existing exact CPMM adapter owns arithmetic. A deployed binary hash is
recorded, but does not establish a reproducible source-to-deployment binding.
Token-2022, unknown layouts and incomplete account sets are rejected.
"""

from __future__ import annotations

import base64
import copy
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Mapping

from solders.pubkey import Pubkey

from src.direct_venue.cpmm_math import RAYDIUM_FEE_SOURCE_REVISION
from src.market.observations import ObservationGeneration
from src.strategy.arbitrage_graph import VenueIdentity
from src.strategy.exact_cpmm_capacity import (
    MAINNET_GENESIS,
    PINNED_DECODER_REVISION,
    PINNED_TOKEN_REVISION,
    QualifiedCpmmState,
    QualifiedRaydiumCpmmAdapter,
    RAYDIUM_CPMM_PROGRAM_ID,
    SPL_TOKEN_PROGRAM,
    SolanaAssetIdentity,
)

SCHEMA = "shadow.raydium-cpmm-native-capture.v1"
LOADER = "BPFLoaderUpgradeab1e11111111111111111111111"
CLOCK = "SysvarC1ock11111111111111111111111111111111"
SYSVAR_OWNER = "Sysvar1111111111111111111111111111111111111"
PROGRAM = Pubkey.from_string(RAYDIUM_CPMM_PROGRAM_ID)
AUTHORITY, AUTH_BUMP = Pubkey.find_program_address(
    [b"vault_and_lp_mint_auth_seed"], PROGRAM
)


class NativeCaptureError(ValueError):
    """Missing, malformed or incoherent native evidence; never a zero quote."""


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def integer(value: Any, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum or value > 2**63 - 1:
        raise NativeCaptureError(f"invalid {label}")
    return value


def key(value: Any) -> str:
    if not isinstance(value, str):
        raise NativeCaptureError("public key must be text")
    try:
        parsed = Pubkey.from_string(value)
    except ValueError as exc:
        raise NativeCaptureError("invalid public key") from exc
    if str(parsed) != value:
        raise NativeCaptureError("noncanonical public key")
    return value


def _u(data: bytes, offset: int, size: int = 8) -> int:
    return int.from_bytes(data[offset : offset + size], "little")


def _pk(data: bytes, offset: int) -> str:
    return str(Pubkey.from_bytes(data[offset : offset + 32]))


def _layout(data: bytes, length: int, name: str) -> None:
    if (
        len(data) != length
        or data[:8] != hashlib.sha256(f"account:{name}".encode()).digest()[:8]
    ):
        raise NativeCaptureError(f"unsupported {name} layout/discriminator")


@dataclass(frozen=True, slots=True)
class NativeAccount:
    address: str
    owner: str
    executable: bool
    data: bytes
    lamports: int

    @classmethod
    def from_rpc(cls, address: Any, value: Any) -> NativeAccount:
        if not isinstance(value, dict) or type(value.get("executable")) is not bool:
            raise NativeCaptureError("missing account or executable flag")
        encoded = value.get("data")
        if (
            not isinstance(encoded, list)
            or len(encoded) != 2
            or encoded[1] != "base64"
            or not isinstance(encoded[0], str)
            or len(encoded[0])
            > (6_000_000 if value.get("owner") == LOADER else 900_000)
        ):
            raise NativeCaptureError("bounded base64 account data required")
        try:
            data = base64.b64decode(encoded[0], validate=True)
        except ValueError as exc:
            raise NativeCaptureError("invalid base64 account data") from exc
        lamports = value.get("lamports")
        if type(lamports) is not int or not 0 <= lamports <= 2**64 - 1:
            raise NativeCaptureError("invalid account lamports")
        return cls(
            key(address), key(value.get("owner")), value["executable"], data, lamports
        )

    def require(self, owner: str, length: int | None = None) -> bytes:
        if (
            self.owner != owner
            or self.executable
            or (length is not None and len(self.data) != length)
        ):
            raise NativeCaptureError("account owner, executable or size mismatch")
        return self.data


@dataclass(frozen=True, slots=True)
class PoolPointers:
    pool: str
    config: str
    vaults: tuple[str, str]
    lp_mint: str
    mints: tuple[str, str]
    token_programs: tuple[str, str]
    observation: str

    @property
    def required_accounts(self) -> tuple[str, ...]:
        return (
            self.pool,
            self.config,
            *self.vaults,
            self.lp_mint,
            *self.mints,
            self.observation,
        )


def pool_pointers(account: NativeAccount) -> PoolPointers:
    data = account.require(RAYDIUM_CPMM_PROGRAM_ID)
    _layout(data, 637, "PoolState")
    return PoolPointers(
        account.address,
        _pk(data, 8),
        (_pk(data, 72), _pk(data, 104)),
        _pk(data, 136),
        (_pk(data, 168), _pk(data, 200)),
        (_pk(data, 232), _pk(data, 264)),
        _pk(data, 296),
    )


def program_data_address(account: NativeAccount) -> str:
    if account.address != RAYDIUM_CPMM_PROGRAM_ID or account.owner != LOADER:
        raise NativeCaptureError("wrong CPMM deployment owner")
    if not account.executable or len(account.data) != 36 or _u(account.data, 0, 4) != 2:
        raise NativeCaptureError("unsupported upgradeable program layout")
    return _pk(account.data, 4)


@dataclass(frozen=True, slots=True)
class DecodedNativeCapture:
    pools: tuple[QualifiedCpmmState, ...]
    slot: int
    available_at_ns: int
    observed_at_ns: int
    block_hash: str
    parent_hash: str
    binary_sha256: str
    deployment_slot: int
    capture_hash: str
    evidence_kind: str


def decode_native_capture(
    payload: Mapping[str, Any], *, max_age_seconds: float = 120.0
) -> DecodedNativeCapture:
    if (
        payload.get("schema") != SCHEMA
        or payload.get("decoder_revision") != PINNED_DECODER_REVISION
    ):
        raise NativeCaptureError("unsupported capture schema/decoder")
    if payload.get("source_revision") != RAYDIUM_FEE_SOURCE_REVISION:
        raise NativeCaptureError("unsupported source revision")
    if (
        payload.get("genesis_hash") != MAINNET_GENESIS
        or payload.get("commitment") != "finalized"
    ):
        raise NativeCaptureError("wrong genesis or non-finalized capture")
    if payload.get("evidence_kind") not in {"captured-rpc", "synthetic-fixture"}:
        raise NativeCaptureError("explicit evidence kind required")
    if not math.isfinite(max_age_seconds) or not 0 < max_age_seconds <= 3600:
        raise NativeCaptureError("invalid freshness bound")
    slot = integer(payload.get("slot"), "context slot", 1)
    observed = integer(payload.get("observed_at_ns"), "observed time", 1)
    available = integer(payload.get("available_at_ns"), "available time", observed)
    block = payload.get("block")
    if (
        not isinstance(block, dict)
        or integer(block.get("parentSlot"), "parent slot") >= slot
    ):
        raise NativeCaptureError("missing rooted block/parent")
    block_hash, parent_hash = key(block.get("blockhash")), key(
        block.get("previousBlockhash")
    )
    block_time = integer(block.get("blockTime"), "block time", 1)
    if block_hash == parent_hash or block_time * 10**9 > available:
        raise NativeCaptureError("invalid rooted block clock/hash")
    raw = payload.get("accounts")
    pool_ids = payload.get("pool_ids")
    if (
        not isinstance(raw, list)
        or not 1 <= len(raw) <= 100
        or any(not isinstance(e, dict) for e in raw)
    ):
        raise NativeCaptureError("bounded complete account list required")
    metadata = payload.get("account_response_metadata")
    if not isinstance(metadata, dict) or metadata.get("jsonrpc") != "2.0":
        raise NativeCaptureError("raw account response envelope required")
    response = copy.deepcopy(metadata)
    result = response.get("result")
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("context"), dict)
        or result["context"].get("slot") != slot
        or "value" in result
    ):
        raise NativeCaptureError("raw account response context mismatch")
    result["value"] = [
        entry.get("value") if isinstance(entry, dict) else None for entry in raw
    ]
    if content_hash(response) != payload.get("account_response_hash"):
        raise NativeCaptureError("raw account response hash mismatch")
    manifest = payload.get("manifest_sha256")
    if (
        not isinstance(manifest, str)
        or len(manifest) != 64
        or any(c not in "0123456789abcdef" for c in manifest)
    ):
        raise NativeCaptureError("manifest hash required")
    if payload["evidence_kind"] == "captured-rpc":
        receipts = payload.get("rpc_receipts")
        if (
            not isinstance(receipts, list)
            or len(receipts) != 4
            or any(
                not isinstance(r, dict) or r.get("error") or r.get("http_status") != 200
                for r in receipts
            )
        ):
            raise NativeCaptureError("complete successful RPC receipt chain required")
        if [r.get("method") for r in receipts] != [
            "getGenesisHash",
            "getMultipleAccounts",
            "getMultipleAccounts",
            "getBlock",
        ] or receipts[2].get("response_hash") != payload["account_response_hash"]:
            raise NativeCaptureError("RPC receipt/account provenance mismatch")
        for receipt in receipts:
            request_body = receipt.get("request_body")
            if (
                not isinstance(request_body, dict)
                or request_body.get("jsonrpc") != "2.0"
                or request_body.get("method") != receipt["method"]
                or request_body.get("id") != receipt.get("request_id")
            ):
                raise NativeCaptureError("RPC request envelope mismatch")
            if content_hash(
                {"url": receipt.get("endpoint"), "body": request_body}
            ) != receipt.get("request_fingerprint"):
                raise NativeCaptureError("RPC request provenance mismatch")
            started = integer(receipt.get("requested_at_ns"), "request time", 1)
            finished = integer(receipt.get("available_at_ns"), "receipt time", started)
            if finished > available:
                raise NativeCaptureError("future receipt in native capture")
        request_params = receipts[2]["request_body"].get("params")
        if (
            not isinstance(request_params, list)
            or len(request_params) != 2
            or request_params[0] != [e.get("address") for e in raw]
            or not isinstance(request_params[1], dict)
            or request_params[1].get("commitment") != "finalized"
            or request_params[1].get("encoding") != "base64"
            or metadata.get("id") != receipts[2]["request_id"]
        ):
            raise NativeCaptureError("account address/order/read scope mismatch")
        root_params = receipts[3]["request_body"].get("params")
        if (
            not isinstance(root_params, list)
            or len(root_params) != 2
            or root_params[0] != slot
            or not isinstance(root_params[1], dict)
            or root_params[1].get("commitment") != "finalized"
            or root_params[1].get("transactionDetails") != "none"
        ):
            raise NativeCaptureError("root request/context scope mismatch")
        root_reply = {
            "jsonrpc": "2.0",
            "id": receipts[3].get("request_id"),
            "result": block,
        }
        if (
            content_hash(root_reply) != receipts[3].get("response_hash")
            or receipts[2].get("available_at_ns") != observed
            or receipts[3].get("available_at_ns", available + 1) > available
        ):
            raise NativeCaptureError("root receipt/time provenance mismatch")
    if not isinstance(pool_ids, list) or not 1 <= len(pool_ids) <= 8:
        raise NativeCaptureError("require 1..8 pool addresses")
    pools = tuple(sorted(key(v) for v in pool_ids))
    if len(set(pools)) != len(pools):
        raise NativeCaptureError("duplicate pool address")
    accounts: dict[str, NativeAccount] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise NativeCaptureError("invalid raw account entry")
        account = NativeAccount.from_rpc(entry.get("address"), entry.get("value"))
        if account.address in accounts:
            raise NativeCaptureError("duplicate account address")
        accounts[account.address] = account

    def require(address: str) -> NativeAccount:
        try:
            return accounts[address]
        except KeyError as exc:
            raise NativeCaptureError("incomplete native account set") from exc

    programdata = require(
        program_data_address(require(RAYDIUM_CPMM_PROGRAM_ID))
    ).require(LOADER)
    if (
        len(programdata) <= 45
        or _u(programdata, 0, 4) != 3
        or programdata[12] not in (0, 1)
    ):
        raise NativeCaptureError("unsupported programdata layout")
    deployment_slot = _u(programdata, 4)
    if deployment_slot > slot:
        raise NativeCaptureError("deployment newer than bank")
    binary_sha256 = hashlib.sha256(programdata[45:]).hexdigest()
    clock = require(CLOCK).require(SYSVAR_OWNER, 40)
    chain_time = int.from_bytes(clock[32:40], "little", signed=True)
    if _u(clock, 0) != slot or abs(chain_time - block_time) > 2:
        raise NativeCaptureError("clock/block/context incoherent")
    generation = ObservationGeneration(
        genesis_hash=MAINNET_GENESIS,
        provider_generation=manifest,
        asset_generation=PINNED_TOKEN_REVISION,
        policy_generation="finalized-native-shadow-v1",
        code_generation=f"{PINNED_DECODER_REVISION}:{binary_sha256}",
    )
    states: list[QualifiedCpmmState] = []
    expected_accounts = {
        RAYDIUM_CPMM_PROGRAM_ID,
        program_data_address(require(RAYDIUM_CPMM_PROGRAM_ID)),
        CLOCK,
    }
    for pool_id in pools:
        pool = require(pool_id)
        pointers = pool_pointers(pool)
        expected_accounts.update(pointers.required_accounts)
        if pointers.token_programs != (SPL_TOKEN_PROGRAM, SPL_TOKEN_PROGRAM):
            raise NativeCaptureError("Token-2022/unknown token program is unqualified")
        if bytes(Pubkey.from_string(pointers.mints[0])) >= bytes(
            Pubkey.from_string(pointers.mints[1])
        ):
            raise NativeCaptureError("pool mint order is noncanonical")
        if len(set(pointers.required_accounts)) != len(pointers.required_accounts):
            raise NativeCaptureError("aliased pool accounts")
        data = pool.data
        if data[328] != AUTH_BUMP or data[329] & 4 or data[329] & ~7:
            raise NativeCaptureError("invalid authority bump or paused/unknown status")
        if (
            chain_time < _u(data, 373)
            or data[390] not in (0, 1)
            or data[389] not in (0, 1, 2)
        ):
            raise NativeCaptureError("pool not open or unsupported creator flags")
        config = require(pointers.config).require(RAYDIUM_CPMM_PROGRAM_ID)
        _layout(config, 236, "AmmConfig")
        config_key, config_bump = Pubkey.find_program_address(
            [b"amm_config", _u(config, 10, 2).to_bytes(2, "big")], PROGRAM
        )
        if (
            str(config_key) != pointers.config
            or config[8] != config_bump
            or config[9] not in (0, 1)
        ):
            raise NativeCaptureError("config PDA/bump/flags mismatch")
        oracle = require(pointers.observation).require(RAYDIUM_CPMM_PROGRAM_ID)
        _layout(oracle, 4075, "ObservationState")
        oracle_key, _ = Pubkey.find_program_address(
            [b"observation", bytes(Pubkey.from_string(pool_id))], PROGRAM
        )
        if (
            str(oracle_key) != pointers.observation
            or _pk(oracle, 11) != pool_id
            or oracle[8] not in (0, 1)
            or _u(oracle, 9, 2) >= 100
        ):
            raise NativeCaptureError("oracle binding/index mismatch")
        assets: list[SolanaAssetIdentity] = []
        balances: list[int] = []
        for i in range(2):
            mint = require(pointers.mints[i]).require(SPL_TOKEN_PROGRAM, 82)
            if (
                mint[45] != 1
                or _u(mint, 0, 4) not in (0, 1)
                or _u(mint, 46, 4) not in (0, 1)
                or mint[44] != data[331 + i]
            ):
                raise NativeCaptureError("mint layout/initialization/decimals mismatch")
            vault_account = require(pointers.vaults[i])
            vault = vault_account.require(SPL_TOKEN_PROGRAM, 165)
            if (
                _pk(vault, 0) != pointers.mints[i]
                or _pk(vault, 32) != str(AUTHORITY)
                or vault[108] != 1
                or _u(vault, 72, 4) != 0
                or _u(vault, 129, 4) != 0
            ):
                raise NativeCaptureError("vault mint/authority/state/delegate mismatch")
            native = _u(vault, 109, 4)
            if native != int(
                pointers.mints[i] == "So11111111111111111111111111111111111111112"
            ) or (
                native == 1 and vault_account.lamports < _u(vault, 113) + _u(vault, 64)
            ):
                raise NativeCaptureError("invalid native vault tag")
            assets.append(
                SolanaAssetIdentity(
                    "solana-mainnet",
                    MAINNET_GENESIS,
                    pointers.mints[i],
                    SPL_TOKEN_PROGRAM,
                    PINNED_TOKEN_REVISION,
                    mint[44],
                )
            )
            balances.append(_u(vault, 64))
        lp = require(pointers.lp_mint).require(SPL_TOKEN_PROGRAM, 82)
        if (
            lp[45] != 1
            or lp[44] != data[330]
            or _u(lp, 0, 4) != 1
            or _pk(lp, 4) != str(AUTHORITY)
            or _u(lp, 46, 4) != 0
        ):
            raise NativeCaptureError("LP mint authority/layout mismatch")
        fees_a = (_u(data, 341), _u(data, 357), _u(data, 397))
        fees_b = (_u(data, 349), _u(data, 365), _u(data, 405))
        if balances[0] <= sum(fees_a) or balances[1] <= sum(fees_b):
            raise NativeCaptureError("fee counters exceed available reserves")
        state = QualifiedCpmmState(
            venue=VenueIdentity(RAYDIUM_CPMM_PROGRAM_ID, pool_id),
            asset_a=assets[0],
            asset_b=assets[1],
            reserve_a=balances[0] - sum(fees_a),
            reserve_b=balances[1] - sum(fees_b),
            fee_bps=0,
            slot=slot,
            observed_at=float(block_time),
            expires_at=block_time + max_age_seconds,
            generation=generation,
            trade_fee_rate_ppm=_u(config, 12),
            protocol_fee_rate_ppm=_u(config, 20),
            fund_fee_rate_ppm=_u(config, 28),
            creator_fee_rate_ppm=_u(config, 108) if data[390] else 0,
            creator_fee_on=("both", "token-a", "token-b")[data[389]],
            accrued_fees_a=fees_a,
            accrued_fees_b=fees_b,
        )
        QualifiedRaydiumCpmmAdapter.qualify_state(state)
        states.append(state)
    if set(accounts) != expected_accounts:
        raise NativeCaptureError("unexpected accounts outside coherent native set")
    return DecodedNativeCapture(
        tuple(states),
        slot,
        available,
        observed,
        block_hash,
        parent_hash,
        binary_sha256,
        deployment_slot,
        content_hash(payload),
        str(payload["evidence_kind"]),
    )
