"""PR-022 decision-intelligence contracts: advisory-only, offline-safe."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

SCHEMA_VERSION = "decision-row/v1"
FEATURE_SPEC_VERSION = "pre_quote/v1"
MODEL_ARTIFACT_VERSION = "decision-linear/v1"


class DecisionStage(str, Enum):
    PRE_QUOTE = "PRE_QUOTE"


class ModelStatus(str, Enum):
    BASELINE_ONLY = "BASELINE_ONLY"
    MODEL_DISABLED = "MODEL_DISABLED"
    DISABLED_INSUFFICIENT_DATA = "DISABLED_INSUFFICIENT_DATA"
    REJECTED_FOR_SHADOW = "REJECTED_FOR_SHADOW"
    SHADOW_CHALLENGER = "SHADOW_CHALLENGER"


class RecommendedBand(str, Enum):
    PRIORITIZE = "PRIORITIZE"
    NEUTRAL = "NEUTRAL"
    DEPRIORITIZE = "DEPRIORITIZE"
    BASELINE_ONLY = "BASELINE_ONLY"


ALLOWED_PRE_QUOTE_FEATURES: Mapping[str, str] = {
    "strategy_family": "category: allowlisted strategy family known at candidate observation",
    "opportunity_type": "category: detector class known at candidate observation",
    "route_shape_class": "category: deterministic route-shape class, not raw route",
    "market_category": "category: versioned allowlisted market/mint category",
    "candidate_age_ms": "integer milliseconds since source observation at PRE_QUOTE",
    "slot_age": "integer source slot age at PRE_QUOTE",
    "provider_health": "category: healthy|degraded|circuit_open|unknown snapshot known then",
    "quota_band": "category: available|tight|exhausted|unknown snapshot known then",
    "capacity_status": "category: pass|deny|unknown cheap canonical status before quote",
    "complexity_profile": "category: low|medium|high|unknown pre-build estimate",
    "token2022_flag": "category: yes|no|unknown capability flag",
    "historical_success_rate_ppm": "integer ppm rolling aggregate from strictly earlier terminal events",
    "historical_reject_rate_ppm": "integer ppm rolling aggregate from strictly earlier terminal events",
}
FORBIDDEN_PRE_QUOTE_TOKENS = (
    "pnl",
    "profit_sol",
    "final",
    "simulation",
    "terminal",
    "log",
    "balance",
    "repayment",
    "landing",
    "send",
    "signature",
    "UI amount",
    "virtual balance",
    "private credential",
    "signing credential",
    "legacy_score",
    "score_float",
    "quote_output",
)


@dataclass(frozen=True, slots=True)
class RankingRecommendation:
    artifact_version: str | None
    stage: DecisionStage
    probability: float | None
    baseline_priority: int
    recommended_band: RecommendedBand
    explanations: tuple[str, ...] = field(default_factory=tuple)
    model_status: ModelStatus = ModelStatus.BASELINE_ONLY
    artifact_checksum: str | None = None
    feature_spec_version: str = FEATURE_SPEC_VERSION
    advisory_only: str = (
        "advisory shadow rank only; deterministic gates remain authoritative"
    )


@dataclass(frozen=True, slots=True)
class DecisionFeatureRow:
    row_id: str
    root_opportunity_id: str
    lineage_group_id: str
    candidate_observed_at: str
    source_slot: int
    observation_sequence: int
    available_at_stage: DecisionStage
    features_pre_quote: Mapping[str, Any]
    label_status: str
    label_value: int | None
    terminal_timestamp: str | None
    source_event_ids: tuple[str, ...]
    source_event_hashes: tuple[str, ...]
    row_quality: str = "OK"
    exclusion_reason: str | None = None
