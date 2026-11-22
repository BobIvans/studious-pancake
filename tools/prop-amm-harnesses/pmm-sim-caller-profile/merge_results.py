#!/usr/bin/env python
"""Merge pmm-sim benchmark parquet outputs into per-row caller-profile records.

Research-only evidence builder for PR #665 (pmm-sim caller-profile matrix).
Reads the parquet files written by run_matrix.sh, enriches each row with the
caller profile, snapshot provenance and synthetic-vs-genuine classification,
computes caller_delta_bps vs DIRECT and MAGNUS_NATIVE baselines, and writes
deterministic CSV + JSON receipts with SHA-256 digests.

Never drops failures: rows whose simulator run failed are preserved from
failures.txt as BLOCKED/UNKNOWN records. Unknown results are counted as
neither positive nor negative.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq

PARQUET_NAME = re.compile(
    r"^(?P<slot>\d+)_(?P<via>direct|magnus|jupiter|dflow|okxlabs|titan)_"
    r"(?P<pmm>humidifi|humidifi-swap-v2|humidifi-swap-v3)_"
    r"(?P<market>[1-9A-HJ-NP-Za-km-z]{40,44})_"
    r"(?P<time>\d{8}-\d{6})\.parquet$"
)
PROFILE_BY_VIA = {
    "direct": "DIRECT",
    "magnus": "MAGNUS_NATIVE",
    "jupiter": "JUPITER_SIM",
    "dflow": "DFLOW_SIM",
    "okxlabs": "OKX_SIM",
    "titan": "TITAN_SIM",
}
CLASSIFICATION = {
    "DIRECT": "GENUINE_EXECUTABLE_ROUTE_CANDIDATE",
    "MAGNUS_NATIVE": "SYNTHETIC_SIMULATION_BY_DEFAULT",
    "JUPITER_SIM": "SYNTHETIC_SIMULATION",
    "DFLOW_SIM": "SYNTHETIC_SIMULATION",
    "OKX_SIM": "SYNTHETIC_SIMULATION",
    "TITAN_SIM": "SYNTHETIC_SIMULATION",
}
INSTRUCTION_BY_PMM = {
    "humidifi": "swap-v1",
    "humidifi-swap-v2": "swap-v2",
    "humidifi-swap-v3": "swap-v3",
}
HUMIDIFI_PROGRAM_ID = "9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_rows(results_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for pq_file in sorted(results_dir.glob("*.parquet")):
        m = PARQUET_NAME.match(pq_file.name)
        if not m:
            print(
                f"WARN: unrecognized parquet name skipped: {pq_file.name}",
                file=sys.stderr,
            )
            continue
        profile = PROFILE_BY_VIA[m.group("via")]
        table = pq.read_table(pq_file).to_pylist()
        for rec in table:
            rows.append(
                {
                    "parquet_file": pq_file.name,
                    "upstream_slot_in_name": int(m.group("slot")),
                    "caller_profile": profile,
                    "classification": CLASSIFICATION[profile],
                    "amm_name": m.group("pmm"),
                    "instruction_version": INSTRUCTION_BY_PMM[m.group("pmm")],
                    "program_id": HUMIDIFI_PROGRAM_ID,
                    "market_id": m.group("market"),
                    "slot": rec.get("slot"),
                    "src_token": rec.get("src_token"),
                    "dst_token": rec.get("dst_token"),
                    "amount_in": rec.get("amount_in"),
                    "amount_out": rec.get("amount_out"),
                    "spread": rec.get("spread"),
                    "spread_bps": rec.get("spread_bps"),
                    "compute_units": rec.get("compute_units"),
                    "simulator_return": "OK",
                    "simulator_error": "",
                    "row_label": "",
                }
            )
    for fail_path in [results_dir / "failures.txt"]:
        if not fail_path.exists():
            continue
        for line in fail_path.read_text().splitlines():
            m = re.match(
                r"RUN_FAILED tag=(\S+) pmm=(\S+) suffix=(\S+) (\S+)->(\S+) amount=(\S+)",
                line,
            )
            if not m:
                continue
            tag, pmm, _suffix, src, dst, amount = m.groups()
            rows.append(
                {
                    "parquet_file": "",
                    "upstream_slot_in_name": None,
                    "caller_profile": PROFILE_BY_VIA.get(tag, tag.upper()),
                    "classification": CLASSIFICATION.get(
                        PROFILE_BY_VIA.get(tag, ""), "SYNTHETIC_SIMULATION"
                    ),
                    "amm_name": pmm,
                    "instruction_version": INSTRUCTION_BY_PMM.get(pmm, "unknown"),
                    "program_id": HUMIDIFI_PROGRAM_ID,
                    "market_id": _suffix,
                    "slot": None,
                    "src_token": src,
                    "dst_token": dst,
                    "amount_in": float(amount),
                    "amount_out": None,
                    "spread": None,
                    "spread_bps": None,
                    "compute_units": None,
                    "simulator_return": "RUN_FAILED",
                    "simulator_error": "see log; failure preserved",
                    "row_label": "BLOCKED",
                }
            )
    return rows


def annotate_deltas(rows: list[dict]) -> None:
    groups: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        key = (
            r["amm_name"],
            r["market_id"],
            r["src_token"],
            r["dst_token"],
            r["amount_in"],
        )
        groups[key].setdefault(r["caller_profile"], r)
    for r in rows:
        key = (
            r["amm_name"],
            r["market_id"],
            r["src_token"],
            r["dst_token"],
            r["amount_in"],
        )
        group = groups[key]
        for baseline in ("DIRECT", "MAGNUS_NATIVE"):
            base = group.get(baseline)
            field = f"caller_delta_bps_vs_{baseline.lower().replace('_', '_')}"
            if base is None or base["amount_out"] is None or r["amount_out"] is None:
                r[field] = None
            elif base["amount_out"] == 0:
                r[field] = None
            else:
                r[field] = round(
                    (r["amount_out"] - base["amount_out"])
                    / base["amount_out"]
                    * 10_000,
                    4,
                )


def label_best(rows: list[dict]) -> None:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r["simulator_return"] != "OK":
            continue
        key = (
            r["amm_name"],
            r["market_id"],
            r["src_token"],
            r["dst_token"],
            r["amount_in"],
        )
        groups[key].append(r)
    for group in groups.values():
        simulated = [
            r
            for r in group
            if r["classification"] == "SYNTHETIC_SIMULATION"
            or r["caller_profile"] == "MAGNUS_NATIVE"
        ]
        genuine = [
            r
            for r in group
            if r["classification"] == "GENUINE_EXECUTABLE_ROUTE_CANDIDATE"
        ]
        if simulated and all(r["amount_out"] is not None for r in simulated):
            best = max(simulated, key=lambda r: r["amount_out"])
            worst = min(simulated, key=lambda r: r["amount_out"])
            if best["amount_out"] == worst["amount_out"]:
                for r in group:
                    r["row_label"] = (
                        "NO_DIFFERENCE"
                        if r["simulator_return"] == "OK"
                        else r["row_label"]
                    )
            else:
                best["row_label"] = "BEST_SIMULATED_CALLER_PROFILE"
        if genuine and all(r["amount_out"] is not None for r in genuine):
            best_g = max(genuine, key=lambda r: r["amount_out"])
            if best_g["row_label"] == "":
                best_g["row_label"] = "BEST_REAL_EXECUTABLE_ROUTE"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir")
    ap.add_argument("--snapshot-id", required=True)
    ap.add_argument("--slot", type=int, default=None)
    ap.add_argument("--account-snapshot-digest", default="")
    ap.add_argument("--program-digest", default="")
    ap.add_argument(
        "--pmm-sim-commit", default="cc4ae891a2a765d92c89d4381f96dce4afd446bb"
    )
    ap.add_argument("--magnus-rev", default="9ecd34b634031f5dfdf5747c33a329605ea6e7c4")
    ap.add_argument("--cargo-lock-digest", default="")
    ap.add_argument("--rustc", default="")
    ap.add_argument(
        "--matrix",
        default=None,
        help="market_matrix_v1.json path; filters rows to the defined amount ladder",
    )
    ap.add_argument("--out-csv", default=None)
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args()

    results_dir = Path(args.results_dir)
    rows = load_rows(results_dir)
    if args.matrix:
        matrix = json.loads(Path(args.matrix).read_text(encoding="utf-8"))
        ladder = {float(a) for a in matrix["amount_grid_human_units"]}
        dropped = len(rows)
        rows = [r for r in rows if r["amount_in"] in ladder]
        print(
            f"ladder filter: kept {len(rows)}/{dropped} rows (adjacent range probes dropped)"
        )
    annotate_deltas(rows)
    label_best(rows)

    fieldnames = [
        "snapshot_id",
        "slot",
        "account_snapshot_digest",
        "program_digest",
        "program_binary_source",
        "amm_name",
        "instruction_version",
        "program_id",
        "market_id",
        "caller_profile",
        "classification",
        "direction_src",
        "direction_dst",
        "amount_in",
        "amount_out",
        "spread_bps",
        "reverse_roundtrip_out_raw",
        "caller_delta_bps_vs_direct",
        "caller_delta_bps_vs_magnus_native",
        "cu_consumed",
        "simulator_return",
        "simulator_error",
        "row_label",
        "pmm_sim_commit",
        "magnus_rev",
        "cargo_lock_digest",
        "run_metadata",
    ]
    csv_path = Path(args.out_csv or results_dir / "caller_profile_results.csv")
    json_path = Path(args.out_json or results_dir / "caller_profile_results.json")
    out_rows = []
    for r in rows:
        out_rows.append(
            {
                "snapshot_id": args.snapshot_id,
                "slot": args.slot if args.slot is not None else r["slot"],
                "account_snapshot_digest": args.account_snapshot_digest,
                "program_digest": args.program_digest,
                "program_binary_source": "harness_shipped_upstream_mirror",
                "amm_name": r["amm_name"],
                "instruction_version": r["instruction_version"],
                "program_id": r["program_id"],
                "market_id": r["market_id"],
                "caller_profile": r["caller_profile"],
                "classification": r["classification"],
                "direction_src": r["src_token"],
                "direction_dst": r["dst_token"],
                "amount_in": r["amount_in"],
                "amount_out": r["amount_out"],
                "spread_bps": r["spread_bps"],
                "reverse_roundtrip_out_raw": None,
                "caller_delta_bps_vs_direct": r.get("caller_delta_bps_vs_direct"),
                "caller_delta_bps_vs_magnus_native": r.get(
                    "caller_delta_bps_vs_magnus_native"
                ),
                "cu_consumed": r["compute_units"],
                "simulator_return": r["simulator_return"],
                "simulator_error": r["simulator_error"],
                "row_label": r["row_label"],
                "pmm_sim_commit": args.pmm_sim_commit,
                "magnus_rev": args.magnus_rev,
                "cargo_lock_digest": args.cargo_lock_digest,
                "run_metadata": f"rustc={args.rustc}; via={r['caller_profile']}; source_parquet={r['parquet_file']}",
            }
        )
    out_rows.sort(key=lambda r: json.dumps(r, sort_keys=True, default=str))
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)
    unknown = sum(
        1 for r in out_rows if r["simulator_return"] not in ("OK", "RUN_FAILED")
    )
    receipt = {
        "schema": "studious-pancake.pmm-sim-caller-profile-results.v1",
        "results_csv_sha256": sha256_file(csv_path),
        "row_count": len(out_rows),
        "ok_rows": sum(1 for r in out_rows if r["simulator_return"] == "OK"),
        "failed_rows": sum(
            1 for r in out_rows if r["simulator_return"] == "RUN_FAILED"
        ),
        "unknown_rows": unknown,
        "unknown_note": "unknown results are counted as neither positive nor negative",
        "classification_counts": {
            c: sum(1 for r in out_rows if r["classification"] == c)
            for c in sorted({r["classification"] for r in out_rows})
        },
        "row_label_counts": {
            l: sum(1 for r in out_rows if r["row_label"] == l)
            for l in [
                "BEST_SIMULATED_CALLER_PROFILE",
                "BEST_REAL_EXECUTABLE_ROUTE",
                "NO_DIFFERENCE",
                "BLOCKED",
            ]
        },
        "snapshot_id": args.snapshot_id,
        "pmm_sim_commit": args.pmm_sim_commit,
        "magnus_rev": args.magnus_rev,
        "production_boundary": "research only; synthetic simulation rows have no mainnet meaning; no profitability claim",
    }
    json_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"OK rows={receipt['row_count']} ok={receipt['ok_rows']} failed={receipt['failed_rows']} unknown={receipt['unknown_rows']}"
    )
    print(f"csv={csv_path} json={json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
