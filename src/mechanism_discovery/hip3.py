"""RND-08 PR-354 mechanism-discovery contracts."""

from .core import make_research_function

ingest_hip3_dex_config = make_research_function("ingest_hip3_dex_config", "RND-08")
track_hip3_config_transition = make_research_function("track_hip3_config_transition", "RND-08")
normalize_hip3_oracle_basis = make_research_function("normalize_hip3_oracle_basis", "RND-08")
model_hip3_funding_oi_constraint = make_research_function("model_hip3_funding_oi_constraint", "RND-08")
detect_hip3_halt_resume_residual = make_research_function("detect_hip3_halt_resume_residual", "RND-08")
detect_hip3_cross_dex_basis = make_research_function("detect_hip3_cross_dex_basis", "RND-08")
attribute_hip3_deployer_regime = make_research_function("attribute_hip3_deployer_regime", "RND-08")
qualify_hip3_specialization = make_research_function("qualify_hip3_specialization", "RND-08")

__all__ = [
    "ingest_hip3_dex_config",
    "track_hip3_config_transition",
    "normalize_hip3_oracle_basis",
    "model_hip3_funding_oi_constraint",
    "detect_hip3_halt_resume_residual",
    "detect_hip3_cross_dex_basis",
    "attribute_hip3_deployer_regime",
    "qualify_hip3_specialization"
]
