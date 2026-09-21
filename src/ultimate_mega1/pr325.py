"""PR-325 / NF-1007..1011: interference-aware shadow experiment cohorts."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Mapping, Sequence

from .core import ContractResult, UltimateMegaError, record, require_nonnegative, require_positive, stable_hash


def construct_experiment_interference_graph(
    episode_resources: Mapping[str, Sequence[str]],
    *,
    dependency_coverage_known: bool,
) -> ContractResult:
    if not dependency_coverage_known:
        raise UltimateMegaError("DEPENDENCY_COVERAGE_UNKNOWN")
    resources_to_eps: dict[str, list[str]] = defaultdict(list)
    for episode, resources in episode_resources.items():
        for resource in resources:
            resources_to_eps[str(resource)].append(str(episode))
    adjacency: dict[str, set[str]] = {str(ep): set() for ep in episode_resources}
    for episodes in resources_to_eps.values():
        for left in episodes:
            adjacency[left].update(ep for ep in episodes if ep != left)
    return record(
        "construct_experiment_interference_graph",
        {"adjacency": {k: tuple(sorted(v)) for k, v in sorted(adjacency.items())}, "resource_count": len(resources_to_eps)},
    )


def assign_resource_cluster_experiment(
    adjacency: Mapping[str, Sequence[str]],
    *,
    arms: Sequence[str],
    assignment_seed: str,
    washout_seconds: int,
    live_exploration: bool = False,
) -> ContractResult:
    if live_exploration:
        raise UltimateMegaError("LIVE_EXPLORATION_NOT_AUTHORIZED")
    if len(arms) < 2:
        raise UltimateMegaError("EXPERIMENT_ARMS_REQUIRED")
    washout = require_nonnegative(washout_seconds, "washout_seconds")
    unseen = set(adjacency)
    components = []
    while unseen:
        start = min(unseen)
        queue = deque([start])
        unseen.remove(start)
        component = []
        while queue:
            node = queue.popleft()
            component.append(node)
            for nxt in adjacency.get(node, ()):
                if nxt in unseen:
                    unseen.remove(nxt)
                    queue.append(nxt)
        components.append(tuple(sorted(component)))
    assignments = []
    for idx, component in enumerate(sorted(components)):
        digest = int(stable_hash("experiment-assignment", (assignment_seed, component)), 16)
        assignments.append((component, arms[digest % len(arms)]))
    return record(
        "assign_resource_cluster_experiment",
        {"assignments": tuple(assignments), "washout_seconds": washout, "randomization_recorded": True, "live": False},
    )


def detect_cross_arm_contamination(
    assignments: Sequence[tuple[Sequence[str], str]],
    shared_updates: Mapping[str, Sequence[str]],
) -> ContractResult:
    episode_arm = {}
    for episodes, arm in assignments:
        for episode in episodes:
            episode_arm[str(episode)] = arm
    contaminated = []
    for update_id, episodes in shared_updates.items():
        arms = {episode_arm.get(str(ep)) for ep in episodes if str(ep) in episode_arm}
        if len(arms) > 1:
            contaminated.append(str(update_id))
    return record(
        "detect_cross_arm_contamination",
        {"contaminated_updates": tuple(sorted(contaminated)), "clean_holdout": not contaminated},
        status="INCOMPLETE" if contaminated else "OK",
        blockers=("UNTRACEABLE_SHARED_STATE",) if contaminated else (),
    )


def estimate_cluster_aware_effects(
    *,
    treatment_outcomes: Sequence[int],
    control_outcomes: Sequence[int],
) -> ContractResult:
    if len(treatment_outcomes) < 2 or len(control_outcomes) < 2:
        raise UltimateMegaError("TOO_FEW_INDEPENDENT_GROUPS")
    t = [int(x) for x in treatment_outcomes]
    c = [int(x) for x in control_outcomes]
    t_mean_num = sum(t)
    c_mean_num = sum(c)
    effect_num = t_mean_num * len(c) - c_mean_num * len(t)
    effect_den = len(t) * len(c)
    return record(
        "estimate_cluster_aware_effects",
        {"treatment_clusters": len(t), "control_clusters": len(c), "effect_fraction": (effect_num, effect_den), "observation_unit": "RESOURCE_CLUSTER"},
    )


def publish_interference_sensitivity(
    *,
    baseline_effect_fraction: tuple[int, int],
    alternative_effect_fractions: Sequence[tuple[int, int]],
) -> ContractResult:
    base_num, base_den = baseline_effect_fraction
    base_den = require_positive(base_den, "base_den")
    base_sign = (base_num > 0) - (base_num < 0)
    unstable = False
    normalized = []
    for num, den in alternative_effect_fractions:
        den = require_positive(den, "den")
        normalized.append((int(num), den))
        sign = (num > 0) - (num < 0)
        if sign != base_sign:
            unstable = True
    return record(
        "publish_interference_sensitivity",
        {"baseline_effect_fraction": (int(base_num), base_den), "alternatives": tuple(normalized), "sign_stable": not unstable},
        status="INCOMPLETE" if unstable else "OK",
        blockers=("UNIDENTIFIED_SPILLOVER",) if unstable else (),
    )
