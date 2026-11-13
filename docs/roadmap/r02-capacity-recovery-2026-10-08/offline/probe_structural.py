#!/usr/bin/env python3
"""Read-only structural decode of captured Solana accounts; NEVER qualifies capacity."""
from __future__ import annotations
import base64
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

def b58encode(raw: bytes) -> str:
    value = int.from_bytes(raw, "big")
    output = ""
    while value:
        value, mod = divmod(value, 58)
        output = B58[mod] + output
    leading = len(raw) - len(raw.lstrip(b"\0"))
    return "1" * leading + output

def layout(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))

def decode_fields(raw: bytes, schema: dict, *, exact_length: bool) -> dict:
    tag = bytes(schema.get("discriminator", schema.get("reserve_discriminator")))
    if raw[:8] != tag:
        raise ValueError("UNKNOWN_DISCRIMINATOR")
    expected = schema.get("account_size_bytes", schema.get("prefix_len_bytes"))
    if len(raw) < expected or (exact_length and len(raw) != expected):
        raise ValueError("ACCOUNT_SIZE_SCHEMA_MISMATCH")
    result = {}
    for f in schema["fields"] if "fields" in schema else schema["prefix_fields"]:
        ofs, width = f["offset"], f["bytes"]
        buf = raw[ofs:ofs+width]
        if len(buf) != width:
            raise ValueError("TRUNCATED_STRUCT")
        kind = f["type"]
        if kind == "pubkey":
            result[f["name"]] = b58encode(buf)
        elif kind.startswith("u") and kind[1:].isdigit():
            result[f["name"]] = str(int.from_bytes(buf, "little"))
        elif kind.startswith("bytes"):
            result[f["name"]] = buf.hex()
        else:
            raise ValueError("UNKNOWN_FIELD_TYPE")
    return result

def decode_captured_account(account: dict, protocol: str) -> dict:
    schema_file = {"jupiter_lend":"jupiter_token_reserve_layout.json",
                   "kamino":"kamino_reserve_prefix_layout.json"}.get(protocol)
    if schema_file is None:
        raise ValueError("UNSUPPORTED_PROTOCOL")
    meta = layout(schema_file)
    owner = meta["owner_program_id"] if protocol == "jupiter_lend" else meta["official_program_id"]
    if account.get("owner") != owner or account.get("executable") is not False:
        raise ValueError("PROGRAM_OWNER_OR_EXECUTABLE_MISMATCH")
    entry = account.get("data")
    if not isinstance(entry, list) or len(entry)!=2 or entry[1]!="base64":
        raise ValueError("ACCOUNT_ENCODING_MISMATCH")
    try:
        raw=base64.b64decode(entry[0],validate=True)
    except (ValueError,base64.binascii.Error) as exc:
        raise ValueError("INVALID_BASE64") from exc
    structural=decode_fields(raw,meta,exact_length=protocol=="jupiter_lend")
    return {"schema":"r02.structural-observation.v1","protocol":protocol,
        "status":"STRUCTURAL_ONLY_NOT_FLASH_CAPACITY","structural":structural,
        "observed_owner":owner,"raw_length":len(raw),
        "needs_live_reserve_cap_and_quorum":True,"qualified_edges":[],
        "sign_enabled":False,"send_enabled":False,"execution_authority":"NONE"}

if __name__ == "__main__":
    raise SystemExit("Import and call decode_captured_account on captured JSON; no RPC or network supported.")
