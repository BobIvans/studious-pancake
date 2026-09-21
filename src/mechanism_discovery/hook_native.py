"""RND-01 PR-354 mechanism-discovery contracts."""

from .core import make_research_function

ingest_v4_hook_registry = make_research_function("ingest_v4_hook_registry", "RND-01")
attest_hook_runtime_identity = make_research_function("attest_hook_runtime_identity", "RND-01")
decode_hook_state_machine = make_research_function("decode_hook_state_machine", "RND-01")
simulate_hook_fee_surface = make_research_function("simulate_hook_fee_surface", "RND-01")
simulate_wrapper_hook_parity = make_research_function("simulate_wrapper_hook_parity", "RND-01")
simulate_dualpool_jit_liquidity = make_research_function("simulate_dualpool_jit_liquidity", "RND-01")
detect_hook_cross_venue_residual = make_research_function("detect_hook_cross_venue_residual", "RND-01")
qualify_hook_family = make_research_function("qualify_hook_family", "RND-01")

__all__ = [
    "ingest_v4_hook_registry",
    "attest_hook_runtime_identity",
    "decode_hook_state_machine",
    "simulate_hook_fee_surface",
    "simulate_wrapper_hook_parity",
    "simulate_dualpool_jit_liquidity",
    "detect_hook_cross_venue_residual",
    "qualify_hook_family"
]
