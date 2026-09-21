"""RND-02 PR-354 mechanism-discovery contracts."""

from .core import make_research_function

ingest_reclamm_state = make_research_function("ingest_reclamm_state", "RND-02")
project_reclamm_virtual_balances = make_research_function("project_reclamm_virtual_balances", "RND-02")
project_reclamm_price_range = make_research_function("project_reclamm_price_range", "RND-02")
quote_reclamm_time_surface = make_research_function("quote_reclamm_time_surface", "RND-02")
detect_reclamm_transition_basis = make_research_function("detect_reclamm_transition_basis", "RND-02")
attribute_reclamm_residual = make_research_function("attribute_reclamm_residual", "RND-02")
stress_reclamm_parameter_change = make_research_function("stress_reclamm_parameter_change", "RND-02")
qualify_reclamm_strategy = make_research_function("qualify_reclamm_strategy", "RND-02")

__all__ = [
    "ingest_reclamm_state",
    "project_reclamm_virtual_balances",
    "project_reclamm_price_range",
    "quote_reclamm_time_surface",
    "detect_reclamm_transition_basis",
    "attribute_reclamm_residual",
    "stress_reclamm_parameter_change",
    "qualify_reclamm_strategy"
]
