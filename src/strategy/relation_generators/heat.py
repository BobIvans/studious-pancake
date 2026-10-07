"""Evidence heat and learned quotas; expensive work requires an anomaly trigger."""

from dataclasses import dataclass
import math

from src.discovery.dynamic_universe.universe import Lifecycle


@dataclass(frozen=True)
class HeatInputs:
    executable_depth: float = 0
    independent_venues: int = 0
    structural_anchor: float = 0
    divergence: float = 0
    topology_change: float = 0
    volume_acceleration: float = 0
    recurrence: float = 0
    verification_success: float = 0
    flash_capacity: float = 0
    staleness: float = 0
    source_correlation: float = 0
    shared_liquidity: float = 0
    failure_rate: float = 0
    event_only: bool = False


def heat(inputs: HeatInputs) -> tuple[float, Lifecycle]:
    positive = (
        inputs.executable_depth,
        inputs.structural_anchor,
        inputs.divergence,
        inputs.topology_change,
        inputs.volume_acceleration,
        inputs.recurrence,
        inputs.verification_success,
        inputs.flash_capacity,
    )
    negative = (
        inputs.staleness,
        inputs.source_correlation,
        inputs.shared_liquidity,
        inputs.failure_rate,
    )
    if (
        type(inputs.independent_venues) is not int
        or inputs.independent_venues < 0
        or any(not math.isfinite(x) or x < 0 for x in positive + negative)
    ):
        raise ValueError("invalid heat evidence")
    score = sum(positive) + min(inputs.independent_venues, 8) - sum(negative)
    state = Lifecycle.COLD
    if inputs.event_only:
        state = Lifecycle.EVENT
    elif (
        score >= 8
        and inputs.independent_venues >= 2
        and inputs.recurrence > 0
        and inputs.verification_success > 0
        and inputs.staleness == 0
    ):
        state = Lifecycle.HOT
    elif score >= 3 and inputs.staleness == 0:
        state = Lifecycle.WARM
    return score, state


class HeatScheduler:
    def __init__(self, *, request_budget: int = 32):
        if type(request_budget) is not int or not 1 <= request_budget <= 4096:
            raise ValueError("invalid request cap")
        self.remaining = request_budget
        self.backoff_until: dict[str, float] = {}
        self.failures: dict[str, int] = {}
        self.negative_evidence: list[tuple[str, float, str]] = []

    def observe_failure(
        self,
        provider: str,
        *,
        now: float,
        reason: str,
        retry_after: float | None = None,
    ) -> None:
        if reason not in (
            "rate_limit",
            "timeout",
            "schema_drift",
            "transport_error",
        ) or not math.isfinite(now):
            raise ValueError("invalid negative scheduling evidence")
        if retry_after is not None and (
            not math.isfinite(retry_after) or retry_after < 0
        ):
            raise ValueError("invalid retry window")
        count = min(10, self.failures.get(provider, 0) + 1)
        self.failures[provider] = count
        self.backoff_until[provider] = now + min(300, max(2**count, retry_after or 0))
        self.negative_evidence.append((provider, now, reason))

    def admit(
        self,
        provider: str,
        *,
        priority: int,
        state: Lifecycle,
        anomaly: bool,
        now: float,
    ) -> bool:
        if priority not in range(4) or not math.isfinite(now):
            raise ValueError("invalid scheduler request")
        if (
            self.remaining == 0
            or now < self.backoff_until.get(provider, 0)
            or state == Lifecycle.RETIRED
        ):
            return False
        if priority >= 2 and (
            not anomaly or state not in (Lifecycle.HOT, Lifecycle.WARM, Lifecycle.EVENT)
        ):
            return False
        if state == Lifecycle.EVENT and not anomaly:
            return False
        self.remaining -= 1
        return True
