"""Advisory extensions and review queue, never direct delete or live effects."""

from .common import digest, verify_seal
from .laya_triage import build_compact_state, validate_decision


def collect_candidates_for_triage(
    records: list[dict], *, limit: int = 32
) -> list[dict]:
    if limit < 1:
        raise ValueError("positive retrieval limit required")
    # Exact deterministic filtering first, bounded lexical/delta novelty ordering second.
    unique: dict[str, dict] = {}
    for record in records:
        key = (
            record.get("payload_sha256")
            or record.get("event_id")
            or record.get("episode_id")
        )
        if key is None:
            raise ValueError("triage source identity required")
        unique.setdefault(key, record)
    return sorted(
        unique.values(),
        key=lambda r: (
            -abs(r.get("delta_atoms", 0)),
            r.get("event_id", r.get("episode_id", "")),
        ),
    )[:limit]


def apply_laya_retention_extension(
    record: dict, receipt: dict, *, now_ms: int, minimum_confidence: float = 0.8
) -> dict:
    verify_seal(receipt)
    state = receipt["state"]
    if (
        digest(build_compact_state(record, kind=state["kind"]))
        != receipt["state_sha256"]
    ):
        raise ValueError("advisory decision source mismatch")
    if (
        receipt["delete_authorized"] is not False
        or receipt["live_authorized"] is not False
    ):
        raise ValueError("advisory authority violation")
    decision = receipt["decision"]
    validate_decision(decision, state["kind"])
    result = dict(record)
    if decision["confidence"] < minimum_confidence:
        return result
    extension = decision.get("retention_extension", "normal")
    durations = {"normal": 0, "extend_24h": 86_400_000, "extend_7d": 604_800_000}
    if extension == "pin_episode":
        result["manual_pin"] = True
    elif extension in durations and durations[extension]:
        result["retain_until_ms"] = max(
            record.get("retain_until_ms", 0), now_ms + durations[extension]
        )
    elif extension not in durations:
        raise ValueError("unsupported retention extension")
    return result


def queue_strong_ai_review(
    receipts: list[dict], *, threshold: float = 0.8
) -> list[dict]:
    result = []
    for receipt in receipts:
        verify_seal(receipt)
        decision = receipt["decision"]
        if (
            decision["confidence"] >= threshold
            and max(
                decision.get("strong_ai_needed", 0),
                decision.get("followup_required", 0),
                decision.get("evidence_gap", 0),
            )
            >= threshold
        ):
            result.append(
                {
                    "decision_ref": receipt["receipt_sha256"],
                    "state_ref": receipt["state_sha256"],
                    "status": "QUEUED",
                    "live_authorized": False,
                }
            )
    return result
