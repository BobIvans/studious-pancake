#!/usr/bin/env python3
"""
Backtest Replay & Tuning Engine for Paper Trading Logs.

Reads recorded paper trades from SQLite (bot_history.db) and re-evaluates
execution decisions under hypothetical parameters, allowing data-driven
tuning of min_profit, tip_pct, slippage_bps, and other config values.

Usage:
    python scripts/backtest_replay.py                          # Use defaults
    python scripts/backtest_replay.py --db-path ./custom.db    # Custom DB path
    python scripts/backtest_replay.py --min-profit 0.0002 --slippage 10 --tip-pct 0.3
    python scripts/backtest_replay.py --min-profit 0.0001 0.0002 0.0005  # Multiple values
"""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple


# ── Column schema for paper_trades table ─────────────────────────────────
# Expected columns (dynamic — the table may have been created with
# any subset of these; we read them dynamically via PRAGMA table_info).
EXPECTED_COLUMNS = {
    "slot", "blockhash", "route", "token_in", "token_out",
    "amount_lamports", "gross_revenue_lamports", "flashloan_fee_lamports",
    "dex_fee_lamports", "slippage_bps", "network_fee_lamports",
    "priority_fee_lamports", "jito_tip_lamports", "ata_rent_lamports",
    "total_cost_lamports", "net_profit_lamports", "roi_pct", "decision",
}


def discover_columns(cursor: sqlite3.Cursor, table: str) -> List[str]:
    """Return all column names for *table*."""
    cursor.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cursor.fetchall()]


def load_trades(db_path: str) -> List[Dict]:
    """Load all rows from the paper_trades table."""
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    tables = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = [t[0] for t in tables]

    trades = []
    for tbl in table_names:
        cols = discover_columns(cursor, tbl)
        pk_str = ", ".join(cols)
        rows = cursor.execute(f"SELECT {pk_str} FROM {tbl}").fetchall()
        for row in rows:
            trades.append(dict(row))

    conn.close()
    return trades


# ── Backtesting logic ─────────────────────────────────────────────────


def backtest_trade(
    trade: Dict,
    min_profit_sol: float,
    tip_pct: float,
    slippage_bps: int,
) -> Dict:
    """Re-evaluate a single paper trade under new parameters.

    Returns a dict with keys:
      - original_net_profit_sol
      - backtested_net_profit_sol
      - decision (EXECUTED / SKIPPED)
      - delta_sol
      - reason (if skipped)
    """
    gross = trade.get("gross_revenue_lamports", 0) or 0
    flashloan_fee = trade.get("flashloan_fee_lamports", 0) or 0
    dex_fee = trade.get("dex_fee_lamports", 0) or 0
    network_fee = trade.get("network_fee_lamports", 0) or 0
    priority_fee = trade.get("priority_fee_lamports", 0) or 0
    ata_rent = trade.get("ata_rent_lamports", 0) or 0
    amount = trade.get("amount_lamports", 0) or 0

    # Original net profit (as logged)
    original_total_cost = (
        flashloan_fee + dex_fee + network_fee + priority_fee + ata_rent
    )
    original_net = gross - original_total_cost
    original_net_sol = original_net / 1e9

    # Backtested: compute Jito tip from gross profit and tip_pct
    original_jito_tip = trade.get("jito_tip_lamports", 0) or 0

    # Recompute net profit with the new tip percentage applied to gross profit
    backtested_jito_tip = int(max(gross * tip_pct, 10_000))  # 10k lamports floor
    backtested_jito_tip_lamports = max(backtested_jito_tip, original_jito_tip)

    backtested_total_cost = (
        flashloan_fee
        + dex_fee
        + network_fee
        + priority_fee
        + ata_rent
        + backtested_jito_tip_lamports
    )
    backtested_net = gross - backtested_total_cost
    backtested_net_sol = backtested_net / 1e9

    # Decision
    min_profit_lamports = int(min_profit_sol * 1e9)
    if backtested_net < min_profit_lamports:
        return {
            "original_net_profit_sol": original_net_sol,
            "backtested_net_profit_sol": backtested_net_sol,
            "decision": "SKIPPED",
            "delta_sol": backtested_net_sol - original_net_sol,
            "reason": f"net {backtested_net_sol:.6f} SOL < min {min_profit_sol:.6f} SOL",
            "amount_sol": amount / 1e9,
            "slippage_bps": slippage_bps,
            "tip_lamports": backtested_jito_tip_lamports,
        }

    return {
        "original_net_profit_sol": original_net_sol,
        "backtested_net_profit_sol": backtested_net_sol,
        "decision": "EXECUTED",
        "delta_sol": backtested_net_sol - original_net_sol,
        "reason": "",
        "amount_sol": amount / 1e9,
        "slippage_bps": slippage_bps,
        "tip_lamports": backtested_jito_tip_lamports,
    }


