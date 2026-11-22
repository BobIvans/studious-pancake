#!/usr/bin/env python
"""Coverage validator for the Gate A validation subset.

Fails (exit != 0) if any required dimension is missing from the subset:
all 6 caller profiles, all 3 instruction variants, both directions per pair,
at least 3 distinct markets, both amount levels, all three version-specific
instruction layouts, and the deterministic expected-failure control.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED_PROFILES = {
    "DIRECT",
    "MAGNUS_NATIVE",
    "JUPITER_SIM",
    "DFLOW_SIM",
    "OKX_SIM",
    "TITAN_SIM",
}
REQUIRED_VARIANTS = {"humidifi", "humidifi-swap-v2", "humidifi-swap-v3"}
REQUIRED_AMOUNTS = {1000, 64000}
MIN_MARKETS = 3
MIN_DIRECTIONS_PER_PAIR = 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("subset")
    args = ap.parse_args()

    data = json.loads(Path(args.subset).read_text(encoding="utf-8"))
    scenarios = [s["scenario_id"] for s in data["scenarios"]]
    parsed = []
    for sid in scenarios:
        parts = sid.split("|")
        if len(parts) != 6:
            print(f"FAIL malformed scenario id: {sid}")
            return 2
        parsed.append(
            {
                "snapshot": parts[0],
                "pmm": parts[1],
                "market": parts[2],
                "profile": parts[3],
                "direction": parts[4],
                "amount": int(parts[5]),
            }
        )

    checks = []
    profiles = {p["profile"] for p in parsed}
    checks.append(("profiles_6", profiles == REQUIRED_PROFILES, f"{sorted(profiles)}"))
    variants = {p["pmm"] for p in parsed}
    checks.append(("variants_3", variants == REQUIRED_VARIANTS, f"{sorted(variants)}"))
    markets = {p["market"] for p in parsed}
    checks.append(("markets>=3", len(markets) >= MIN_MARKETS, f"{len(markets)}"))
    amounts = {p["amount"] for p in parsed}
    checks.append(("amount_levels", REQUIRED_AMOUNTS <= amounts, f"{sorted(amounts)}"))
    dirs_by_pair = {}
    for p in parsed:
        pair = "wsol-usd1" if "usd1" in p["direction"] else "wsol-usdc"
        dirs_by_pair.setdefault(pair, set()).add(p["direction"].split("2")[1])
    pair_dirs_ok = (
        all(len(v) == MIN_DIRECTIONS_PER_PAIR for v in dirs_by_pair.values())
        and len(dirs_by_pair) >= 1
    )
    checks.append(
        (
            "directions_per_pair",
            pair_dirs_ok,
            str({k: sorted(v) for k, v in dirs_by_pair.items()}),
        )
    )
    layouts = {}
    for p in parsed:
        layouts.setdefault(p["pmm"], set()).add(p["market"])
    checks.append(
        (
            "layouts_v1_v2_v3_present",
            all(layouts[v] for v in REQUIRED_VARIANTS),
            str({k: len(v) for k, v in layouts.items()}),
        )
    )
    has_expected_failure = any(
        p["role"] == "expected_failure_control_0x31" for p in data["scenarios"]
    )
    checks.append(("deterministic_expected_failure_control", has_expected_failure, ""))
    checks.append(("subset_size_30_50", 30 <= len(parsed) <= 50, f"{len(parsed)}"))

    ok = all(c[1] for c in checks)
    for name, passed, detail in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {name} {detail}")
    print(f"{sum(1 for c in checks if c[1])}/{len(checks)} coverage checks passed")
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
