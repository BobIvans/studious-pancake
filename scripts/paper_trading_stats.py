#!/usr/bin/env python3
"""
Paper Trading Statistics Viewer
Shows statistics from paper_trading.db
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))

from ingest.data_aggregator import DataAggregator

async def main():
    aggregator = DataAggregator("bot_history.db")

    print("📊 PAPER TRADING STATISTICS")
    print("=" * 50)

    try:
        stats = await aggregator.get_paper_trading_stats(days=1)  # Last 24 hours

        print(f"📈 Total Paper Trades: {stats['total_trades']}")
        print(f"💰 Total Profit: {stats['total_profit']:.6f} SOL")
        print(f"📅 Period: {stats['period_days']} days")
        print()

        if stats['top_routes']:
            print("🏆 Top Profitable Routes:")
            for i, route in enumerate(stats['top_routes'][:5], 1):
                print(f"  {i}. {route['route']}")
                print(f"     Avg Profit: {route['avg_profit']:.6f} SOL")
                print(f"     Trades: {route['count']}")
        else:
            print("📝 No paper trades found yet")

    except Exception as e:
        print(f"❌ Error reading stats: {e}")

if __name__ == "__main__":
    asyncio.run(main())