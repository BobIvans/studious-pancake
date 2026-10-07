"""Evidence-bound MarketEpisode projection with point-in-time stage features."""

from dataclasses import asdict
from src.agg02.storage import DurableRawJournal
from src.market.observations import MarketObservationV2
from src.market_data_evolution.contracts import MarketEpisode
from src.decision.dataset import validate_pre_quote_features
from .common import seal
from .experiment_manifest import verify_experiment_identity

STAGES = (
    "PRE_QUOTE",
    "QUOTE",
    "SIZING",
    "PLANNER",
    "COMPILER",
    "SIMULATION",
    "RECONCILIATION",
    "PAPER_OUTCOME",
)


def link_stage_evidence(
    decisions: list[dict], observations: dict[str, dict]
) -> list[dict]:
    result = []
    for decision in decisions:
        required = {
            "decision_id",
            "stage",
            "available_at_ms",
            "source_refs",
            "features",
            "action",
            "reason_code",
            "thresholds",
            "strategy_id",
            "strategy_version",
        }
        if not required <= decision.keys() or decision["stage"] not in STAGES:
            raise ValueError("incomplete typed stage evidence")
        cutoff = decision["available_at_ms"]
        if type(cutoff) is not int or cutoff < 0:
            raise ValueError("stage availability required")
        if decision["stage"] == "PRE_QUOTE":
            validate_pre_quote_features(decision["features"])
        for source in decision["source_refs"]:
            if (
                source not in observations
                or observations[source]["available_at_ms"] > cutoff
            ):
                raise ValueError("future or unknown stage evidence")
        if decision["action"] == "REJECT" and not decision["reason_code"]:
            raise ValueError("stable rejection reason required")
        result.append(dict(decision))
    if len({r["decision_id"] for r in result}) != len(result):
        raise ValueError("duplicate stage decision")
    return sorted(
        result,
        key=lambda r: (
            r["available_at_ms"],
            STAGES.index(r["stage"]),
            r["decision_id"],
        ),
    )


def link_negative_examples(decisions: list[dict]) -> list[dict]:
    return [r for r in decisions if r["action"] == "REJECT"]


def build_market_episode(
    episode: MarketEpisode,
    *,
    experiment: dict,
    observations: list[dict],
    decisions: list[dict],
    journal: DurableRawJournal,
    raw_event_ids: list[str],
    market_observations: tuple[MarketObservationV2, ...] = (),
    candidate_id: str | None = None,
    resource_usage: dict | None = None,
) -> dict:
    verify_experiment_identity(experiment)
    by_id = {r["observation_id"]: r for r in observations}
    if len(by_id) != len(observations) or not by_id or not raw_event_ids:
        raise ValueError("unique observation and raw lineage required")
    for observation in observations:
        if type(observation.get("available_at_ms")) is not int:
            raise ValueError("observation availability required")
        if observation["available_at_ms"] > episode.feature_available_at:
            raise ValueError("episode feature lookahead")
        linked = observation.get("raw_event_ids", [])
        if not linked or not set(linked) <= set(raw_event_ids):
            raise ValueError("observation raw lineage missing")
    known_raw = {
        r["event_id"]: r
        for r in journal.iter_retention_rows(event_ids=set(raw_event_ids))
    }
    if set(known_raw) != set(raw_event_ids):
        raise ValueError("raw lineage not in AGG-02 owner")
    stages = link_stage_evidence(decisions, by_id)
    if any(
        r["stage"] == "PAPER_OUTCOME"
        and (
            episode.label_available_at is None
            or r["available_at_ms"] < episode.label_available_at
        )
        for r in stages
    ):
        raise ValueError("terminal outcome lookahead")
    canonical_market = [
        {
            **asdict(o),
            "observation_id": o.observation_id,
            "generation_identity": o.generation.identity,
        }
        for o in market_observations
    ]
    payload = {
        "schema": "studious.episode-lineage.v2",
        "episode": asdict(episode),
        "experiment_identity": experiment,
        "candidate_id": candidate_id,
        "observations": observations,
        "market_observations": canonical_market,
        "decisions": stages,
        "negative_examples": link_negative_examples(stages),
        "raw_event_ids": sorted(set(raw_event_ids)),
        "raw_source_refs": [
            {k: v for k, v in row.items() if k not in {"payload", "envelope_json"}}
            for row in known_raw.values()
        ],
        "resource_usage": resource_usage,
        "live_authorized": False,
    }
    receipt = seal(payload)
    journal.pin_retention(raw_event_ids, evidence_id=receipt["receipt_sha256"])
    return receipt
