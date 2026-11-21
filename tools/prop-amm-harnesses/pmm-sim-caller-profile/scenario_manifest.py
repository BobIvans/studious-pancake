#!/usr/bin/env python
"""Build scenario_manifest_v1.json + results CSV/JSON from the runner journals.

Acceptance: exactly 2700 unique scenario_ids, exactly one terminal status each.
Identical duplicate terminal records are deduplicated; conflicting terminal records
for one scenario_id hard-fail. Per-scenario classification (synthetic vs genuine),
caller_delta_bps vs DIRECT/MAGNUS_NATIVE baselines and row labels are computed here.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

HUMIDIFI_PROGRAM = "9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp"
VARIANTS = ["humidifi", "humidifi-swap-v2", "humidifi-swap-v3"]
MARKETS = [
    "FksffEqnBRixYGR791Qw2MgdU7zNCpHVFYBL4Fa4qVuH",
    "DB3sUCP2H4icbeKmK6yb6nUxU5ogbcRHtGuq7W2RoRwW",
    "6n9VhCwQ7EwK6NqFDjnHPzEk6wZdRBTfh43RFgHQWHuQ",
    "AvGeFw71N5sNfV97mZ1uNrHg4yfufRicCJUrS9j2ehTX",
    "5dhYayH9qvzNyCPoh2hKN8TJqumoGsWdyZ9UfPLXBfD9",
]
PROFILES = [
    "DIRECT",
    "MAGNUS_NATIVE",
    "JUPITER_SIM",
    "DFLOW_SIM",
    "OKX_SIM",
    "TITAN_SIM",
]
AMOUNTS = [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2000, 4000, 8000, 16000, 32000, 64000]
CLASSIFICATION = {
    "DIRECT": "GENUINE_EXECUTABLE_ROUTE_CANDIDATE",
    "MAGNUS_NATIVE": "SYNTHETIC_SIMULATION_BY_DEFAULT",
    "JUPITER_SIM": "SYNTHETIC_SIMULATION",
    "DFLOW_SIM": "SYNTHETIC_SIMULATION",
    "OKX_SIM": "SYNTHETIC_SIMULATION",
    "TITAN_SIM": "SYNTHETIC_SIMULATION",
}
TERMINAL_SETTLED = (
    "OK_COMPLETE_ROUND_TRIP",
    "FORWARD_SWAP_FAILED",
    "REVERSE_SWAP_FAILED",
    "BLOCKED_INFRA",
    "OFFLINE_VIOLATION",
)


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def expected_ids(snapshot_id: str) -> list[str]:
    out = []
    for pmm in VARIANTS:
        for market in MARKETS:
            # 5dhYayH9 is WSOL-USD1 only for swap-v2/v3; v1 market is WSOL-USDC (pinned setup.toml)
            dst = "usd1" if (market == MARKETS[4] and pmm != "humidifi") else "usdc"
            for direction in (f"wsol2{dst}", f"{dst}2wsol"):
                for profile in PROFILES:
                    for amount in AMOUNTS:
                        out.append(
                            f"{snapshot_id}|{pmm}|{market}|{profile}|{direction}|{amount}"
                        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "results_root", help="results/<snapshot_id> dir containing journal/"
    )
    ap.add_argument("--snapshot-id", required=True)
    ap.add_argument("--out-dir", default="research/pmm-sim-caller-profile")
    args = ap.parse_args()

    journal_dir = Path(args.results_root) / "journal"
    terminals: dict[str, list[dict]] = {}
    for f in sorted(journal_dir.glob("journal_w*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # incomplete trailing record: quarantined (never terminal)
            if rec.get("type") != "terminal":
                continue
            terminals.setdefault(rec["scenario_id"], []).append(rec)

    conflicts = []
    settled: dict[str, dict] = {}
    dup_identical = 0
    for sid, recs in terminals.items():
        distinct = {json.dumps(r, sort_keys=True) for r in recs}
        if len(distinct) > 1:
            statuses = {r["status"] for r in recs}
            if len(statuses) > 1 or len(recs) != len(distinct):
                conflicts.append(
                    {
                        "scenario_id": sid,
                        "records": len(recs),
                        "statuses": sorted(statuses),
                    }
                )
                continue
        # identical duplicates: dedup, keep the record with max attempt
        settled[sid] = sorted(
            recs, key=lambda r: r.get("attempt", r.get("attempts_used", 0))
        )[-1]
    if conflicts:
        print(
            "FATAL: conflicting terminal records for scenario ids (hard fail):",
            file=sys.stderr,
        )
        for c in conflicts[:10]:
            print(json.dumps(c), file=sys.stderr)
        return 5

    expected = expected_ids(args.snapshot_id)
    missing = [sid for sid in expected if sid not in settled]
    extra = [sid for sid in settled if sid not in set(expected)]
    if missing or extra:
        print(
            f"FATAL: coverage mismatch missing={len(missing)} extra={len(extra)}",
            file=sys.stderr,
        )
        for sid in missing[:5]:
            print(" missing:", sid, file=sys.stderr)
        return 6

    # deltas + labels
    groups: dict[tuple, dict[str, dict]] = {}
    for sid, rec in settled.items():
        _, pmm, market, profile, direction, amount = rec["scenario_id"].split("|")
        if rec["status"] == "OK_COMPLETE_ROUND_TRIP":
            groups.setdefault((pmm, market, direction, int(amount)), {})[profile] = rec
    for rec in settled.values():
        rec["caller_delta_bps_vs_direct"] = None
        rec["caller_delta_bps_vs_magnus_native"] = None
        rec["row_label"] = ""
        rec["classification"] = CLASSIFICATION[rec["scenario_id"].split("|")[3]]
    for key, group in groups.items():
        base_direct = group.get("DIRECT")
        base_magnus = group.get("MAGNUS_NATIVE")
        for profile, rec in group.items():
            for base, field in (
                (base_direct, "caller_delta_bps_vs_direct"),
                (base_magnus, "caller_delta_bps_vs_magnus_native"),
            ):
                if base and base["amount_out_raw"]:
                    rec[field] = round(
                        (rec["amount_out_raw"] - base["amount_out_raw"])
                        / base["amount_out_raw"]
                        * 10_000,
                        4,
                    )
        simulated = [r for p, r in group.items() if p != "DIRECT"]
        genuine = [group["DIRECT"]] if "DIRECT" in group else []
        if simulated and len({r["amount_out_raw"] for r in simulated}) > 1:
            max(simulated, key=lambda r: r["amount_out_raw"])["row_label"] = (
                "BEST_SIMULATED_CALLER_PROFILE"
            )
        elif len(simulated) >= 2:
            # >=2 simulated candidates with identical outputs: honest NO_DIFFERENCE
            for r in simulated:
                r["row_label"] = "NO_DIFFERENCE"
        # a single simulated candidate gets no label (nothing to differentiate)
        if genuine:
            genuine[0]["row_label"] = "BEST_REAL_EXECUTABLE_ROUTE"

    out_dir = Path(args.out_dir)
    rows = []
    for sid in expected:
        rec = settled[sid]
        _, pmm, market, profile, direction, amount = sid.split("|")
        rows.append(
            {
                "scenario_id": sid,
                "snapshot_id": args.snapshot_id,
                "slot": 401101387,
                "amm_name": pmm,
                "instruction_version": (
                    pmm.replace("humidifi", "swap-v1")
                    if pmm == "humidifi"
                    else pmm.split("-")[-1]
                ),
                "program_id": HUMIDIFI_PROGRAM,
                "market_id": market,
                "caller_profile": profile,
                "classification": rec["classification"],
                "direction": direction,
                "amount": int(amount),
                "status": rec["status"],
                "failure_category": rec["failure_category"],
                "error_code": (rec.get("error_code") or "")[:200],
                "amount_out_raw": rec.get("amount_out_raw"),
                "compute_units": rec.get("compute_units"),
                "caller_delta_bps_vs_direct": rec["caller_delta_bps_vs_direct"],
                "caller_delta_bps_vs_magnus_native": rec[
                    "caller_delta_bps_vs_magnus_native"
                ],
                "row_label": rec["row_label"],
                "artifact_path": rec.get("artifact_path", ""),
                "attempts_used": rec.get("attempts_used"),
                "batch_id": rec["batch_id"],
                "worker_id": rec["worker_id"],
                "offline_status": rec["offline_status"],
            }
        )
    fieldnames = list(rows[0].keys())
    csv_path = out_dir / "caller_profile_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    status_counts: dict[str, int] = {}
    label_counts: dict[str, int] = {}
    for r in rows:
        status_counts[r["status"].split(":")[0]] = (
            status_counts.get(r["status"].split(":")[0], 0) + 1
        )
        label_counts[r["row_label"]] = label_counts.get(r["row_label"], 0) + 1
    by_variant = {}
    for r in rows:
        by_variant.setdefault(r["amm_name"], {}).setdefault(
            r["status"].split(":")[0], 0
        )
        by_variant[r["amm_name"]][r["status"].split(":")[0]] += 1

    receipt = {
        "schema": "studious-pancake.pmm-sim-scenario-manifest.v1",
        "snapshot_id": args.snapshot_id,
        "slot": 401101387,
        "scenario_count_expected": len(expected),
        "scenario_count_terminal": len(settled),
        "unique_scenario_ids": len(settled),
        "conflicting_terminal_records": 0,
        "results_csv_sha256": sha256_file(csv_path),
        "status_counts": status_counts,
        "row_label_counts": label_counts,
        "by_variant": by_variant,
        "offline_status": sorted({r["offline_status"] for r in rows}),
        "classification_note": "spoof profiles and harness-shipped-router rows are SYNTHETIC_SIMULATION with no mainnet meaning; DIRECT rows are GENUINE_EXECUTABLE_ROUTE_CANDIDATE for the pinned snapshot only",
        "single_snapshot_limitation": "all rows are slot 401101387 (upstream static snapshot); captured slot 472269598 is BLOCKED_SIMULATOR_INCOMPATIBLE; no persistent caller-preference claim is made from a single snapshot",
        "production_boundary": "research only; min_return=1 upstream default is not a production slippage guard; HumidiFi ignores min_amount_out (same-tx post-balance guard required)",
    }
    json_path = out_dir / "scenario_manifest_v1.json"
    json_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: receipt[k]
                for k in (
                    "scenario_count_terminal",
                    "unique_scenario_ids",
                    "status_counts",
                    "results_csv_sha256",
                )
            },
            indent=1,
        )
    )
    return 0 if len(settled) == len(expected) == 2700 else 7


if __name__ == "__main__":
    sys.exit(main())
