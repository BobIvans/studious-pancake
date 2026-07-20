"""Bounded Jupiter route-attempt scheduling.

The scheduler is deliberately deterministic: it chooses a finite list of quote or
build attempts inside a universal safety envelope.  It never weakens slippage,
program/mint allowlists, freshness, quota reserve or minimum-profit policy.  If
all bounded profiles are exhausted, callers must return NO_TRADE or a retryable
reason rather than keep probing Jupiter.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Iterable, Mapping

from .quota import JupiterQuotaManager, JupiterQuotaPurpose, cache_key


class JupiterAttemptRole(str, Enum):
    DISCOVERY = "discovery"
    REFINEMENT = "refinement"
    FINALIZATION = "finalization"


class JupiterAttemptStopReason(str, Enum):
    READY = "ready"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    STALE_QUOTE = "stale_quote"
    EDGE_BELOW_THRESHOLD = "edge_below_threshold"
    QUOTA_EXHAUSTED = "quota_exhausted"
    ATTEMPT_LIMIT_REACHED = "attempt_limit_reached"


def _required_snapshot_int(snapshot: Mapping[str, object], key: str) -> int:
    """Return a required integer quota snapshot field with mypy-safe narrowing."""

    value = snapshot.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"quota snapshot field {key!r} must be an integer")
    return value


@dataclass(frozen=True)
class JupiterSafetyEnvelope:
    """Invariant policy that a fallback profile cannot relax."""

    max_slippage_bps: int
    max_price_impact_bps: int
    min_net_profit_base_units: int
    max_transaction_bytes: int = 1232
    max_compute_units: int = 1_400_000
    min_quote_ttl_seconds: float = 0.5
    max_quote_age_seconds: float = 2.0
    allow_below_50_accounts: bool = False
    allowed_programs: tuple[str, ...] = ()
    denied_programs: tuple[str, ...] = ()
    allowed_input_mints: tuple[str, ...] = ()
    allowed_output_mints: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.max_slippage_bps < 0:
            raise ValueError("max_slippage_bps must be non-negative")
        if self.max_price_impact_bps < 0:
            raise ValueError("max_price_impact_bps must be non-negative")
        if self.min_net_profit_base_units < 0:
            raise ValueError("min_net_profit_base_units must be non-negative")
        if self.max_transaction_bytes <= 0 or self.max_compute_units <= 0:
            raise ValueError("transaction and compute limits must be positive")
        if self.min_quote_ttl_seconds < 0 or self.max_quote_age_seconds <= 0:
            raise ValueError("quote freshness bounds are invalid")


@dataclass(frozen=True)
class JupiterAttemptProfile:
    name: str
    role: JupiterAttemptRole
    max_accounts: int
    include_dexes: tuple[str, ...] = ()
    exclude_dexes: tuple[str, ...] = ()
    only_direct_routes: bool = False
    request_purpose: JupiterQuotaPurpose = JupiterQuotaPurpose.DISCOVERY
    cache_ttl_seconds: float = 0.25

    def validate_against(self, envelope: JupiterSafetyEnvelope) -> None:
        if self.max_accounts > 64:
            raise ValueError("max_accounts cannot exceed Jupiter composable safety cap 64")
        if self.max_accounts < 50 and not envelope.allow_below_50_accounts:
            raise ValueError("max_accounts below 50 requires explicit envelope policy")
        overlap = set(self.include_dexes).intersection(self.exclude_dexes)
        if overlap:
            raise ValueError(f"profile includes and excludes the same DEXes: {sorted(overlap)}")


@dataclass(frozen=True)
class JupiterRouteAttempt:
    sequence: int
    trace_id: str
    profile: JupiterAttemptProfile
    envelope: JupiterSafetyEnvelope
    reason: str
    cache_key: str

    @property
    def max_accounts(self) -> int:
        return self.profile.max_accounts


@dataclass(frozen=True)
class JupiterRouteAttemptPlan:
    attempts: tuple[JupiterRouteAttempt, ...]
    stop_reason: JupiterAttemptStopReason = JupiterAttemptStopReason.READY

    @property
    def is_exhausted(self) -> bool:
        return self.stop_reason is not JupiterAttemptStopReason.READY or not self.attempts


@dataclass(frozen=True)
class JupiterAttemptContext:
    trace_id: str
    request_fingerprint: str
    now: float
    deadline_at: float
    quote_created_at: float | None = None
    estimated_edge_bps: int | None = None
    min_edge_bps: int = 0
    remaining_profiles: int | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class JupiterAttemptSchedulerConfig:
    account_budget_steps: tuple[int, ...] = (64, 56, 50)
    include_dexes: tuple[str, ...] = ()
    exclude_dexes: tuple[str, ...] = ()
    reserve_finalization_profiles: int = 1
    max_attempts: int = 4
    cache_ttl_seconds: float = 0.25

    def normalized_steps(self, *, allow_below_50_accounts: bool) -> tuple[int, ...]:
        seen: list[int] = []
        for raw in self.account_budget_steps:
            value = int(raw)
            if value > 64:
                value = 64
            if value < 50 and not allow_below_50_accounts:
                continue
            if value not in seen:
                seen.append(value)
        if 64 not in seen:
            seen.insert(0, 64)
        return tuple(seen)


class JupiterRouteAttemptScheduler:
    """Build deterministic attempt plans under quota-aware stop conditions."""

    def __init__(
        self,
        config: JupiterAttemptSchedulerConfig,
        envelope: JupiterSafetyEnvelope,
        quota: JupiterQuotaManager | None = None,
    ) -> None:
        envelope.validate()
        if config.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        self.config = config
        self.envelope = envelope
        self.quota = quota

    def profiles(self) -> tuple[JupiterAttemptProfile, ...]:
        steps = self.config.normalized_steps(
            allow_below_50_accounts=self.envelope.allow_below_50_accounts
        )
        profiles: list[JupiterAttemptProfile] = []
        for index, accounts in enumerate(steps):
            role = (
                JupiterAttemptRole.DISCOVERY
                if index == 0
                else JupiterAttemptRole.REFINEMENT
            )
            purpose = (
                JupiterQuotaPurpose.DISCOVERY
                if role is JupiterAttemptRole.DISCOVERY
                else JupiterQuotaPurpose.REFINEMENT
            )
            profiles.append(
                JupiterAttemptProfile(
                    name=f"{role.value}-max-accounts-{accounts}",
                    role=role,
                    max_accounts=accounts,
                    include_dexes=self.config.include_dexes,
                    exclude_dexes=self.config.exclude_dexes,
                    request_purpose=purpose,
                    cache_ttl_seconds=self.config.cache_ttl_seconds,
                )
            )

        # Finalization is separate so its reserved quota cannot be consumed by
        # exploratory retries.
        for index in range(max(0, self.config.reserve_finalization_profiles)):
            profiles.append(
                JupiterAttemptProfile(
                    name=f"finalization-{index + 1}",
                    role=JupiterAttemptRole.FINALIZATION,
                    max_accounts=steps[-1],
                    include_dexes=self.config.include_dexes,
                    exclude_dexes=self.config.exclude_dexes,
                    request_purpose=JupiterQuotaPurpose.FINALIZATION,
                    cache_ttl_seconds=0.0,
                )
            )
        return tuple(profile for profile in profiles[: self.config.max_attempts])

    def stop_reason(self, context: JupiterAttemptContext) -> JupiterAttemptStopReason:
        if context.now >= context.deadline_at:
            return JupiterAttemptStopReason.DEADLINE_EXCEEDED
        if context.quote_created_at is not None:
            age = context.now - context.quote_created_at
            if age > self.envelope.max_quote_age_seconds:
                return JupiterAttemptStopReason.STALE_QUOTE
        if (
            context.estimated_edge_bps is not None
            and context.estimated_edge_bps < context.min_edge_bps
        ):
            return JupiterAttemptStopReason.EDGE_BELOW_THRESHOLD
        if context.remaining_profiles is not None and context.remaining_profiles <= 0:
            return JupiterAttemptStopReason.ATTEMPT_LIMIT_REACHED
        if self.quota is not None:
            snap = self.quota.snapshot()
            limit = _required_snapshot_int(snap, "limit")
            reserve = _required_snapshot_int(snap, "finalization_reserve")
            occupancy = _required_snapshot_int(snap, "window_occupancy")
            if occupancy >= max(0, limit - reserve):
                return JupiterAttemptStopReason.QUOTA_EXHAUSTED
        return JupiterAttemptStopReason.READY

    def plan(self, context: JupiterAttemptContext) -> JupiterRouteAttemptPlan:
        stop = self.stop_reason(context)
        if stop is not JupiterAttemptStopReason.READY:
            return JupiterRouteAttemptPlan(attempts=(), stop_reason=stop)

        attempts: list[JupiterRouteAttempt] = []
        for sequence, profile in enumerate(self.profiles(), start=1):
            profile.validate_against(self.envelope)
            attempts.append(
                JupiterRouteAttempt(
                    sequence=sequence,
                    trace_id=context.trace_id,
                    profile=profile,
                    envelope=self.envelope,
                    reason="bounded-profile",
                    cache_key=cache_key(
                        (
                            context.request_fingerprint,
                            profile.name,
                            profile.max_accounts,
                            ",".join(profile.include_dexes),
                            ",".join(profile.exclude_dexes),
                        )
                    ),
                )
            )
        return JupiterRouteAttemptPlan(attempts=tuple(attempts))

    def with_profile_failure(
        self,
        failed_profile: JupiterAttemptProfile,
        *,
        reason: str,
    ) -> "JupiterRouteAttemptScheduler":
        """Return a scheduler with one failed profile removed.

        The safety envelope is copied verbatim, so failure handling cannot loosen
        hard policy while searching for the next bounded route profile.
        """

        profiles = [
            profile
            for profile in self.profiles()
            if profile.name != failed_profile.name
        ]
        next_config = replace(
            self.config,
            account_budget_steps=tuple(profile.max_accounts for profile in profiles),
            reserve_finalization_profiles=sum(
                1 for profile in profiles if profile.role is JupiterAttemptRole.FINALIZATION
            ),
        )
        return JupiterRouteAttemptScheduler(next_config, self.envelope, self.quota)


def build_default_scheduler(
    *,
    quota: JupiterQuotaManager | None = None,
    account_budget_steps: Iterable[int] = (64, 56, 50),
    max_slippage_bps: int,
    max_price_impact_bps: int,
    min_net_profit_base_units: int,
) -> JupiterRouteAttemptScheduler:
    """Factory used by runtime composition roots that do not need custom profiles."""

    envelope = JupiterSafetyEnvelope(
        max_slippage_bps=max_slippage_bps,
        max_price_impact_bps=max_price_impact_bps,
        min_net_profit_base_units=min_net_profit_base_units,
    )
    config = JupiterAttemptSchedulerConfig(account_budget_steps=tuple(account_budget_steps))
    return JupiterRouteAttemptScheduler(config, envelope, quota)
