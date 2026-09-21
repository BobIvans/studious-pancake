"""RND-06 PR-354 mechanism-discovery contracts."""

from .core import make_research_function

ingest_umbrella_reserve_state = make_research_function("ingest_umbrella_reserve_state", "RND-06")
project_umbrella_slash_exchange_rate = make_research_function("project_umbrella_slash_exchange_rate", "RND-06")
price_umbrella_reward_slash_basis = make_research_function("price_umbrella_reward_slash_basis", "RND-06")
detect_umbrella_deficit_transition = make_research_function("detect_umbrella_deficit_transition", "RND-06")
model_umbrella_cooldown_liquidity = make_research_function("model_umbrella_cooldown_liquidity", "RND-06")
attribute_umbrella_market_residual = make_research_function("attribute_umbrella_market_residual", "RND-06")
stress_umbrella_multi_reserve_event = make_research_function("stress_umbrella_multi_reserve_event", "RND-06")
qualify_umbrella_specialization = make_research_function("qualify_umbrella_specialization", "RND-06")

__all__ = [
    "ingest_umbrella_reserve_state",
    "project_umbrella_slash_exchange_rate",
    "price_umbrella_reward_slash_basis",
    "detect_umbrella_deficit_transition",
    "model_umbrella_cooldown_liquidity",
    "attribute_umbrella_market_residual",
    "stress_umbrella_multi_reserve_event",
    "qualify_umbrella_specialization"
]
