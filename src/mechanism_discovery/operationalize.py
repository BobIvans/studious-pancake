"""RND-00 PR-354 mechanism-discovery contracts."""

from src.strategy_evolution.residual_discovery import (
    update_anomaly_coverage_registry as canonical_update_anomaly_coverage_registry,
)

from .core import make_research_function

bind_concrete_source_to_evo = make_research_function("bind_concrete_source_to_evo", "RND-00")
capture_evo_point_in_time_corpus = make_research_function("capture_evo_point_in_time_corpus", "RND-00")
join_real_bot_operations = make_research_function("join_real_bot_operations", "RND-00")
build_evo_replay_fixture = make_research_function("build_evo_replay_fixture", "RND-00")
run_evo_source_ablation = make_research_function("run_evo_source_ablation", "RND-00")
run_evo_walk_forward = make_research_function("run_evo_walk_forward", "RND-00")
measure_evo_coverage = make_research_function("measure_evo_coverage", "RND-00")
publish_evo_qualification_verdict = make_research_function("publish_evo_qualification_verdict", "RND-00")

__all__ = [
    "bind_concrete_source_to_evo",
    "capture_evo_point_in_time_corpus",
    "join_real_bot_operations",
    "build_evo_replay_fixture",
    "run_evo_source_ablation",
    "run_evo_walk_forward",
    "measure_evo_coverage",
    "publish_evo_qualification_verdict"
]
