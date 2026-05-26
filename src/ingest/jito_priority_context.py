"""Jito Priority Context Adapter and Simulator for Dynamic Tips and Landing Pressure."""

from typing import Dict, Any, Optional, Literal
from dataclasses import dataclass
import time

PriorityLane = Literal["baseline", "elevated", "congested"]

@dataclass
class JitoPriorityContext:
    priority_lane: PriorityLane
    congestion_level: float  # 0.0 to 1.0
    recent_failed_tx_rate: float  # 0.0 to 1.0
    base_tip_lamports: int
    dynamic_tip_target_lamports: int
    tip_efficiency_score: float  # 0.0 to 1.0
    landing_pressure_score: float  # 0.0 to 1.0
    tip_budget_violation_flag: bool
    estimated_landing_improvement_pct: float
    timestamp_sec: int

class JitoPriorityContextAdapter:
    """Adapter for live Jito priority data with fallback simulation."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.base_tip_lamports = self.config.get("base_tip_lamports", 10000)  # 0.00001 SOL
        self.congestion_multiplier = self.config.get("congestion_multiplier", 5000)
        self.max_budget_sol = self.config.get("max_budget_sol", 10.0)

    def classify_priority_lane(self, congestion_level: float) -> PriorityLane:
        """Classify network congestion into priority lanes."""
        if congestion_level < 0.3:
            return "baseline"
        elif congestion_level < 0.7:
            return "elevated"
        else:
            return "congested"

    def calculate_dynamic_tip_target(self, congestion_level: float, recent_failed_tx_rate: float) -> int:
        """Calculate dynamic tip target in lamports."""
        dynamic_addition = int(self.congestion_multiplier * recent_failed_tx_rate)
        return self.base_tip_lamports + dynamic_addition

    def calculate_tip_efficiency_score(self, estimated_landing_improvement_pct: float, tip_cost_sol: float) -> float:
        """Calculate tip efficiency score."""
        if tip_cost_sol <= 0:
            return 1.0
        efficiency = estimated_landing_improvement_pct / (tip_cost_sol * 10000)
        return min(1.0, max(0.0, efficiency))

    def calculate_landing_pressure_score(self, congestion_level: float) -> float:
        """Calculate landing pressure score."""
        pressure = min(1.0, congestion_level * 0.8)
        return 1.0 - pressure

    def simulate_congestion_data(self, token_context: Dict[str, Any]) -> Dict[str, float]:
        """Simulate congestion data when live data unavailable."""
        # Use heuristic based on token activity and network state
        base_congestion = 0.2  # Default baseline

        # Increase based on recent volume or social activity
        if token_context.get("smart_money_inflows_1h_usd", 0) > 100000:
            base_congestion += 0.3
        if token_context.get("social_velocity_10m", 0) > 50:
            base_congestion += 0.2

        # Cap at 1.0
        congestion_level = min(1.0, base_congestion)

        # Simulate failed tx rate based on congestion
        recent_failed_tx_rate = congestion_level * 0.5

        return {
            "congestion_level": congestion_level,
            "recent_failed_tx_rate": recent_failed_tx_rate
        }

    def build_jito_context(self, token_context: Dict[str, Any], live_data: Optional[Dict[str, Any]] = None) -> JitoPriorityContext:
        """Build JitoPriorityContext from token context and optional live data."""
        if live_data:
            congestion_level = live_data.get("congestion_level", 0.2)
            recent_failed_tx_rate = live_data.get("recent_failed_tx_rate", 0.1)
        else:
            sim_data = self.simulate_congestion_data(token_context)
            congestion_level = sim_data["congestion_level"]
            recent_failed_tx_rate = sim_data["recent_failed_tx_rate"]

        priority_lane = self.classify_priority_lane(congestion_level)
        dynamic_tip_target = self.calculate_dynamic_tip_target(congestion_level, recent_failed_tx_rate)

        # Estimate landing improvement based on priority lane
        landing_improvements = {
            "baseline": 5.0,  # 5% improvement
            "elevated": 15.0,  # 15% improvement
            "congested": 30.0  # 30% improvement
        }
        estimated_landing_improvement_pct = landing_improvements[priority_lane]

        tip_cost_sol = dynamic_tip_target / 1_000_000_000  # Convert lamports to SOL
        tip_efficiency_score = self.calculate_tip_efficiency_score(estimated_landing_improvement_pct, tip_cost_sol)
        landing_pressure_score = self.calculate_landing_pressure_score(congestion_level)

        # Check budget violation
        tip_budget_violation_flag = tip_cost_sol > self.max_budget_sol

        return JitoPriorityContext(
            priority_lane=priority_lane,
            congestion_level=congestion_level,
            recent_failed_tx_rate=recent_failed_tx_rate,
            base_tip_lamports=self.base_tip_lamports,
            dynamic_tip_target_lamports=dynamic_tip_target,
            tip_efficiency_score=tip_efficiency_score,
            landing_pressure_score=landing_pressure_score,
            tip_budget_violation_flag=tip_budget_violation_flag,
            estimated_landing_improvement_pct=estimated_landing_improvement_pct,
            timestamp_sec=int(time.time())
        )