#!/usr/bin/env python
"""Hard-fail audit of a runnable pmm-sim snapshot (strict offline qualification).

Rejects (exit != 0) rather than warning on: missing required accounts, mixed slot
generations, wrong account owners, ELF/alias sha mismatch, missing provenance, or
activation flags not all false. Network enforcement is provided at run time by the
batch runner's black-hole listener (see batch_runner.py).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HUMIDIFI_PROGRAM = "9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
MINTS = [
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB",
]
MARKETS = {
    "FksffEqnBRixYGR791Qw2MgdU7zNCpHVFYBL4Fa4qVuH": (
        "C3FzbX9n1YD2dow2dCmEv5uNyyf22Gb3TLAEqGBhw5fY",
        "3RWFAQBRkNGq7CMGcTLK3kXDgFTe9jgMeFYqk8nHwcWh",
    ),
    "DB3sUCP2H4icbeKmK6yb6nUxU5ogbcRHtGuq7W2RoRwW": (
        "8BrVfsvzb1DZqCactbYWoKSv24AfsLBuXJqzpzYCwznF",
        "HsQcHFFNUVTp3MWrXYbuZchBNd4Pwk8636bKzLvpfYNR",
    ),
    "6n9VhCwQ7EwK6NqFDjnHPzEk6wZdRBTfh43RFgHQWHuQ": (
        "Cv9St5tDTGwpbG5UVvM6QvFmf3FYSXc14W9BYvQN5wAZ",
        "7Rf8Gu8YemSoGjZT3z1cL5BT9HLbGywcyaz8Mrbhd1MH",
    ),
    "AvGeFw71N5sNfV97mZ1uNrHg4yfufRicCJUrS9j2ehTX": (
        "ECEPWwZJ1U1Vjsj1X5sUbZYETKMSCjYHuoTMVitCn64t",
        "FBWtVVvzsRuAAzVX8ua1hden9KmgPrC2rFijuwEn1ngJ",
    ),
    "5dhYayH9qvzNyCPoh2hKN8TJqumoGsWdyZ9UfPLXBfD9": (
        "86DHdQfRpghMCmXYKDg93bXtmi3doBL5NeY9DYwAj6rz",
        "FqEVwrQJsJ4AciwJRYLPQEdstDfUYJp6z3f6XYb6MnSb",
    ),
}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "snapshot_cfg",
        help="runnable snapshot cfg dir (contains setup.toml, accounts/, programs/)",
    )
    ap.add_argument("--expect-slot", type=int, default=None)
    args = ap.parse_args()

    cfg = Path(args.snapshot_cfg)
    checks: list[tuple[str, bool, str]] = []

    manifest_path = cfg / "RUNNABLE_SNAPSHOT_MANIFEST.json"
    if not manifest_path.exists():
        print("FATAL: RUNNABLE_SNAPSHOT_MANIFEST.json missing", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    flags = manifest.get("activation_flags", {})
    checks.append(
        (
            "activation_flags_all_false",
            all(v is False for v in flags.values()),
            str(flags),
        )
    )

    programs = cfg / "programs"
    accounts = cfg / "accounts"
    primary = programs / "humidifi.so"
    elf_sha = sha256(primary)
    checks.append(("humidifi_elf_present", primary.exists(), elf_sha))
    manifest_sha = manifest.get("humidifi_program_elf_sha256")
    checks.append(
        (
            "humidifi_elf_provenance_recorded",
            manifest_sha == elf_sha,
            f"{manifest_sha} vs {elf_sha}",
        )
    )
    for alias in ("humidifi-swap-v2.so", "humidifi-swap-v3.so"):
        p = programs / alias
        same = p.exists() and sha256(p) == elf_sha
        checks.append(
            (
                f"alias_{alias}_byte_identical",
                same,
                "" if same else "sha mismatch or missing",
            )
        )
        entry = manifest.get("aliases", {}).get(alias, {})
        checks.append(
            (
                f"alias_{alias}_recorded_candidate",
                entry.get("status") == "candidate",
                str(entry.get("status")),
            )
        )

    for router in (
        "magnus-router.so",
        "magnus-router-spoof-jupiter.so",
        "magnus-router-spoof-dflow.so",
        "magnus-router-spoof-okxlabs.so",
        "magnus-router-spoof-titan.so",
    ):
        checks.append(
            (
                f"router_binary_{router}",
                (programs / router).exists(),
                "local LiteSVM-only harness binary",
            )
        )

    slots = set()
    required_missing = []
    owners_bad = []
    needed = set(MINTS)
    for market, (base_ta, quote_ta) in MARKETS.items():
        needed.add(market)
        needed.add(base_ta)
        needed.add(quote_ta)
    for pk in sorted(needed):
        matches = sorted(accounts.glob(f"*_{pk}.json"))
        if not matches:
            required_missing.append(pk)
            continue
        rec = json.loads(matches[0].read_text(encoding="utf-8"))
        slots.add(rec.get("slot"))
        owner = rec["account"]["owner"]
        if pk in MARKETS and owner != HUMIDIFI_PROGRAM:
            owners_bad.append(f"market {pk} owner {owner}")
        if pk in MINTS or pk in {ta for tas in MARKETS.values() for ta in tas}:
            if pk in MINTS and owner != TOKEN_PROGRAM:
                owners_bad.append(f"mint {pk} owner {owner}")

    checks.append(
        (
            "required_accounts_present",
            not required_missing,
            f"missing={required_missing[:3]}",
        )
    )
    checks.append(("owners_correct", not owners_bad, f"bad={owners_bad[:3]}"))
    non_null_slots = {s for s in slots if s is not None}
    checks.append(
        (
            "single_slot_generation",
            len(non_null_slots) <= 1,
            f"slots={sorted(non_null_slots)}",
        )
    )
    if args.expect_slot is not None:
        checks.append(
            (
                "expected_slot",
                non_null_slots == {args.expect_slot} or not non_null_slots,
                f"expect={args.expect_slot}",
            )
        )

    ok = all(c[1] for c in checks)
    for name, passed, detail in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {name} {detail}")
    print(
        f"{sum(1 for c in checks if c[1])}/{len(checks)} checks passed — snapshot {'VALID' if ok else 'REJECTED'}"
    )
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
