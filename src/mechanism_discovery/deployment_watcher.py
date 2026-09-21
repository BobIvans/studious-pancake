"""RND-11 PR-354 mechanism-discovery contracts."""

from src.strategy_evolution.residual_discovery import (
    update_anomaly_coverage_registry as canonical_update_anomaly_coverage_registry,
)

from .core import make_research_function

watch_protocol_registry_delta = make_research_function("watch_protocol_registry_delta", "RND-11")
watch_onchain_deployment_delta = make_research_function("watch_onchain_deployment_delta", "RND-11")
classify_semantic_delta = make_research_function("classify_semantic_delta", "RND-11")
score_research_priority = make_research_function("score_research_priority", "RND-11")
quarantine_new_mechanism = make_research_function("quarantine_new_mechanism", "RND-11")
schedule_minimum_data_capture = make_research_function("schedule_minimum_data_capture", "RND-11")
retire_obsolete_mechanism = make_research_function("retire_obsolete_mechanism", "RND-11")
feed_watcher_into_evo09 = make_research_function("feed_watcher_into_evo09", "RND-11")

__all__ = [
    "watch_protocol_registry_delta",
    "watch_onchain_deployment_delta",
    "classify_semantic_delta",
    "score_research_priority",
    "quarantine_new_mechanism",
    "schedule_minimum_data_capture",
    "retire_obsolete_mechanism",
    "feed_watcher_into_evo09"
]
