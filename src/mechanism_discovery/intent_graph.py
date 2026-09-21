"""RND-04 PR-354 mechanism-discovery contracts."""

from .core import make_research_function

attest_intent_resolver = make_research_function("attest_intent_resolver", "RND-04")
resolve_order_requirements = make_research_function("resolve_order_requirements", "RND-04")
compile_intent_dependency_graph = make_research_function("compile_intent_dependency_graph", "RND-04")
normalize_intent_deadlines_and_finality = make_research_function("normalize_intent_deadlines_and_finality", "RND-04")
compare_solver_quotes_same_intent = make_research_function("compare_solver_quotes_same_intent", "RND-04")
estimate_solver_inventory_shadow_cost = make_research_function("estimate_solver_inventory_shadow_cost", "RND-04")
detect_intent_settlement_basis = make_research_function("detect_intent_settlement_basis", "RND-04")
qualify_intent_dialect = make_research_function("qualify_intent_dialect", "RND-04")

__all__ = [
    "attest_intent_resolver",
    "resolve_order_requirements",
    "compile_intent_dependency_graph",
    "normalize_intent_deadlines_and_finality",
    "compare_solver_quotes_same_intent",
    "estimate_solver_inventory_shadow_cost",
    "detect_intent_settlement_basis",
    "qualify_intent_dialect"
]
