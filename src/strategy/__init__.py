"""Strategy runtime package."""
from .detectors import CircularArbitrageDetector, DetectorPair
from .domain import Opportunity
from .interfaces import Strategy, StrategyMode, StrategyContext
from .opportunity_identity import (
    DedupAdmission,
    LogicalOpportunityIdentity,
    OpportunityIdentityError,
    PersistentOpportunityDedupLedger,
    build_logical_opportunity_identity,
)
from .registry import StrategyRegistry
from .runtime import StrategyRuntime, TaskSupervisor
from .queue import OpportunityQueue

__all__ = [
    "Opportunity",
    "Strategy",
    "StrategyMode",
    "StrategyContext",
    "StrategyRegistry",
    "StrategyRuntime",
    "TaskSupervisor",
    "OpportunityQueue",
    "CircularArbitrageDetector",
    "DetectorPair",
    "DedupAdmission",
    "LogicalOpportunityIdentity",
    "OpportunityIdentityError",
    "PersistentOpportunityDedupLedger",
    "build_logical_opportunity_identity",
]
