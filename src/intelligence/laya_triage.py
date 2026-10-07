"""Optional typed compact-state Laya adapter. It has no mutation capability."""

from collections.abc import Callable
from importlib.resources import files
import json
from pathlib import Path
from .common import canonical, digest
from .laya_cache import decision_cache_key, load_cached_decision, store_decision_receipt

PROMPT_VERSION = "studious.laya-retention.v2"
ALLOWED = {
    "event_id",
    "episode_id",
    "group_id",
    "source_id",
    "available_at_ms",
    "candidate_id",
    "reason_code",
    "stage",
    "delta_atoms",
    "counts",
    "source_refs",
    "data_quality",
    "resource_usage",
    "goal",
    "assumptions",
    "recent_exemplars",
    "retention_class",
    "novelty_features",
    "learning_features",
    "paths",
}


def build_compact_state(record: dict, *, kind: str, max_bytes: int = 16_384) -> dict:
    if kind not in {"observation", "episode", "repo_group"}:
        raise ValueError("unsupported triage state")
    state = {"kind": kind, "state": {k: v for k, v in record.items() if k in ALLOWED}}
    if len(canonical(state)) > max_bytes:
        raise ValueError("compact state budget exceeded; retrieve fewer exemplars")
    return state


def _questions(kind: str) -> list[dict]:
    contract = json.loads(
        files("src.resources")
        .joinpath("local_intelligence_laya_questions_v2.json")
        .read_text(encoding="utf-8")
    )
    return contract[kind + "_state"]


def validate_decision(decision: dict, kind: str) -> dict:
    questions = _questions(kind)
    expected = {q["id"] for q in questions} | {"confidence"}
    if set(decision) != expected:
        raise ValueError("typed advisory response fields mismatch")
    confidence = decision["confidence"]
    if type(confidence) not in {int, float} or not 0 <= confidence <= 1:
        raise ValueError("invalid advisory confidence")
    for question in questions:
        value = decision[question["id"]]
        if question["type"] == "score" and (
            type(value) is not int or not 0 <= value <= 4
        ):
            raise ValueError("score must be 0..4")
        if question["type"] == "noul" and (
            type(value) not in {int, float} or not 0 <= value <= 1
        ):
            raise ValueError("probability must be 0..1")
        if question["type"] == "choice" and value not in question["criteria"]:
            raise ValueError("unknown advisory choice")
    return dict(decision)


def _score(
    record: dict,
    *,
    kind: str,
    backend: Callable | None = None,
    cache_root: str | Path,
    model_version: str = "NOT_CONFIGURED",
    policy_sha: str,
    max_bytes: int = 16_384,
) -> dict:
    state = build_compact_state(record, kind=kind, max_bytes=max_bytes)
    key = decision_cache_key(
        state,
        model_version=model_version,
        prompt_version=PROMPT_VERSION,
        policy_sha=policy_sha,
    )
    cached = load_cached_decision(cache_root, key)
    if cached:
        validate_decision(cached["decision"], kind)
        return {"status": "CACHED", "receipt": cached}
    if backend is None:
        return {
            "status": "NOT_OBSERVED",
            "reason": "OPTIONAL_LOCAL_LAYA_NOT_CONFIGURED",
            "state_sha256": digest(state),
            "delete_authorized": False,
            "live_authorized": False,
        }
    decision = validate_decision(backend(state, _questions(kind)), kind)
    return {
        "status": "SCORED",
        "receipt": store_decision_receipt(cache_root, key, decision, state=state),
    }


def score_observation(record, **kwargs):
    return _score(record, kind="observation", **kwargs)


def score_episode(record, **kwargs):
    return _score(record, kind="episode", **kwargs)


def score_repo_group(record, **kwargs):
    return _score(record, kind="repo_group", **kwargs)


def batch_score(
    records: list[dict], *, kind: str, limit: int = 32, **kwargs
) -> list[dict]:
    if limit < 1:
        raise ValueError("positive inference batch limit required")
    return [_score(record, kind=kind, **kwargs) for record in records[:limit]]
