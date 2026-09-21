"""RND-09 PR-354 mechanism-discovery contracts."""

from .core import make_research_function

build_collateral_dependency_graph = make_research_function("build_collateral_dependency_graph", "RND-09")
estimate_protocol_exposure_surface = make_research_function("estimate_protocol_exposure_surface", "RND-09")
detect_forced_flow_trigger = make_research_function("detect_forced_flow_trigger", "RND-09")
simulate_contagion_sequence = make_research_function("simulate_contagion_sequence", "RND-09")
estimate_forced_flow_liquidity_depletion = make_research_function("estimate_forced_flow_liquidity_depletion", "RND-09")
detect_post_contagion_residual = make_research_function("detect_post_contagion_residual", "RND-09")
attribute_contagion_episode = make_research_function("attribute_contagion_episode", "RND-09")
qualify_contagion_model = make_research_function("qualify_contagion_model", "RND-09")

__all__ = [
    "build_collateral_dependency_graph",
    "estimate_protocol_exposure_surface",
    "detect_forced_flow_trigger",
    "simulate_contagion_sequence",
    "estimate_forced_flow_liquidity_depletion",
    "detect_post_contagion_residual",
    "attribute_contagion_episode",
    "qualify_contagion_model"
]
