"""RND-07 PR-354 mechanism-discovery contracts."""

from .core import make_research_function

ingest_stvault_identity_and_roles = make_research_function("ingest_stvault_identity_and_roles", "RND-07")
ingest_stvault_metrics_and_quarantine = make_research_function("ingest_stvault_metrics_and_quarantine", "RND-07")
model_stvault_steth_liquidity = make_research_function("model_stvault_steth_liquidity", "RND-07")
model_validator_operator_basis = make_research_function("model_validator_operator_basis", "RND-07")
detect_quarantine_liquidity_basis = make_research_function("detect_quarantine_liquidity_basis", "RND-07")
detect_stvault_fee_term_basis = make_research_function("detect_stvault_fee_term_basis", "RND-07")
stress_stvault_withdrawal_shortfall = make_research_function("stress_stvault_withdrawal_shortfall", "RND-07")
qualify_stvault_specialization = make_research_function("qualify_stvault_specialization", "RND-07")

__all__ = [
    "ingest_stvault_identity_and_roles",
    "ingest_stvault_metrics_and_quarantine",
    "model_stvault_steth_liquidity",
    "model_validator_operator_basis",
    "detect_quarantine_liquidity_basis",
    "detect_stvault_fee_term_basis",
    "stress_stvault_withdrawal_shortfall",
    "qualify_stvault_specialization"
]
