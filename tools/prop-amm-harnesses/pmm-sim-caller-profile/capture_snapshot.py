#!/usr/bin/env python
"""One-time user-authorized read-only snapshot capture for the pmm-sim caller-profile slice.

Captures (READ-ONLY, no subscriptions, no signing, no sending, credential-free public RPC):
  - the deployed HumidiFi program executable account + its program-data account,
  - the deployed Magnus router executable account + program-data (for binary provenance),
  - all HumidiFi market / token-account / mint accounts listed in the pinned market manifest.

Writes an immutable snapshot directory:
  snapshot/<slot>/accounts/<pubkey>.json   ({"pubkey","data_base64","executable","lamports","owner","rent_epoch"})
  snapshot/<slot>/SNAPSHOT_MANIFEST.json   (endpoint, slot, timestamps, digests, method list)

This is CAPTURE_ONLY evidence: never PAPER_QUALIFIED, never live, valid only at the captured slot.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

# Pinned via docs/integrations/offline/humidifi-venue-2026-11-21/SOURCE_MANIFEST.json
HUMIDIFI_PROGRAM_ID = "9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp"
MAGNUS_ROUTER_ID = "F9Z9WiieTtL4giMt3eBFEsB5vmAFotLz37FWC7NcbzpT"

MARKETS = [
    # (swap_version, pair, market, base_ta, quote_ta, add1, vote)
    (
        "v1",
        "WSOL-USDC",
        "FksffEqnBRixYGR791Qw2MgdU7zNCpHVFYBL4Fa4qVuH",
        "C3FzbX9n1YD2dow2dCmEv5uNyyf22Gb3TLAEqGBhw5fY",
        "3RWFAQBRkNGq7CMGcTLK3kXDgFTe9jgMeFYqk8nHwcWh",
        None,
        None,
    ),
    (
        "v1",
        "WSOL-USDC",
        "DB3sUCP2H4icbeKmK6yb6nUxU5ogbcRHtGuq7W2RoRwW",
        "8BrVfsvzb1DZqCactbYWoKSv24AfsLBuXJqzpzYCwznF",
        "HsQcHFFNUVTp3MWrXYbuZchBNd4Pwk8636bKzLvpfYNR",
        None,
        None,
    ),
    (
        "v1",
        "WSOL-USDC",
        "6n9VhCwQ7EwK6NqFDjnHPzEk6wZdRBTfh43RFgHQWHuQ",
        "Cv9St5tDTGwpbG5UVvM6QvFmf3FYSXc14W9BYvQN5wAZ",
        "7Rf8Gu8YemSoGjZT3z1cL5BT9HLbGywcyaz8Mrbhd1MH",
        None,
        None,
    ),
    (
        "v1",
        "WSOL-USDC",
        "AvGeFw71N5sNfV97mZ1uNrHg4yfufRicCJUrS9j2ehTX",
        "ECEPWwZJ1U1Vjsj1X5sUbZYETKMSCjYHuoTMVitCn64t",
        "FBWtVVvzsRuAAzVX8ua1hden9KmgPrC2rFijuwEn1ngJ",
        None,
        None,
    ),
    (
        "v1",
        "WSOL-USDC",
        "5dhYayH9qvzNyCPoh2hKN8TJqumoGsWdyZ9UfPLXBfD9",
        "86DHdQfRpghMCmXYKDg93bXtmi3doBL5NeY9DYwAj6rz",
        "FqEVwrQJsJ4AciwJRYLPQEdstDfUYJp6z3f6XYb6MnSb",
        None,
        None,
    ),
    (
        "v2",
        "WSOL-USDC",
        "FksffEqnBRixYGR791Qw2MgdU7zNCpHVFYBL4Fa4qVuH",
        "C3FzbX9n1YD2dow2dCmEv5uNyyf22Gb3TLAEqGBhw5fY",
        "3RWFAQBRkNGq7CMGcTLK3kXDgFTe9jgMeFYqk8nHwcWh",
        "4nXmcNY1NjNd9sjA3qajUdUYpVDvwxTzGZT9oS4KpaD1",
        "J1to1yufRnoWn81KYg1XkTWzmKjnYSnmE2VY8DGUJ9Qv",
    ),
    (
        "v2",
        "WSOL-USDC",
        "DB3sUCP2H4icbeKmK6yb6nUxU5ogbcRHtGuq7W2RoRwW",
        "8BrVfsvzb1DZqCactbYWoKSv24AfsLBuXJqzpzYCwznF",
        "HsQcHFFNUVTp3MWrXYbuZchBNd4Pwk8636bKzLvpfYNR",
        None,
        None,
    ),
    (
        "v2",
        "WSOL-USDC",
        "6n9VhCwQ7EwK6NqFDjnHPzEk6wZdRBTfh43RFgHQWHuQ",
        "Cv9St5tDTGwpbG5UVvM6QvFmf3FYSXc14W9BYvQN5wAZ",
        "7Rf8Gu8YemSoGjZT3z1cL5BT9HLbGywcyaz8Mrbhd1MH",
        None,
        None,
    ),
    (
        "v2",
        "WSOL-USDC",
        "AvGeFw71N5sNfV97mZ1uNrHg4yfufRicCJUrS9j2ehTX",
        "ECEPWwZJ1U1Vjsj1X5sUbZYETKMSCjYHuoTMVitCn64t",
        "FBWtVVvzsRuAAzVX8ua1hden9KmgPrC2rFijuwEn1ngJ",
        None,
        None,
    ),
    (
        "v2",
        "WSOL-USD1",
        "5dhYayH9qvzNyCPoh2hKN8TJqumoGsWdyZ9UfPLXBfD9",
        "86DHdQfRpghMCmXYKDg93bXtmi3doBL5NeY9DYwAj6rz",
        "FqEVwrQJsJ4AciwJRYLPQEdstDfUYJp6z3f6XYb6MnSb",
        None,
        None,
    ),
    (
        "v3",
        "WSOL-USDC",
        "FksffEqnBRixYGR791Qw2MgdU7zNCpHVFYBL4Fa4qVuH",
        "C3FzbX9n1YD2dow2dCmEv5uNyyf22Gb3TLAEqGBhw5fY",
        "3RWFAQBRkNGq7CMGcTLK3kXDgFTe9jgMeFYqk8nHwcWh",
        "4nXmcNY1NjNd9sjA3qajUdUYpVDvwxTzGZT9oS4KpaD1",
        "J1to1yufRnoWn81KYg1XkTWzmKjnYSnmE2VY8DGUJ9Qv",
    ),
    (
        "v3",
        "WSOL-USDC",
        "DB3sUCP2H4icbeKmK6yb6nUxU5ogbcRHtGuq7W2RoRwW",
        "8BrVfsvzb1DZqCactbYWoKSv24AfsLBuXJqzpzYCwznF",
        "HsQcHFFNUVTp3MWrXYbuZchBNd4Pwk8636bKzLvpfYNR",
        "4nXmcNY1NjNd9sjA3qajUdUYpVDvwxTzGZT9oS4KpaD1",
        "J1to1yufRnoWn81KYg1XkTWzmKjnYSnmE2VY8DGUJ9Qv",
    ),
    (
        "v3",
        "WSOL-USDC",
        "6n9VhCwQ7EwK6NqFDjnHPzEk6wZdRBTfh43RFgHQWHuQ",
        "Cv9St5tDTGwpbG5UVvM6QvFmf3FYSXc14W9BYvQN5wAZ",
        "7Rf8Gu8YemSoGjZT3z1cL5BT9HLbGywcyaz8Mrbhd1MH",
        "4nXmcNY1NjNd9sjA3qajUdUYpVDvwxTzGZT9oS4KpaD1",
        "J1to1yufRnoWn81KYg1XkTWzmKjnYSnmE2VY8DGUJ9Qv",
    ),
    (
        "v3",
        "WSOL-USDC",
        "AvGeFw71N5sNfV97mZ1uNrHg4yfufRicCJUrS9j2ehTX",
        "ECEPWwZJ1U1Vjsj1X5sUbZYETKMSCjYHuoTMVitCn64t",
        "FBWtVVvzsRuAAzVX8ua1hden9KmgPrC2rFijuwEn1ngJ",
        "4nXmcNY1NjNd9sjA3qajUdUYpVDvwxTzGZT9oS4KpaD1",
        "J1to1yufRnoWn81KYg1XkTWzmKjnYSnmE2VY8DGUJ9Qv",
    ),
    (
        "v3",
        "WSOL-USD1",
        "5dhYayH9qvzNyCPoh2hKN8TJqumoGsWdyZ9UfPLXBfD9",
        "86DHdQfRpghMCmXYKDg93bXtmi3doBL5NeY9DYwAj6rz",
        "FqEVwrQJsJ4AciwJRYLPQEdstDfUYJp6z3f6XYb6MnSb",
        "4nXmcNY1NjNd9sjA3qajUdUYpVDvwxTzGZT9oS4KpaD1",
        "J1to1yufRnoWn81KYg1XkTWzmKjnYSnmE2VY8DGUJ9Qv",
    ),
]

MINTS = [
    "So11111111111111111111111111111111111111112",  # WSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB",  # USD1
]

BPF_LOADER_PROGRAM = "BPFLoaderUpgradeab1e11111111111111111111111"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


def rpc(url: str, method: str, params: list) -> dict:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        out = json.load(resp)
    if "error" in out:
        raise RuntimeError(f"RPC error for {method}: {out['error']}")
    return out["result"]


def program_data_address_from_chain(url: str, program_id: str) -> str | None:
    """Read the program-data address from the loader-v3 program account data (bytes 4..36)."""
    res = rpc(url, "getAccountInfo", [program_id, {"encoding": "base64"}])
    val = res["value"]
    if val is None:
        return None
    import base64 as _b64

    data = _b64.b64decode(val["data"][0])
    if val["owner"] != BPF_LOADER_PROGRAM or len(data) < 36:
        raise RuntimeError(
            f"program {program_id} is not a loader-v3 executable account (owner={val['owner']})"
        )
    import solders.pubkey as spk

    return str(spk.Pubkey.from_bytes(data[4:36]))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc-url", default="https://api.mainnet-beta.solana.com")
    ap.add_argument(
        "--out-root", required=True, help="research/pmm-sim-caller-profile/snapshot"
    )
    args = ap.parse_args()

    out_root = Path(args.out_root)
    slot_res = rpc(args.rpc_url, "getSlot", [{"commitment": "confirmed"}])
    slot = int(slot_res)
    out_dir = out_root / str(slot)
    accounts_dir = out_dir / "accounts"
    accounts_dir.mkdir(parents=True, exist_ok=True)

    optional_pubkeys = [
        MAGNUS_ROUTER_ID,
        program_data_address_from_chain(args.rpc_url, MAGNUS_ROUTER_ID),
    ]
    optional_pubkeys = [p for p in optional_pubkeys if p]
    humidifi_program_data = program_data_address_from_chain(
        args.rpc_url, HUMIDIFI_PROGRAM_ID
    )
    pubkeys = [HUMIDIFI_PROGRAM_ID, humidifi_program_data] + optional_pubkeys
    for _v, _p, market, base_ta, quote_ta, add1, vote in MARKETS:
        pubkeys += [market, base_ta, quote_ta]
        if add1:
            pubkeys.append(add1)
        if vote:
            pubkeys.append(vote)
    pubkeys += MINTS
    seen: set[str] = set()
    pubkeys = [p for p in pubkeys if not (p in seen or seen.add(p))]

    fetched: dict[str, dict] = {}
    not_found: list[str] = []
    BATCH = 100
    for i in range(0, len(pubkeys), BATCH):
        batch = pubkeys[i : i + BATCH]
        res = rpc(
            args.rpc_url,
            "getMultipleAccounts",
            [batch, {"encoding": "base64", "commitment": "confirmed"}],
        )
        for pk, val in zip(batch, res["value"]):
            if val is None:
                # Required venue accounts are asserted below; optional router accounts are recorded as UNKNOWN.
                not_found.append(pk)
                continue
            fetched[pk] = {
                "pubkey": pk,
                "data_base64": val["data"][0],
                "encoding": val["data"][1],
                "lamports": val["lamports"],
                "owner": val["owner"],
                "executable": val.get("executable", False),
                "rent_epoch": val.get("rentEpoch"),
            }

    # owner assertions
    required = [HUMIDIFI_PROGRAM_ID]
    for _v, _p, market, base_ta, quote_ta, add1, vote in MARKETS:
        # add1/vote are upstream-setup CPI helper accounts that may be legitimately absent
        # (some upstream v2 rows even use the 111..1 placeholder); markets, token accounts and
        # mints are required — unknown is not zero.
        required += [market, base_ta, quote_ta]
    required += MINTS
    missing_required = [pk for pk in dict.fromkeys(required) if pk not in fetched]
    if missing_required:
        for pk in missing_required:
            print(
                f"REQUIRED_ACCOUNT_NOT_FOUND: {pk} — refusing to continue (unknown is not zero)",
                file=sys.stderr,
            )
        return 3
    problems = []
    if (
        fetched[HUMIDIFI_PROGRAM_ID]["owner"] != BPF_LOADER_PROGRAM
        or not fetched[HUMIDIFI_PROGRAM_ID]["executable"]
    ):
        problems.append(
            "HumidiFi program account is not an executable BPFLoaderUpgradeab1e account"
        )
    for _v, _p, market, base_ta, quote_ta, _a1, _v1 in MARKETS:
        if fetched[market]["owner"] != HUMIDIFI_PROGRAM_ID:
            problems.append(
                f"market {market} owner {fetched[market]['owner']} != HumidiFi program"
            )
        for ta in (base_ta, quote_ta):
            if fetched[ta]["owner"] != TOKEN_PROGRAM:
                problems.append(
                    f"token account {ta} owner {fetched[ta]['owner']} != SPL Token program"
                )
    if problems:
        for p in problems:
            print(f"OWNER_ASSERTION_FAILED: {p}", file=sys.stderr)
        (out_dir / "OWNER_ASSERTION_FAILURES.txt").write_text(
            "\n".join(problems) + "\n", encoding="utf-8"
        )
        return 2

    for pk, rec in fetched.items():
        (accounts_dir / f"{pk}.json").write_text(
            json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )

    account_files = sorted(accounts_dir.glob("*.json"))
    per_account = {p.stem: sha256_file(p) for p in account_files}
    whole = hashlib.sha256()
    for p in account_files:
        whole.update(p.name.encode())
        whole.update(sha256_file(p).encode())
    program_bytes_path = accounts_dir / f"{HUMIDIFI_PROGRAM_ID}.json"
    manifest = {
        "schema": "studious-pancake.pmm-sim-snapshot.v1",
        "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "endpoint_class": "public_credential_free_read_only_rpc",
        "endpoint_url": args.rpc_url,
        "commitment": "confirmed",
        "slot": slot,
        "methods_used": ["getSlot", "getMultipleAccounts"],
        "subscriptions": "NONE",
        "signing_sending": "NONE",
        "account_count": len(account_files),
        "per_account_sha256": per_account,
        "whole_snapshot_digest": whole.hexdigest(),
        "humidifi_program_id": HUMIDIFI_PROGRAM_ID,
        "humidifi_program_data_address": humidifi_program_data,
        "humidifi_program_bytes_sha256": hashlib.sha256(
            base64.b64decode(fetched[HUMIDIFI_PROGRAM_ID]["data_base64"])
        ).hexdigest(),
        "magnus_router_id": MAGNUS_ROUTER_ID,
        "magnus_router_deployed_state": (
            {
                "bytes_sha256": hashlib.sha256(
                    base64.b64decode(fetched[MAGNUS_ROUTER_ID]["data_base64"])
                ).hexdigest()
            }
            if MAGNUS_ROUTER_ID in fetched
            else "NOT_FOUND_ON_MAINNET_AT_PINNED_ID (UNKNOWN, honestly recorded; MAGNUS_NATIVE rows stay SYNTHETIC_SIMULATION_BY_DEFAULT)"
        ),
        "accounts_not_found_optional": not_found,
        "owner_assertions": "PASS",
        "snapshot_status": "RAW_ACCOUNT_CAPTURE_ONLY — never PAPER_QUALIFIED, never live",
    }
    (out_dir / "SNAPSHOT_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"OK slot={slot} accounts={len(account_files)} digest={manifest['whole_snapshot_digest']}"
    )
    print(f"humidifi_program_bytes_sha256={manifest['humidifi_program_bytes_sha256']}")
    print(f"magnus_router_deployed_state={manifest['magnus_router_deployed_state']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
