"""Deterministic discovery fanout with one shared cycle budget."""

from dataclasses import dataclass
from itertools import combinations


@dataclass(frozen=True, slots=True)
class DiscoveryLimits:
    max_tokens: int = 16
    max_pairs: int = 64
    max_providers: int = 4
    max_amounts: int = 8
    max_requests: int = 128
    max_candidates: int = 64
    deadline_ms: int = 5_000

    def __post_init__(self) -> None:
        if any(
            type(x) is not int or x <= 0
            for x in (
                self.max_tokens,
                self.max_pairs,
                self.max_providers,
                self.max_amounts,
                self.max_requests,
                self.max_candidates,
                self.deadline_ms,
            )
        ):
            raise ValueError("discovery limits must be positive integers")


@dataclass(frozen=True, order=True, slots=True)
class DiscoveryRequest:
    input_asset: str
    output_asset: str
    amount: int
    provider: str


def bounded_requests(
    *,
    tokens: tuple[str, ...],
    amounts: tuple[int, ...],
    providers: tuple[str, ...],
    limits: DiscoveryLimits,
) -> tuple[DiscoveryRequest, ...]:
    """Return a stable prefix; never allocate tasks or a P² provider graph."""
    clean_tokens = tuple(sorted(set(tokens)))
    clean_amounts = tuple(sorted(set(amounts)))
    clean_providers = tuple(sorted(set(providers)))
    if (
        len(clean_tokens) > limits.max_tokens
        or len(clean_amounts) > limits.max_amounts
        or len(clean_providers) > limits.max_providers
    ):
        raise ValueError("discovery input exceeds configured bound")
    if any(type(x) is not int or x <= 0 or x > 2**64 - 1 for x in clean_amounts):
        raise ValueError("invalid discovery amount")
    pairs = tuple(combinations(clean_tokens, 2))
    if len(pairs) > limits.max_pairs:
        raise ValueError("pair fanout exceeds configured bound")
    result: list[DiscoveryRequest] = []
    # Provider is the inner dimension so truncation fairly rotates providers.
    for pair in pairs:
        for amount in clean_amounts:
            for provider in clean_providers:
                if len(result) == limits.max_requests:
                    return tuple(result)
                result.append(DiscoveryRequest(pair[0], pair[1], amount, provider))
    return tuple(result)
