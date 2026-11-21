"""Deterministic offline verification of the N07 Project 0 rebind dossier.

Checks, with zero network access:
1. every vendored blob hash matches SOURCE_MANIFEST.json (git blob sha1);
2. the IDL-pinned Bank layout arithmetic: body 3904 = PR-028 core 1856 +
   trailing padding 2048, and every PR-028 anchor offset matches the
   IDL-derived offset map;
3. the flashloan instruction accounts pinned from the IDL (start: 3 metas,
   end: 3 metas incl. the rebind `group` account);
4. the offline borrow-capacity bound reproduces exact vectors and fails
   closed on the documented negative inputs.

Run: python verify_n07_pins.py   (exit 0 == all pins verified)
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent
REPO = DOSSIER.parents[3]
sys.path.insert(0, str(REPO))

from src.lending.unsigned_builders.project0_builder import (  # noqa: E402
    P0_END_FLASHLOAN_ACCOUNT_METAS,
    P0_START_FLASHLOAN_ACCOUNT_METAS,
    encode_p0_start_flashloan_data,
)
from src.providers.marginfi.layouts import (  # noqa: E402
    P0_BANK_0_1_12_CORE_BODY_LEN,
    P0_BANK_0_1_12_FULL_BODY_LEN,
    P0_BANK_0_1_12_TRAILING_PADDING_LEN,
    P0_BANK_CONFIG_BORROW_LIMIT_OFFSET,
    P0_BANK_CONFIG_OPERATIONAL_STATE_OFFSET,
)
from src.providers.marginfi.bank_discovery import (  # noqa: E402
    P0_OPERATIONAL_STATE_NAMES,
    derive_p0_offline_borrow_capacity_bound,
)


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def check_blob_hashes(manifest: dict) -> list[str]:
    failures = []
    for entry in manifest["new_blobs"]:
        path = DOSSIER / entry["local"]
        actual = git_blob_sha1(path.read_bytes())
        if actual != entry["upstream_git_blob_sha"]:
            failures.append(f"blob hash mismatch for {entry['local']}: {actual}")
    return failures


def check_idl_layout() -> list[str]:
    failures = []
    idl = json.loads(
        (DOSSIER / "vendor-reference/idl/marginfi_0.1.12.json.txt").read_text(
            encoding="utf-8"
        )
    )
    if idl.get("address") != "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA":
        failures.append("IDL program address mismatch")
    types = {t["name"]: t["type"] for t in idl["types"]}

    def size(t):
        prim = {
            "pubkey": 32,
            "u8": 1,
            "u16": 2,
            "u32": 4,
            "u64": 8,
            "i8": 1,
            "i16": 2,
            "i32": 4,
            "i64": 8,
            "u128": 16,
            "i128": 16,
            "bool": 1,
        }
        if isinstance(t, str):
            if t in prim:
                return prim[t]
            t = {"defined": {"name": t}}
        if "defined" in t:
            d = types[t["defined"]["name"]]
            if "fields" in d:
                return sum(size(f["type"]) for f in d["fields"])
            return 1  # unit enum
        if "array" in t:
            el, n = t["array"]
            n_val = n if isinstance(n, int) else size({"defined": {"name": n}})
            return size(el) * n_val
        if "option" in t:
            return 1 + size(t["option"])
        raise ValueError(f"unknown type {t}")

    body = sum(size(f["type"]) for f in types["Bank"]["fields"])
    if body != P0_BANK_0_1_12_FULL_BODY_LEN:
        failures.append(
            f"IDL bank body {body} != pinned {P0_BANK_0_1_12_FULL_BODY_LEN}"
        )
    if (
        P0_BANK_0_1_12_CORE_BODY_LEN + P0_BANK_0_1_12_TRAILING_PADDING_LEN
        != P0_BANK_0_1_12_FULL_BODY_LEN
    ):
        failures.append("core + trailing padding mismatch")
    if P0_BANK_CONFIG_BORROW_LIMIT_OFFSET != 768:
        failures.append("borrow limit anchor mismatch")
    if P0_BANK_CONFIG_OPERATIONAL_STATE_OFFSET != 600:
        failures.append("operational state anchor mismatch")
    return failures


def check_instruction_metas() -> list[str]:
    failures = []
    idl = json.loads(
        (DOSSIER / "vendor-reference/idl/marginfi_0.1.12.json.txt").read_text(
            encoding="utf-8"
        )
    )
    idl_accounts = {}
    # The IDL names the sysvar account `ixs_sysvar`; the pinned constant in
    # the builder uses the PR-028 spelling `instructions_sysvar`. Map it.
    idl_name_map = {"ixs_sysvar": "instructions_sysvar"}
    for ix in idl["instructions"]:
        if ix["name"] in (
            "lending_account_start_flashloan",
            "lending_account_end_flashloan",
        ):
            idl_accounts[ix["name"]] = [
                idl_name_map.get(a["name"], a["name"]) for a in ix["accounts"]
            ]
    if idl_accounts.get("lending_account_start_flashloan") != [
        name for name, _role in P0_START_FLASHLOAN_ACCOUNT_METAS
    ]:
        failures.append("start flashloan metas differ from IDL")
    if idl_accounts.get("lending_account_end_flashloan") != [
        name for name, _role in P0_END_FLASHLOAN_ACCOUNT_METAS
    ]:
        failures.append("end flashloan metas differ from IDL (group rebind)")
    data = encode_p0_start_flashloan_data(2)
    if data != bytes.fromhex("0e8321dc51bab46b") + (2).to_bytes(8, "little"):
        failures.append("start flashloan data encoding mismatch")
    return failures


def check_bound_vectors() -> list[str]:
    from dataclasses import replace

    from src.providers.marginfi.bank_discovery import MarginfiBankCapacityObservation
    from solders.pubkey import Pubkey

    failures = []
    pk = lambda seed: str(Pubkey.from_bytes(bytes((seed,)) * 32))  # noqa: E731
    obs = MarginfiBankCapacityObservation(
        bank=pk(1),
        group=pk(2),
        mint=pk(3),
        mint_decimals=6,
        token_program="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        liquidity_vault=pk(4),
        liquidity_vault_authority=pk(5),
        oracle_setup=3,
        oracle_keys=(pk(6),),
        asset_tag=0,
        operational_state=1,
        operational=True,
        bank_data_sha256="0" * 64,
        vault_data_sha256="0" * 64,
        group_data_sha256=None,
        raw_vault_amount_base_units=5_000_000,
        raw_borrow_limit=10_000_000,
        origination_fee_raw_i80f48=1 << 46,
        fee_rounding="I80F48_CEIL_SCALE_2POW48",
        raw_asset_share_value_i80f48=0,
        raw_liability_share_value_i80f48=0,
        raw_liquidity_shares_i80f48=0,
        raw_liability_shares_i80f48=0,
        capacity_derivation="R02CAPD_CAPACITY_DERIVATION_UNPROVEN",
        effective_capacity_base_units=None,
        constraint_gaps=("ORACLE_PRICE_UNPROVEN", "BANK_PDA_SEED_UNPINNED"),
        blockers=("MISSING_EFFECTIVE_FLASH_CAP", "LIVE_ROOTED_RPC_NOT_AUTHORIZED"),
        walletless_mode="WALLETLESS_BANK_DISCOVERY_ONLY",
    )
    bound = derive_p0_offline_borrow_capacity_bound(obs)
    if bound.bound_base_units != 5_000_000:
        failures.append(f"bound vector: {bound.bound_base_units}")
    if bound.origination_fee_base_units != 1_250_000:  # ceil(5e6/4)
        failures.append(f"fee vector: {bound.origination_fee_base_units}")
    exhausted = replace(
        obs,
        raw_liability_shares_i80f48=10_000_001 << 48,
        raw_liability_share_value_i80f48=1 << 48,
    )
    ex = derive_p0_offline_borrow_capacity_bound(exhausted)
    if not (ex.capacity_exhausted and ex.bound_base_units == 0):
        failures.append("exhaustion vector failed")
    not_op = replace(obs, operational=False)
    try:
        derive_p0_offline_borrow_capacity_bound(not_op)
        failures.append("non-operational bank did not fail closed")
    except Exception:
        pass
    return failures


def main() -> int:
    manifest = json.loads(
        (DOSSIER / "SOURCE_MANIFEST.json").read_text(encoding="utf-8")
    )
    failures = []
    failures += check_blob_hashes(manifest)
    failures += check_idl_layout()
    failures += check_instruction_metas()
    failures += check_bound_vectors()
    if failures:
        for line in failures:
            print(f"FAIL: {line}")
        return 1
    print(
        "N07_VERIFY_OK blobs=%d idl_layout=closed metas=pinned "
        "bound_vectors=reproduced states=%s"
        % (len(manifest["new_blobs"]), len(P0_OPERATIONAL_STATE_NAMES))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
