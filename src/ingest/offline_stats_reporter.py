#!/usr/bin/env python3
"""Offline statistics reporter for arbitrage trading data analysis."""

import asyncio
import logging
import json
import statistics
from typing import Dict, List, Any, Tuple, Optional
from collections import defaultdict
try:
    import matplotlib.pyplot as plt
    import seaborn as sns
    VISUALIZATION_AVAILABLE = True
except ImportError:
    VISUALIZATION_AVAILABLE = False
    plt = None
    sns = None
from datetime import datetime, timedelta

from src.ingest.data_collector import DataCollector

logger = logging.getLogger(__name__)


class OfflineStatsReporter:
    """Analyzes collected arbitrage data to provide descriptive statistics."""

    def __init__(self, data_collector: DataCollector):
        self.data_collector = data_collector
        self.analysis_results = {}

    async def run_full_analysis(self, days_back: int = 7) -> Dict[str, Any]:
        """Run comprehensive analysis on recent trading data."""
        logger.info(f"Starting stats analysis for last {days_back} days...")

        trades = await self.data_collector.get_recent_trades(50000)
        
        # FIX 231: Warn if fetch cap hit
        if len(trades) >= 50000:
            logger.warning("WARNING: Trade fetch cap reached (50,000). Analysis may be truncated.")

        if not trades:
            return {"error": "No trade data available for analysis"}

        cutoff_time = datetime.now() - timedelta(days=days_back)
        recent_trades = [
            t for t in trades
            if datetime.fromisoformat(t.get("datetime", datetime.now().isoformat())) > cutoff_time
        ]
        
        # FIX 229: Short-circuit if recent_trades is empty after date filter
        if not recent_trades:
            return {"error": f"No trade data available for last {days_back} days"}

        logger.info(f"Analyzing {len(recent_trades)} trades from last {days_back} days")

        analysis = {
            "summary": self._generate_summary_stats(recent_trades),
            "score_analysis": self._analyze_score_effectiveness(recent_trades),
            "pair_performance": self._analyze_pair_performance(recent_trades),
            "time_analysis": self._analyze_timing_patterns(recent_trades),
            "network_analysis": self._analyze_network_impact(recent_trades),
            "generated_at": datetime.now().isoformat()
        }

        self.analysis_results = analysis
        return analysis

    def _generate_summary_stats(self, trades: List[Dict]) -> Dict[str, Any]:
        """Generate basic summary statistics."""
        if not trades:
            return {}

        successful_trades = [t for t in trades if t.get("result") == "success"]
        failed_trades = [t for t in trades if t.get("result") != "success"]

        return {
            "total_trades": len(trades),
            "successful_trades": len(successful_trades),
            "failed_trades": len(failed_trades),
            "success_rate": len(successful_trades) / len(trades),
            "average_score": statistics.mean(float(t.get("initial_score", 0.0)) for t in trades),
            "average_profit": statistics.mean(float(t.get("actual_profit_sol", 0.0)) for t in trades),
            "average_execution_time": statistics.mean(float(t.get("execution_time_ms", 0.0)) for t in trades),
            "total_profit_sol": sum(float(t.get("actual_profit_sol", 0.0)) for t in trades),
            "best_performing_pair": self._find_best_pair(trades),
            "worst_performing_pair": self._find_worst_pair(trades)
        }

    def _analyze_score_effectiveness(self, trades: List[Dict]) -> Dict[str, Any]:
        """Analyze how well scoring predicts success."""
        successful_scores = [float(t.get("initial_score", 0.0)) for t in trades if t.get("result") == "success"]
        failed_scores = [float(t.get("initial_score", 0.0)) for t in trades if t.get("result") != "success"]

        analysis = {
            "avg_success_score": statistics.mean(successful_scores) if successful_scores else 0,
            "avg_failed_score": statistics.mean(failed_scores) if failed_scores else 0,
            "score_difference": (statistics.mean(successful_scores) if successful_scores else 0) -
                              (statistics.mean(failed_scores) if failed_scores else 0),
            "score_correlation": self._calculate_score_correlation(trades)
        }

        thresholds = [20, 40, 60, 80]
        threshold_analysis = {}

        for threshold in thresholds:
            high_score_trades = [t for t in trades if float(t.get("initial_score", 0.0)) >= threshold]
            if high_score_trades:
                success_rate = len([t for t in high_score_trades if t.get("result") == "success"]) / len(high_score_trades)
                threshold_analysis[f"score_{threshold}_plus"] = {
                    "count": len(high_score_trades),
                    "success_rate": success_rate,
                    "avg_profit": statistics.mean(float(t.get("actual_profit_sol", 0.0)) for t in high_score_trades)
                }

        analysis["threshold_analysis"] = threshold_analysis
        return analysis

    def _analyze_pair_performance(self, trades: List[Dict]) -> Dict[str, Any]:
        """Analyze performance by trading pair."""
        pair_stats = defaultdict(list)

        for trade in trades:
            pair_stats[trade["pair"]].append(trade)

        pair_analysis = {}
        for pair, pair_trades in pair_stats.items():
            successful = [t for t in pair_trades if t.get("result") == "success"]
            pair_analysis[pair] = {
                "total_trades": len(pair_trades),
                "success_rate": len(successful) / len(pair_trades),
                "avg_profit": statistics.mean(float(t.get("actual_profit_sol", 0.0)) for t in pair_trades),
                "avg_score": statistics.mean(float(t.get("initial_score", 0.0)) for t in pair_trades),
                "total_volume": sum(float(t.get("expected_profit_sol", 0.0)) for t in pair_trades)
            }

        sorted_pairs = sorted(pair_analysis.items(),
                            key=lambda x: x[1]["success_rate"], reverse=True)

        return {
            "pair_performance": dict(sorted_pairs[:10]),
            "total_pairs": len(pair_analysis)
        }

    def _analyze_timing_patterns(self, trades: List[Dict]) -> Dict[str, Any]:
        """Analyze timing patterns and their impact on success."""
        hourly_stats = defaultdict(list)

        for trade in trades:
            dt = datetime.fromisoformat(trade["datetime"])
            hour = dt.hour
            hourly_stats[hour].append(trade)

        timing_analysis = {}
        for hour, hour_trades in hourly_stats.items():
            successful = [t for t in hour_trades if t.get("result") == "success"]
            timing_analysis[hour] = {
                "total_trades": len(hour_trades),
                "success_rate": len(successful) / len(hour_trades),
                "avg_profit": statistics.mean(float(t.get("actual_profit_sol", 0.0)) for t in hour_trades),
                "peak_hour": len(hour_trades) > statistics.mean(len(h) for h in hourly_stats.values())
            }

        if not timing_analysis:
            return {
                "hourly_performance": {},
                "best_trading_hour": None,
                "worst_trading_hour": None,
                "best_hour_success_rate": 0,
                "time_based_insights": []
            }
        best_hour = max(timing_analysis.items(), key=lambda x: x[1]["success_rate"])
        worst_hour = min(timing_analysis.items(), key=lambda x: x[1]["success_rate"])

        return {
            "hourly_performance": dict(sorted(timing_analysis.items())),
            "best_trading_hour": best_hour[0],
            "worst_trading_hour": worst_hour[0],
            "best_hour_success_rate": best_hour[1]["success_rate"],
            "time_based_insights": self._extract_timing_insights(timing_analysis)
        }

    def _analyze_network_impact(self, trades: List[Dict]) -> Dict[str, Any]:
        """Analyze how network conditions affect trading success."""
        congestion_buckets = defaultdict(list)

        for trade in trades:
            congestion = trade.get("network_congestion", 50)
            if congestion < 25:
                bucket = "low"
            elif congestion < 75:
                bucket = "moderate"
            else:
                bucket = "high"
            congestion_buckets[bucket].append(trade)

        network_analysis = {}
        for level, level_trades in congestion_buckets.items():
            successful = [t for t in level_trades if t.get("result") == "success"]
            network_analysis[level] = {
                "total_trades": len(level_trades),
                "success_rate": len(successful) / len(level_trades) if level_trades else 0,
                "avg_profit": statistics.mean(float(t.get("actual_profit_sol", 0.0)) for t in level_trades) if level_trades else 0,
                "avg_execution_time": statistics.mean(float(t.get("execution_time_ms", 0.0)) for t in level_trades) if level_trades else 0
            }

        return network_analysis

    def _calculate_score_correlation(self, trades: List[Dict]) -> float:
        """Calculate correlation between initial score and actual success."""
        scores = [float(t.get("initial_score", 0.0)) for t in trades]
        successes = [1 if t.get("result") == "success" else 0 for t in trades]

        if len(scores) < 2:
            return 0.0

        try:
            return statistics.correlation(scores, successes)
        except Exception:  # FIX 127
            return 0.0

    def _find_best_pair(self, trades: List[Dict]) -> str:
        """Find the best performing trading pair."""
        pair_stats = defaultdict(list)
        for trade in trades:
            pair_stats[trade["pair"]].append(trade["result"] == "success")

        if not pair_stats:
            return "N/A"

        return max(pair_stats.items(),
                  key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 0)[0]

    def _find_worst_pair(self, trades: List[Dict]) -> str:
        """Find the worst performing trading pair."""
        pair_stats = defaultdict(list)
        for trade in trades:
            pair_stats[trade["pair"]].append(trade["result"] == "success")

        if not pair_stats:
            return "N/A"

        return min(pair_stats.items(),
                  key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 0)[0]

    def _extract_timing_insights(self, timing_analysis: Dict) -> List[str]:
        """Extract key insights from timing analysis."""
        insights = []

        peak_hours = [hour for hour, data in timing_analysis.items() if data["peak_hour"]]
        if peak_hours:
            insights.append(f"Peak activity hours: {', '.join(map(str, peak_hours))}")

        best_hours = sorted(timing_analysis.items(),
                          key=lambda x: x[1]["success_rate"], reverse=True)[:3]
        if best_hours and best_hours[0][1]["success_rate"] > 0.6:
            insights.append(f"Best performing hours: {', '.join(str(h[0]) for h in best_hours)}")

        return insights

    def generate_report(self, save_path: Optional[str] = None) -> str:
        """Generate a comprehensive analysis report."""
        if not self.analysis_results:
            return "No analysis data available. Run run_full_analysis() first."

        report = []
        report.append("# Arbitrage Analysis Report")
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")

        summary = self.analysis_results.get("summary", {})
        report.append("## Summary Statistics")
        report.append(f"- Total Trades: {summary.get('total_trades', 0)}")
        report.append(f"- Success Rate: {summary.get('success_rate', 0):.1%}")
        report.append(f"- Average Score: {summary.get('average_score', 0):.1f}")
        report.append(f"- Total Profit: {summary.get('total_profit_sol', 0):.4f} SOL")
        report.append("")

        score_analysis = self.analysis_results.get("score_analysis", {})
        report.append("## Score Effectiveness")
        report.append(f"- Success Score Avg: {score_analysis.get('avg_success_score', 0):.1f}")
        report.append(f"- Failed Score Avg: {score_analysis.get('avg_failed_score', 0):.1f}")
        report.append(f"- Score Correlation: {score_analysis.get('score_correlation', 0):.2f}")
        report.append("")

        pair_perf = self.analysis_results.get("pair_performance", {})
        if pair_perf:
            report.append("## Top Performing Pairs")
            for pair, stats in list(pair_perf.items())[:5]:
                report.append(f"- {pair}: {stats['success_rate']:.1%} success, {stats['avg_profit']:.4f} SOL avg profit")
            report.append("")

        full_report = "\n".join(report)

        if save_path:
            with open(save_path, 'w') as f:
                f.write(full_report)
            logger.info(f"Report saved to {save_path}")

        return full_report


def main():
    """Run offline analysis."""
    import sys

    if len(sys.argv) > 1:
        days_back = int(sys.argv[1])
    else:
        days_back = 7

    collector = DataCollector()
    analyzer = OfflineStatsReporter(collector)

    results = asyncio.run(analyzer.run_full_analysis(days_back=days_back))

    if "error" in results:
        print(f"Analysis failed: {results['error']}")
        return

    report = analyzer.generate_report(save_path="analysis_report.md")
    print(report)

    print("Analysis complete! Report saved to analysis_report.md")


if __name__ == "__main__":
    main()
