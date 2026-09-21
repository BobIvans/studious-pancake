"""PR-356 research-only contracts for autonomous market science.

These contracts intentionally contain no network, signer, wallet, submission, or
remote-mutation capability. Monetary/capacity fields are integer atoms or
explicit vectors; incompatible resource dimensions are never collapsed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence


ALLOWED_VERDICTS = frozenset(
    {
        "SUPPORTED_RESEARCH_ONLY",
        "REJECTED_WITH_EVIDENCE",
        "INCONCLUSIVE",
        "BLOCKED_EXTERNAL",
        "SATISFIED_BY_EXISTING",
    }
)
ALLOWED_LABEL_STATUSES = frozenset({"MATURE", "CENSORED", "MISSING", "REJECTED", "NO_TRADE"})
EFFECT_BOUNDARY = {
    "production_ready": False,
    "live_enabled": False,
    "signer_access": False,
    "submission_access": False,
    "wallet_access": False,
    "remote_mutation": False,
    "automatic_promotion": False,
    "automatic_capital_increase": False,
}


class PR356ContractError(ValueError):
    """Fail-closed contract violation."""


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PR356ContractError(f"{field_name.upper()}_REQUIRED")
    return value.strip()


def _int(value: Any, field_name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PR356ContractError(f"{field_name.upper()}_INTEGER_REQUIRED")
    if minimum is not None and value < minimum:
        raise PR356ContractError(f"{field_name.upper()}_BELOW_MINIMUM")
    return value


def canonical_hash(payload: Any) -> str:
    """Hash JSON-safe research evidence deterministically."""
    if hasattr(payload, "__dataclass_fields__"):
        payload = asdict(payload)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CampaignManifest:
    campaign_id: str
    base_sha: str
    hypothesis_ids: tuple[str, ...]
    universe: tuple[str, ...]
    budget_vector: Mapping[str, int]
    train_cutoff: int
    holdout_start: int
    holdout_end: int
    embargo: int
    reject_conditions: tuple[str, ...]
    status: str = "PREREGISTERED"
    execution_right: bool = False

    def __post_init__(self) -> None:
        _text(self.campaign_id, "campaign_id")
        _text(self.base_sha, "base_sha")
        if not self.hypothesis_ids:
            raise PR356ContractError("HYPOTHESIS_IDS_REQUIRED")
        if not self.universe:
            raise PR356ContractError("UNIVERSE_REQUIRED")
        for name, value in self.budget_vector.items():
            _text(name, "budget_dimension")
            _int(value, f"budget_{name}", minimum=0)
        _int(self.train_cutoff, "train_cutoff", minimum=0)
        _int(self.holdout_start, "holdout_start", minimum=0)
        _int(self.holdout_end, "holdout_end", minimum=0)
        _int(self.embargo, "embargo", minimum=0)
        if self.holdout_start <= self.train_cutoff + self.embargo:
            raise PR356ContractError("HOLDOUT_EMBARGO_VIOLATION")
        if self.holdout_end < self.holdout_start:
            raise PR356ContractError("HOLDOUT_RANGE_INVALID")
        if self.execution_right:
            raise PR356ContractError("CAMPAIGN_EXECUTION_RIGHT_FORBIDDEN")

    @property
    def manifest_hash(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True, slots=True)
class MarketEpisodeRecord:
    episode_id: str
    campaign_id: str
    mechanism_id: str
    trigger_available_at: int
    episode_start: int
    episode_end_or_censored: int
    feature_snapshot_hash: str
    label_status: str
    label_available_at: int | None
    outcome_provenance: str | None
    interference_cluster_id: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.episode_id, "episode_id"),
            (self.campaign_id, "campaign_id"),
            (self.mechanism_id, "mechanism_id"),
            (self.feature_snapshot_hash, "feature_snapshot_hash"),
            (self.interference_cluster_id, "interference_cluster_id"),
        ):
            _text(value, name)
        _int(self.trigger_available_at, "trigger_available_at", minimum=0)
        trigger_at = _int(self.trigger_available_at, "trigger_available_at", minimum=0)
        episode_start = _int(self.episode_start, "episode_start", minimum=0)
        episode_end = _int(
            self.episode_end_or_censored,
            "episode_end_or_censored",
            minimum=0,
        )
        if episode_start < trigger_at:
            raise PR356ContractError("EPISODE_START_BEFORE_TRIGGER")
        if episode_end < episode_start:
            raise PR356ContractError("EPISODE_END_BEFORE_START")
        if self.label_status not in ALLOWED_LABEL_STATUSES:
            raise PR356ContractError("LABEL_STATUS_INVALID")
        if self.label_status == "MATURE":
            if self.label_available_at is None or not self.outcome_provenance:
                raise PR356ContractError("MATURE_LABEL_PROVENANCE_REQUIRED")
            label_available_at = _int(
                self.label_available_at,
                "label_available_at",
                minimum=0,
            )
            if label_available_at < episode_end:
                raise PR356ContractError("LABEL_AVAILABLE_BEFORE_EPISODE_END")
        elif self.label_available_at is not None:
            _int(self.label_available_at, "label_available_at", minimum=0)


@dataclass(frozen=True, slots=True)
class ResearchVerdict:
    campaign_id: str
    hypothesis_id: str
    verdict: str
    uncertainty_ppm: int
    blind_spots: tuple[str, ...]
    receipt_hash: str
    execution_right: bool = False

    def __post_init__(self) -> None:
        _text(self.campaign_id, "campaign_id")
        _text(self.hypothesis_id, "hypothesis_id")
        if self.verdict not in ALLOWED_VERDICTS:
            raise PR356ContractError("RESEARCH_VERDICT_INVALID")
        _int(self.uncertainty_ppm, "uncertainty_ppm", minimum=0)
        if self.uncertainty_ppm > 1_000_000:
            raise PR356ContractError("UNCERTAINTY_PPM_INVALID")
        _text(self.receipt_hash, "receipt_hash")
        if self.execution_right:
            raise PR356ContractError("RESEARCH_VERDICT_EXECUTION_RIGHT_FORBIDDEN")


@dataclass(frozen=True, slots=True)
class HypothesisProgram:
    hypothesis_id: str
    mechanism_motif_id: str
    observed_variables: tuple[str, ...]
    latent_variables: tuple[str, ...]
    target: str
    lag: int
    horizon: int
    regime: str
    null_hypothesis: str
    reject_condition: str
    counterexample_class: str
    data_requirements: tuple[str, ...]
    cost_budget: Mapping[str, int]
    holdout_id: str
    execution_right: bool = False

    def __post_init__(self) -> None:
        for value, name in (
            (self.hypothesis_id, "hypothesis_id"),
            (self.mechanism_motif_id, "mechanism_motif_id"),
            (self.target, "target"),
            (self.regime, "regime"),
            (self.null_hypothesis, "null_hypothesis"),
            (self.reject_condition, "reject_condition"),
            (self.counterexample_class, "counterexample_class"),
            (self.holdout_id, "holdout_id"),
        ):
            _text(value, name)
        _int(self.lag, "lag", minimum=0)
        _int(self.horizon, "horizon", minimum=1)
        if not self.observed_variables:
            raise PR356ContractError("OBSERVED_VARIABLES_REQUIRED")
        if self.execution_right:
            raise PR356ContractError("HYPOTHESIS_EXECUTION_RIGHT_FORBIDDEN")


@dataclass(frozen=True, slots=True)
class NegativeKnowledgeCard:
    negative_id: str
    canonical_claim: str
    mechanism_motif: str
    failed_assumptions: tuple[str, ...]
    minimal_counterexample: Mapping[str, Any]
    valid_from: int
    valid_until: int | None
    retest_trigger: str
    rediscovery_count: int = 0

    def __post_init__(self) -> None:
        for value, name in (
            (self.negative_id, "negative_id"),
            (self.canonical_claim, "canonical_claim"),
            (self.mechanism_motif, "mechanism_motif"),
            (self.retest_trigger, "retest_trigger"),
        ):
            _text(value, name)
        _int(self.valid_from, "valid_from", minimum=0)
        _int(self.rediscovery_count, "rediscovery_count", minimum=0)
        if self.valid_until is not None and self.valid_until < self.valid_from:
            raise PR356ContractError("NEGATIVE_KNOWLEDGE_VALIDITY_INVALID")


@dataclass(frozen=True, slots=True)
class AgentArchetype:
    archetype_id: str
    role: str
    market_scope: tuple[str, ...]
    information_set: tuple[str, ...]
    action_space: tuple[str, ...]
    inventory_capital_constraints: Mapping[str, int]
    risk_limits: Mapping[str, int]
    execution_rights: tuple[str, ...] = ()
    uncertainty_ppm: int = 1_000_000

    def __post_init__(self) -> None:
        _text(self.archetype_id, "archetype_id")
        _text(self.role, "role")
        _int(self.uncertainty_ppm, "uncertainty_ppm", minimum=0)
        forbidden = {"SIGN", "SUBMIT", "FUND", "LIVE_TRADE", "REMOTE_MUTATE"}
        if forbidden.intersection({item.upper() for item in self.execution_rights}):
            raise PR356ContractError("AGENT_TRADING_AUTHORITY_FORBIDDEN")


@dataclass(frozen=True, slots=True)
class StrategyEvidenceCard:
    strategy_id: str
    strategy_version: str
    mechanism_scope: tuple[str, ...]
    time_domain: str
    evidence_tier: str
    oos_metrics: Mapping[str, int]
    capacity_curve: tuple[tuple[int, int], ...]
    cost_curve: tuple[tuple[int, int], ...]
    uncertainty_components: Mapping[str, int]
    access_constraints: tuple[str, ...]
    valid_from: int
    valid_until: int
    execution_right: bool = False

    def __post_init__(self) -> None:
        _text(self.strategy_id, "strategy_id")
        _text(self.strategy_version, "strategy_version")
        _text(self.time_domain, "time_domain")
        _text(self.evidence_tier, "evidence_tier")
        if self.valid_until < self.valid_from:
            raise PR356ContractError("STRATEGY_EVIDENCE_VALIDITY_INVALID")
        if self.execution_right:
            raise PR356ContractError("STRATEGY_EXECUTION_RIGHT_FORBIDDEN")


@dataclass(frozen=True, slots=True)
class ResourceClaimVector:
    claim_id: str
    capital_by_asset: Mapping[str, int] = field(default_factory=dict)
    fee_reserve: int = 0
    rent_or_account_capital: int = 0
    margin_collateral: Mapping[str, int] = field(default_factory=dict)
    borrow_capacity: Mapping[str, int] = field(default_factory=dict)
    data_quota: Mapping[str, int] = field(default_factory=dict)
    compute_seconds: int = 0
    simulation_slots: int = 0
    storage_bytes: int = 0
    human_review: int = 0
    conflict_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.claim_id, "claim_id")
        for mapping_name in ("capital_by_asset", "margin_collateral", "borrow_capacity", "data_quota"):
            mapping = getattr(self, mapping_name)
            for unit, value in mapping.items():
                _text(unit, f"{mapping_name}_unit")
                _int(value, f"{mapping_name}_{unit}", minimum=0)
        for name in ("fee_reserve", "rent_or_account_capital", "compute_seconds", "simulation_slots", "storage_bytes", "human_review"):
            _int(getattr(self, name), name, minimum=0)


@dataclass(frozen=True, slots=True)
class AllocationProposal:
    proposal_id: str
    candidate_ids: tuple[str, ...]
    weights_or_sizes: Mapping[str, int]
    resource_usage: Mapping[str, Any]
    expected_utility_units: int
    tail_loss_units: int
    binding_constraints: tuple[str, ...]
    rejected_candidates: tuple[str, ...]
    sensitivity_ppm: int
    evidence_refs: tuple[str, ...]
    execution_right: bool = False

    def __post_init__(self) -> None:
        _text(self.proposal_id, "proposal_id")
        _int(self.expected_utility_units, "expected_utility_units")
        _int(self.tail_loss_units, "tail_loss_units", minimum=0)
        _int(self.sensitivity_ppm, "sensitivity_ppm", minimum=0)
        if self.execution_right:
            raise PR356ContractError("ALLOCATION_EXECUTION_RIGHT_FORBIDDEN")
