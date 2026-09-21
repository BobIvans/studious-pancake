"""RND-05 PR-354 mechanism-discovery contracts."""

from .core import make_research_function

ingest_fluid_liquidity_layer = make_research_function("ingest_fluid_liquidity_layer", "RND-05")
ingest_fluid_dex_state = make_research_function("ingest_fluid_dex_state", "RND-05")
model_smart_collateral_debt_coupling = make_research_function("model_smart_collateral_debt_coupling", "RND-05")
quote_fluid_liquidation_swap = make_research_function("quote_fluid_liquidation_swap", "RND-05")
model_fluid_steth_redemption = make_research_function("model_fluid_steth_redemption", "RND-05")
detect_fluid_utilization_transition = make_research_function("detect_fluid_utilization_transition", "RND-05")
detect_fluid_cross_protocol_residual = make_research_function("detect_fluid_cross_protocol_residual", "RND-05")
qualify_fluid_family = make_research_function("qualify_fluid_family", "RND-05")

__all__ = [
    "ingest_fluid_liquidity_layer",
    "ingest_fluid_dex_state",
    "model_smart_collateral_debt_coupling",
    "quote_fluid_liquidation_swap",
    "model_fluid_steth_redemption",
    "detect_fluid_utilization_transition",
    "detect_fluid_cross_protocol_residual",
    "qualify_fluid_family"
]
