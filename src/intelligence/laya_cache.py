"""Content-addressed advisory receipts including model and prompt versions."""

from pathlib import Path
from .common import digest, load_json, save_json, seal, verify_seal


def decision_cache_key(
    state: dict, *, model_version: str, prompt_version: str, policy_sha: str
) -> str:
    if not model_version or not prompt_version or not policy_sha:
        raise ValueError("complete triage versions required")
    return digest(
        {
            "state": state,
            "model_version": model_version,
            "prompt_version": prompt_version,
            "policy_sha": policy_sha,
        }
    )


def load_cached_decision(root: str | Path, key: str) -> dict | None:
    if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
        raise ValueError("invalid cache key")
    path = Path(root) / (key + ".json")
    if not path.exists():
        return None
    receipt = load_json(path)
    verify_seal(receipt)
    if receipt["cache_key"] != key:
        raise ValueError("decision cache mismatch")
    return receipt


def store_decision_receipt(
    root: str | Path, key: str, decision: dict, *, state: dict
) -> dict:
    receipt = seal(
        {
            "schema": "studious.laya-decision.v2",
            "cache_key": key,
            "state_sha256": digest(state),
            "state": state,
            "decision": decision,
            "delete_authorized": False,
            "live_authorized": False,
        }
    )
    old = load_cached_decision(root, key)
    if old is not None and old != receipt:
        raise ValueError("immutable advisory decision conflict")
    save_json(Path(root) / (key + ".json"), receipt)
    return receipt
