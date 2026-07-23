"""Bounded Jupiter route-attempt scheduling.

The scheduler is deterministic and purpose-aware. Optional discovery and
refinement profiles can be skipped when their shared budget is full while
proof-critical finalization remains eligible for the reserved quota.
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
    """Return a required integer quota snapshot field."""

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
            raise ValueError(
                "max_accounts cannot exceed Jupiter composable safety cap 64"
            )
        if self.max_accounts < 50 and not envelope.allow_below_50_accounts:
            raise ValueError("max_accounts below 50 requires explicit envelope policy")
        overlap = set(self.include_dexes).intersection(self.exclude_dexes)
        if overlap:
            raise ValueError(
                f"profile includes and excludes the same DEXes: {sorted(overlap)}"
            )


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
    quota_skipped_profiles: tuple[str, ...] = ()

    @property
    def is_exhausted(self) -> bool:
        return (
            self.stop_reason is not JupiterAttemptStopReason.READY or not self.attempts
        )


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

    def validate(self) -> None:
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if self.reserve_finalization_profiles <= 0:
            raise ValueError("at least one finalization profile is required")
        if self.reserve_finalization_profiles > self.max_attempts:
            raise ValueError("max_attempts cannot truncate all finalization profiles")
        if self.cache_ttl_seconds < 0:
            raise ValueError("cache_ttl_seconds must be non-negative")


class JupiterRouteAttemptScheduler:
    """Build deterministic attempt plans under purpose-aware quota limits."""

    def __init__(
        self,
        config: JupiterAttemptSchedulerConfig,
        envelope: JupiterSafetyEnvelope,
        quota: JupiterQuotaManager | None = None,
    ) -> None:
        envelope.validate()
        config.validate()
        self.config = config
        self.envelope = envelope
        self.quota = quota

    def profiles(self) -> tuple[JupiterAttemptProfile, ...]:
        steps = self.config.normalized_steps(
            allow_below_50_accounts=self.envelope.allow_below_50_accounts
        )
        optional_profiles: list[JupiterAttemptProfile] = []
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
            optional_profiles.append(
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

        finalization_profiles = [
            JupiterAttemptProfile(
                name=f"finalization-{index + 1}",
                role=JupiterAttemptRole.FINALIZATION,
                max_accounts=steps[-1],
                include_dexes=self.config.include_dexes,
                exclude_dexes=self.config.exclude_dexes,
                request_purpose=JupiterQuotaPurpose.FINALIZATION,
                cache_ttl_seconds=0.0,
            )
            for index in range(self.config.reserve_finalization_profiles)
        ]
        optional_limit = self.config.max_attempts - len(finalization_profiles)
        return tuple(optional_profiles[:optional_limit] + finalization_profiles)

    def _context_stop_reason(
        self, context: JupiterAttemptContext
    ) -> JupiterAttemptStopReason:
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
        return JupiterAttemptStopReason.READY

    def _purpose_has_capacity(
        self,
        purpose: JupiterQuotaPurpose,
        snapshot: Mapping[str, object],
    ) -> bool:
        limit = _required_snapshot_int(snapshot, "limit")
        reserve = _required_snapshot_int(snapshot, "finalization_reserve")
        occupancy = _required_snapshot_int(snapshot, "window_occupancy")
        if purpose is JupiterQuotaPurpose.FINALIZATION:
            return occupancy < limit
        return occupancy < max(0, limit - reserve)

    def _eligible_profiles(
        self,
    ) -> tuple[tuple[JupiterAttemptProfile, ...], tuple[str, ...]]:
        profiles = self.profiles()
        if self.quota is None:
            return profiles, ()
        snapshot = self.quota.snapshot()
        eligible: list[JupiterAttemptProfile] = []
        skipped: list[str] = []
        for profile in profiles:
            if self._purpose_has_capacity(profile.request_purpose, snapshot):
                eligible.append(profile)
            else:
                skipped.append(profile.name)
        return tuple(eligible), tuple(skipped)

    def stop_reason(self, context: JupiterAttemptContext) -> JupiterAttemptStopReason:
        stop = self._context_stop_reason(context)
        if stop is not JupiterAttemptStopReason.READY:
            return stop
        eligible, _ = self._eligible_profiles()
        if not eligible:
            return JupiterAttemptStopReason.QUOTA_EXHAUSTED
        return JupiterAttemptStopReason.READY

    def plan(self, context: JupiterAttemptContext) -> JupiterRouteAttemptPlan:
        stop = self._context_stop_reason(context)
        if stop is not JupiterAttemptStopReason.READY:
            return JupiterRouteAttemptPlan(attempts=(), stop_reason=stop)

        profiles, skipped = self._eligible_profiles()
        if not profiles:
            return JupiterRouteAttemptPlan(
                attempts=(),
                stop_reason=JupiterAttemptStopReason.QUOTA_EXHAUSTED,
                quota_skipped_profiles=skipped,
            )

        attempts: list[JupiterRouteAttempt] = []
        for sequence, profile in enumerate(profiles, start=1):
            profile.validate_against(self.envelope)
            attempts.append(
                JupiterRouteAttempt(
                    sequence=sequence,
                    trace_id=context.trace_id,
                    profile=profile,
                    envelope=self.envelope,
                    reason="bounded-purpose-eligible-profile",
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
        return JupiterRouteAttemptPlan(
            attempts=tuple(attempts), quota_skipped_profiles=skipped
        )

    def with_profile_failure(
        self,
        failed_profile: JupiterAttemptProfile,
        *,
        reason: str,
    ) -> "JupiterRouteAttemptScheduler":
        """Remove a failed optional profile without relaxing finalization policy."""

        profiles = [
            profile
            for profile in self.profiles()
            if profile.name != failed_profile.name
        ]
        finalization_count = sum(
            1 for profile in profiles if profile.role is JupiterAttemptRole.FINALIZATION
        )
        if finalization_count <= 0:
            raise ValueError("profile failure cannot remove every finalization profile")
        optional_steps = tuple(
            profile.max_accounts
            for profile in profiles
            if profile.role is not JupiterAttemptRole.FINALIZATION
        )
        next_config = replace(
            self.config,
            account_budget_steps=optional_steps or self.config.account_budget_steps,
            reserve_finalization_profiles=finalization_count,
            max_attempts=len(profiles),
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
    """Build the default purpose-aware route scheduler."""

    envelope = JupiterSafetyEnvelope(
        max_slippage_bps=max_slippage_bps,
        max_price_impact_bps=max_price_impact_bps,
        min_net_profit_base_units=min_net_profit_base_units,
    )
    config = JupiterAttemptSchedulerConfig(
        account_budget_steps=tuple(account_budget_steps)
    )
    return JupiterRouteAttemptScheduler(config, envelope, quota)
