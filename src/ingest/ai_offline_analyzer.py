#!/usr/bin/env python3
"""AI Offline Analyzer for arbitrage trading data analysis and insights."""

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

from src.ingest.ai_data_collector import AIDataCollector

logger = logging.getLogger(__name__)

class AIOfflineAnalyzer:
    """Analyzes collected arbitrage data to provide AI insights and recommendations."""

    def __init__(self, data_collector: AIDataCollector):
        self.data_collector = data_collector
        self.analysis_results = {}

    async def run_full_analysis(self, days_back: int = 7) -> Dict[str, Any]:
        """Run comprehensive analysis on recent trading data."""
        logger.info(f"🔍 Starting AI analysis for last {days_back} days...")

        # Get recent trades
        trades = await self.data_collector.get_recent_trades(50000)  # Last 50k trades

        if not trades:
            return {"error": "No trade data available for analysis"}

        # Filter by time
        cutoff_time = datetime.now() - timedelta(days=days_back)
        recent_trades = [
            t for t in trades
            if datetime.fromisoformat(t["datetime"]) > cutoff_time
        ]

        logger.info(f"📊 Analyzing {len(recent_trades)} trades from last {days_back} days")

        analysis = {
            "summary": self._generate_summary_stats(recent_trades),
            "score_analysis": self._analyze_score_effectiveness(recent_trades),
            "pair_performance": self._analyze_pair_performance(recent_trades),
            "time_analysis": self._analyze_timing_patterns(recent_trades),
            "network_analysis": self._analyze_network_impact(recent_trades),
            "recommendations": self._generate_recommendations(recent_trades),
            "generated_at": datetime.now().isoformat()
        }

        self.analysis_results = analysis
        return analysis

    def _generate_summary_stats(self, trades: List[Dict]) -> Dict[str, Any]:
        """Generate basic summary statistics."""
        if not trades:
            return {}

        successful_trades = [t for t in trades if t["result"] == "success"]
        failed_trades = [t for t in trades if t["result"] != "success"]

        return {
            "total_trades": len(trades),
            "successful_trades": len(successful_trades),
            "failed_trades": len(failed_trades),
            "success_rate": len(successful_trades) / len(trades),
            "average_score": statistics.mean(t["initial_score"] for t in trades),
            "average_profit": statistics.mean(t["actual_profit_sol"] for t in trades),
            "average_execution_time": statistics.mean(t["execution_time_ms"] for t in trades),
            "total_profit_sol": sum(t["actual_profit_sol"] for t in trades),
            "best_performing_pair": self._find_best_pair(trades),
            "worst_performing_pair": self._find_worst_pair(trades)
        }

    def _analyze_score_effectiveness(self, trades: List[Dict]) -> Dict[str, Any]:
        """Analyze how well scoring predicts success."""
        successful_scores = [t["initial_score"] for t in trades if t["result"] == "success"]
        failed_scores = [t["initial_score"] for t in trades if t["result"] != "success"]

        analysis = {
            "avg_success_score": statistics.mean(successful_scores) if successful_scores else 0,
            "avg_failed_score": statistics.mean(failed_scores) if failed_scores else 0,
            "score_difference": (statistics.mean(successful_scores) if successful_scores else 0) -
                              (statistics.mean(failed_scores) if failed_scores else 0),
            "score_correlation": self._calculate_score_correlation(trades)
        }

        # Score threshold analysis
        thresholds = [20, 40, 60, 80]
        threshold_analysis = {}

        for threshold in thresholds:
            high_score_trades = [t for t in trades if t["initial_score"] >= threshold]
            if high_score_trades:
                success_rate = len([t for t in high_score_trades if t["result"] == "success"]) / len(high_score_trades)
                threshold_analysis[f"score_{threshold}_plus"] = {
                    "count": len(high_score_trades),
                    "success_rate": success_rate,
                    "avg_profit": statistics.mean(t["actual_profit_sol"] for t in high_score_trades)
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
            successful = [t for t in pair_trades if t["result"] == "success"]
            pair_analysis[pair] = {
                "total_trades": len(pair_trades),
                "success_rate": len(successful) / len(pair_trades),
                "avg_profit": statistics.mean(t["actual_profit_sol"] for t in pair_trades),
                "avg_score": statistics.mean(t["initial_score"] for t in pair_trades),
                "total_volume": sum(t["expected_profit_sol"] for t in pair_trades)
            }

        # Sort by success rate
        sorted_pairs = sorted(pair_analysis.items(),
                            key=lambda x: x[1]["success_rate"], reverse=True)

        return {
            "pair_performance": dict(sorted_pairs[:10]),  # Top 10 performing pairs
            "total_pairs": len(pair_analysis)
        }

    def _analyze_timing_patterns(self, trades: List[Dict]) -> Dict[str, Any]:
        """Analyze timing patterns and their impact on success."""
        # Group by hour of day
        hourly_stats = defaultdict(list)

        for trade in trades:
            dt = datetime.fromisoformat(trade["datetime"])
            hour = dt.hour
            hourly_stats[hour].append(trade)

        timing_analysis = {}
        for hour, hour_trades in hourly_stats.items():
            successful = [t for t in hour_trades if t["result"] == "success"]
            timing_analysis[hour] = {
                "total_trades": len(hour_trades),
                "success_rate": len(successful) / len(hour_trades),
                "avg_profit": statistics.mean(t["actual_profit_sol"] for t in hour_trades),
                "peak_hour": len(hour_trades) > statistics.mean(len(h["trades"]) for h in hourly_stats.values())
            }

        # Find best and worst hours
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
        # Group by network congestion levels
        congestion_buckets = defaultdict(list)

        for trade in trades:
            congestion = trade.get("network_congestion", 50)  # Default moderate
            if congestion < 25:
                bucket = "low"
            elif congestion < 75:
                bucket = "moderate"
            else:
                bucket = "high"
            congestion_buckets[bucket].append(trade)

        network_analysis = {}
        for level, level_trades in congestion_buckets.items():
            successful = [t for t in level_trades if t["result"] == "success"]
            network_analysis[level] = {
                "total_trades": len(level_trades),
                "success_rate": len(successful) / len(level_trades) if level_trades else 0,
                "avg_profit": statistics.mean(t["actual_profit_sol"] for t in level_trades) if level_trades else 0,
                "avg_execution_time": statistics.mean(t["execution_time_ms"] for t in level_trades) if level_trades else 0
            }

        return network_analysis

    def _generate_recommendations(self, trades: List[Dict]) -> List[str]:
        """Generate actionable recommendations based on analysis."""
        recommendations = []
        analysis = self.analysis_results

        # Score threshold recommendations
        score_analysis = analysis.get("score_analysis", {})
        threshold_analysis = score_analysis.get("threshold_analysis", {})

        if "score_80_plus" in threshold_analysis:
            high_score_data = threshold_analysis["score_80_plus"]
            if high_score_data["success_rate"] > 0.8:
                recommendations.append(
                    f"🚀 Excellent performance for high-score trades (>{high_score_data['success_rate']:.1%} success rate). "
                    "Consider increasing priority for trades with score > 80."
                )

        # Pair-specific recommendations
        pair_performance = analysis.get("pair_performance", {})
        if pair_performance:
            best_pair = max(pair_performance.items(), key=lambda x: x[1]["success_rate"])
            if best_pair[1]["success_rate"] > 0.7:
                recommendations.append(
                    f"🎯 Focus on {best_pair[0]} pair (success rate: {best_pair[1]['success_rate']:.1%}). "
                    "Consider increasing allocation to this pair."
                )

        # Timing recommendations
        time_analysis = analysis.get("time_analysis", {})
        if time_analysis.get("best_hour_success_rate", 0) > 0.7:
            best_hour = time_analysis["best_trading_hour"]
            recommendations.append(
                f"⏰ Optimal trading hours: Focus on {best_hour}:00 (success rate: {time_analysis['best_hour_success_rate']:.1%}). "
                "Consider scheduling more trades during these hours."
            )

        # Network condition recommendations
        network_analysis = analysis.get("network_analysis", {})
        if "high" in network_analysis and network_analysis["high"]["success_rate"] < 0.3:
            recommendations.append(
                "🌐 High network congestion significantly reduces success rate. "
                "Consider pausing trading during peak congestion periods."
            )

        # Score correlation insights
        score_corr = score_analysis.get("score_correlation", 0)
        if score_corr > 0.7:
            recommendations.append(
                f"{score_corr:.2f} Consider adjusting score weights for better prediction accuracy."
            )
        elif score_corr < 0.3:
            recommendations.append(
                f"{score_corr:.2f} Score prediction needs significant improvement. Consider collecting more features."
            )

        # Default recommendations if no specific insights
        if not recommendations:
            recommendations.extend([
                "📊 Collect more data for better analysis (target: 1000+ trades)",
                "🎛️ Consider adjusting scoring algorithm weights based on observed patterns",
                "⏱️ Monitor execution timing and optimize for network conditions"
            ])

        return recommendations

    def _calculate_score_correlation(self, trades: List[Dict]) -> float:
        """Calculate correlation between initial score and actual success."""
        scores = [t["initial_score"] for t in trades]
        successes = [1 if t["result"] == "success" else 0 for t in trades]

        if len(scores) < 2:
            return 0.0

        try:
            return statistics.correlation(scores, successes)
        except:
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

        # Find peak hours
        peak_hours = [hour for hour, data in timing_analysis.items() if data["peak_hour"]]
        if peak_hours:
            insights.append(f"Peak activity hours: {', '.join(map(str, peak_hours))}")

        # Find best performing hours
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
        report.append("# 🤖 AI Arbitrage Analysis Report")
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")

        # Summary
        summary = self.analysis_results.get("summary", {})
        report.append("## 📊 Summary Statistics")
        report.append(f"- Total Trades: {summary.get('total_trades', 0)}")
        report.append(f"- Success Rate: {summary.get('success_rate', 0):.1%}")
        report.append(f"- Average Score: {summary.get('average_score', 0):.1f}")
        report.append(f"- Total Profit: {summary.get('total_profit_sol', 0):.4f} SOL")
        report.append("")

        # Score Analysis
        score_analysis = self.analysis_results.get("score_analysis", {})
        report.append("## 🎯 Score Effectiveness")
        report.append(f"- Success Score Avg: {score_analysis.get('avg_success_score', 0):.1f}")
        report.append(f"- Failed Score Avg: {score_analysis.get('avg_failed_score', 0):.1f}")
        report.append(f"- Score Correlation: {score_analysis.get('score_correlation', 0):.2f}")
        report.append("")

        # Recommendations
        recommendations = self.analysis_results.get("recommendations", [])
        if recommendations:
            report.append("## 💡 AI Recommendations")
            for rec in recommendations:
                report.append(f"- {rec}")
            report.append("")

        # Pair Performance
        pair_perf = self.analysis_results.get("pair_performance", {})
        if pair_perf:
            report.append("## 📈 Top Performing Pairs")
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

    # Initialize components
    collector = AIDataCollector()
    analyzer = AIOfflineAnalyzer(collector)

    # Run analysis
    results = asyncio.run(analyzer.run_full_analysis(days_back=days_back))

    if "error" in results:
        print(f"❌ Analysis failed: {results['error']}")
        return

    # Generate and display report
    report = analyzer.generate_report(save_path="ai_analysis_report.md")
    print(report)

    print("✅ Analysis complete! Report saved to ai_analysis_report.md")


if __name__ == "__main__":
    main()