def print_comparison_table(
    results: List[Dict],
    caption: str,
    min_profit_sol: float,
):
    """Pretty-print a comparison table."""
    executed = [r for r in results if r["decision"] == "EXECUTED"]
    skipped = [r for r in results if r["decision"] == "SKIPPED"]

    total_original = sum(r["original_net_profit_sol"] for r in results)
    total_backtested = sum(r["backtested_net_profit_sol"] for r in executed)
    avg_delta = (
        sum(r["delta_sol"] for r in executed) / len(executed)
        if executed
        else 0.0
    )

    print(f"\n{'=' * 72}")
    print(f"  {caption}")
    print(f"  Min Profit: {min_profit_sol:.6f} SOL")
    print(f"{'=' * 72}")
    print(f"  Total trades examined:   {len(results)}")
    print(f"  Would EXECUTE:           {len(executed)}")
    print(f"  Would SKIP:              {len(skipped)}")
    print(f"  Original total net:      {total_original:.6f} SOL")
    print(f"  Backtested total net:    {total_backtested:.6f} SOL")
    print(f"  Avg delta per exec:      {avg_delta:.6f} SOL")
    if results:
        print(f"  Trade amounts:           {results[0]['amount_sol']:.4f} – {results[-1]['amount_sol']:.4f} SOL")
    print(f"{'=' * 72}\n")

    # Per-trade details for skipped
    if skipped:
        print(f"  ── Skipped trades ──")
        for r in skipped:
            print(
                f"    {r['reason']:65s}  "
                f"(orig={r['original_net_profit_sol']:.6f}, "
                f"new={r['backtested_net_profit_sol']:.6f})"
            )
        print()

    if executed:
        print(f"  ── First 10 executed trades (of {len(executed)}) ──")
        for r in executed[:10]:
            print(
                f"    amount={r['amount_sol']:.4f} SOL  "
                f"orig={r['original_net_profit_sol']:.6f}  "
                f"new={r['backtested_net_profit_sol']:.6f}  "
                f"delta={r['delta_sol']:.6f}  "
                f"slippage={r['slippage_bps']}bps"
            )
        if len(executed) > 10:
            print(f"    ... and {len(executed) - 10} more")


def run_backtest(db_path: str, min_profit: float, tip_pct: float, slippage: int):
    """Run the backtest with a single parameter set."""
    trades = load_trades(db_path)
    if not trades:
        print(f"No paper trades found in {db_path}")
        return [], [], 0.0

    results = [
        backtest_trade(t, min_profit, tip_pct, slippage) for t in trades
    ]

    executed = [r for r in results if r["decision"] == "EXECUTED"]
    skipped = [r for r in results if r["decision"] == "SKIPPED"]
    total_backtested = sum(r["backtested_net_profit_sol"] for r in executed)

    return results, executed, total_backtested


def main():
    parser = argparse.ArgumentParser(
        description="Backtest Replay & Tuning Engine for Paper Trading Logs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s\n"
            "  %(prog)s --min-profit 0.0002 --slippage 10 --tip-pct 0.3\n"
            "  %(prog)s --min-profit 0.0001 0.0002 0.0005\n"
        ),
    )
    parser.add_argument(
        "--db-path",
        default=os.getenv("BOT_HISTORY_DB", "bot_history.db"),
        help="Path to SQLite database (default: bot_history.db or $BOT_HISTORY_DB)",
    )
    parser.add_argument(
        "--min-profit",
        type=float,
        nargs="*",
        default=[0.00005],
        help="Minimum profit threshold in SOL (one or more values, default: 0.00005)",
    )
    parser.add_argument(
        "--tip-pct",
        type=float,
        default=0.4,
        help="Jito tip as fraction of gross profit (default: 0.4 = 40%%)",
    )
    parser.add_argument(
        "--slippage",
        type=int,
        default=15,
        help="Slippage tolerance in BPS (default: 15)",
    )

    args = parser.parse_args()

    if not os.path.exists(args.db_path):
        print(f"ERROR: Database not found: {args.db_path}")
        print("Run the bot in paper-trading mode first to generate trade logs.")
        sys.exit(1)

    min_profit_values = args.min_profit if args.min_profit else [0.00005]

    print(f"🔄 Backtest Replay Engine")
    print(f"   DB path:   {args.db_path}")
    print(f"   Tip pct:   {args.tip_pct}")
    print(f"   Slippage:  {args.slippage} BPS")
    print(f"   Min profit: {', '.join(f'{v:.6f} SOL' for v in min_profit_values)}")
    print()

    trades = load_trades(args.db_path)
    print(f"📊 Loaded {len(trades)} paper trades from database\n")

    if not trades:
        print("No trades to analyze.")
        return

    best_net = -float("inf")
    best_params = None
    best_results = None

    for min_profit_sol in min_profit_values:
        results = [
            backtest_trade(t, min_profit_sol, args.tip_pct, args.slippage)
            for t in trades
        ]
        executed = [r for r in results if r["decision"] == "EXECUTED"]
        total_backtested = sum(r["backtested_net_profit_sol"] for r in executed)

        caption = (
            f"📈 Scenario: min_profit={min_profit_sol:.6f} SOL | "
            f"tip_pct={args.tip_pct} | slippage={args.slippage} BPS"
        )
        print_comparison_table(results, caption, min_profit_sol)

        if total_backtested > best_net:
            best_net = total_backtested
            best_params = (min_profit_sol, args.tip_pct, args.slippage)
            best_results = results

    # Summary
    if best_params:
        print(f"\n{'=' * 72}")
        print(f"  🏆 BEST PARAMETER SET")
        print(f"  Min profit: {best_params[0]:.6f} SOL")
        print(f"  Tip pct:    {best_params[1]}")
        print(f"  Slippage:   {best_params[2]} BPS")
        print(f"  Net profit: {best_net:.6f} SOL")
        executed_count = sum(
            1 for r in (best_results or []) if r["decision"] == "EXECUTED"
        )
        print(f"  Trades executed: {executed_count} / {len(best_results or [])}")
        print(f"{'=' * 72}")

    # Export CSV for further analysis
    export_path = f"backtest_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    if best_results:
        try:
            import csv

            with open(export_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(best_results[0].keys()))
                writer.writeheader()
                writer.writerows(best_results)
            print(f"📄 Detailed results exported to {export_path}")
        except Exception as e:
            print(f"⚠️  CSV export failed: {e}")


if __name__ == "__main__":
    main()
