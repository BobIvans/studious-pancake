#!/usr/bin/env python3
"""Verify the offline Kamino flash-builder dossier bundle without network access.

Re-derives the pinned instruction ABI directly from the vendored codegen text
(the authoritative bytes) and cross-checks it against the manifest and against
the values encoded in ``src/lending/unsigned_builders/kamino_builder.py``.
Offline: file reads + ``git hash-object`` only.
"""

from __future__ import annotations

import json
import re
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BASE = Path("docs/integrations/offline/kamino-flash-builder-2026-11-14")
MANIFEST = ROOT / BASE / "SOURCE_MANIFEST.json"
VENDOR_DIR = ROOT / BASE / "vendor-reference" / "klend"
BUILDER = ROOT / "src" / "lending" / "unsigned_builders" / "kamino_builder.py"


def git_blob_sha1(path: Path) -> str:
    result = subprocess.run(
        ["git", "hash-object", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def discriminator_from_source(text: str, label: str) -> bytes:
    match = re.search(
        r"export const DISCRIMINATOR = Buffer\.from\(\[([0-9,\s]+)\]\)", text
    )
    if match is None:
        raise SystemExit(f"FATAL: no DISCRIMINATOR line found in {label}")
    return bytes(int(part.strip()) for part in match.group(1).split(","))


def args_from_source(text: str, label: str) -> list[str]:
    block = re.search(
        r"export const layout = borsh\.struct<[^>]+>\(\[(.*?)\]\)", text, re.S
    )
    if block is None:
        raise SystemExit(f"FATAL: no borsh layout found in {label}")
    return re.findall(r'borsh\.(u64|u8)\("([a-zA-Z]+)"\)', block.group(1))


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors: list[str] = []
    print(f"PIN repo={manifest['upstream_repository']}")
    print(f"PIN commit={manifest['upstream_commit_sha']}")
    print(
        f"PIN version={manifest['package_version']} license={manifest['license_label']}"
    )
    print(f"PIN retrieved_at={manifest['retrieved_at']}")

    discs: dict[str, bytes] = {}
    arg_orders: dict[str, list[str]] = {}
    for entry in manifest["entries"]:
        local = ROOT / BASE / entry["local_path"]
        if not local.is_file():
            errors.append(f"MISSING:{entry['local_path']}")
            continue
        actual = git_blob_sha1(local)
        expected = entry["upstream_git_blob_sha"]
        byte_len = local.stat().st_size
        if actual != expected:
            errors.append(
                f"GIT_BLOB_MISMATCH:{entry['local_path']} "
                f"expected={expected} actual={actual}"
            )
        elif byte_len != entry["bytes"]:
            errors.append(
                f"BYTE_COUNT_MISMATCH:{entry['local_path']} "
                f"manifest={entry['bytes']} actual={byte_len}"
            )
        else:
            print(f"OK_GIT_BLOB {entry['local_path']}={actual} bytes={byte_len}")
        text = local.read_text(encoding="utf-8")
        stem = local.name.removesuffix(".ts.txt")
        if stem in ("flashBorrowReserveLiquidity", "flashRepayReserveLiquidity"):
            discs[stem] = discriminator_from_source(text, stem)
            arg_orders[stem] = [name for _kind, name in args_from_source(text, stem)]

    if discs.get("flashBorrowReserveLiquidity") != bytes.fromhex("87e734a70734d4c1"):
        errors.append(
            "BORROW_DISCRIMINATOR_MISMATCH "
            f"actual={discs.get('flashBorrowReserveLiquidity', b'').hex()}"
        )
    if discs.get("flashRepayReserveLiquidity") != bytes.fromhex("b97500cb60f5b4ba"):
        errors.append(
            "REPAY_DISCRIMINATOR_MISMATCH "
            f"actual={discs.get('flashRepayReserveLiquidity', b'').hex()}"
        )
    if arg_orders.get("flashBorrowReserveLiquidity") != ["liquidityAmount"]:
        errors.append(
            f"BORROW_ARGS_MISMATCH={arg_orders.get('flashBorrowReserveLiquidity')}"
        )
    if arg_orders.get("flashRepayReserveLiquidity") != [
        "liquidityAmount",
        "borrowInstructionIndex",
    ]:
        errors.append(
            f"REPAY_ARGS_MISMATCH={arg_orders.get('flashRepayReserveLiquidity')}"
        )

    program_text = (VENDOR_DIR / "programId.ts.txt").read_text(encoding="utf-8")
    program_match = re.search(r'address\(\s*"([^"]+)"\s*\)', program_text)
    if program_match is None:
        errors.append("PROGRAM_ID_NOT_FOUND_IN_PINNED_SOURCE")
    else:
        pinned_program = program_match.group(1)
        builder_text = BUILDER.read_text(encoding="utf-8")
        if f'KAMINO_KLEND_PROGRAM_ID = "{pinned_program}"' not in builder_text:
            errors.append(f"BUILDER_PROGRAM_ID_MISMATCH expected={pinned_program}")
        else:
            print(f"OK_PROGRAM_ID {pinned_program}")

    builder_text = BUILDER.read_text(encoding="utf-8")
    if discs:
        for name, expected in (
            ("KAMINO_FLASH_BORROW_DISCRIMINATOR", discs["flashBorrowReserveLiquidity"]),
            ("KAMINO_FLASH_REPAY_DISCRIMINATOR", discs["flashRepayReserveLiquidity"]),
        ):
            tuple_literal = ", ".join(str(byte) for byte in expected)
            if f"bytes(({tuple_literal}))" not in builder_text:
                errors.append(f"BUILDER_DISCRIMINATOR_MISMATCH {name}={expected.hex()}")
            else:
                print(f"OK_BUILDER_DISCRIMINATOR {name}={expected.hex()}")
        golden_vectors = (
            ROOT / "tests" / "fixtures" / "r03" / "kamino_flash_abi_golden.json"
        )
        if golden_vectors.is_file():
            vectors = json.loads(golden_vectors.read_text(encoding="utf-8"))
            amount = int(vectors["liquidity_amount"])
            borrow_expected = discs["flashBorrowReserveLiquidity"] + struct.pack(
                "<Q", amount
            )
            repay_expected = discs["flashRepayReserveLiquidity"] + struct.pack(
                "<QB", amount, int(vectors["repay_borrow_instruction_index"])
            )
            if vectors.get("borrow_data_hex") != borrow_expected.hex():
                errors.append(
                    "GOLDEN_BORROW_DATA_MISMATCH vs vendored codegen re-encode"
                )
            if vectors.get("repay_data_hex") != repay_expected.hex():
                errors.append(
                    "GOLDEN_REPAY_DATA_MISMATCH vs vendored codegen re-encode"
                )
            if not errors:
                print(
                    "OK_GOLDEN_VECTORS borrow/repay data re-encoded from vendored text"
                )

    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print("KAMINO_FLASH_BUILDER_OFFLINE_REFERENCE_INTEGRITY_PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
