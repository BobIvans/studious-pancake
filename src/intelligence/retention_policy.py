"""Deterministic physical retention, separate from model evaluate_retention."""

from .common import seal

CLASSES = {
    "PIN_FOREVER",
    "PIN_EXPERIMENT",
    "KEEP_EPISODE",
    "KEEP_SAMPLE",
    "ROLLUP_ONLY",
    "EXPIRE_RAW",
}
PERMANENT = {
    "terminal_paper_outcome",
    "qualification_evidence",
    "unique_anomaly",
    "schema_drift",
    "replay_mismatch",
    "reconciliation_failure",
    "new_failure_class",
    "manual_pin",
}


def classify_retention_class(record: dict) -> str:
    if any(record.get(flag) is True for flag in PERMANENT):
        return "PIN_FOREVER"
    if record.get("active_experiment") is True:
        return "PIN_EXPERIMENT"
    if record.get("candidate_window") is True or record.get("referenced") is True:
        return "KEEP_EPISODE"
    if record.get("baseline_sample") is True or any(
        record.get(k) is True
        for k in (
            "significant_delta",
            "gap_before",
            "correction",
            "retraction",
            "reconnect",
        )
    ):
        return "KEEP_SAMPLE"
    return "ROLLUP_ONLY" if record.get("stable_poll") is True else "EXPIRE_RAW"


def retention_eligibility(
    record: dict, *, now_ms: int, minimum_age_ms: int = 86_400_000
) -> dict:
    if now_ms < 0 or minimum_age_ms < 1:
        raise ValueError("invalid retention clock/policy")
    klass = classify_retention_class(record)
    reasons = []
    if klass not in {"ROLLUP_ONLY", "EXPIRE_RAW"}:
        reasons.append(klass)
    available = record.get("available_at_ms")
    if (
        type(available) is not int
        or available < 0
        or now_ms - available < minimum_age_ms
    ):
        reasons.append("MINIMUM_AGE_OR_CLOCK_UNKNOWN")
    extended_until = record.get("retain_until_ms", 0)
    if type(extended_until) is not int or extended_until > now_ms:
        reasons.append("RETENTION_EXTENSION")
    for key in (
        "reference_inventory_complete",
        "representation_verified",
        "provenance_verified",
        "compaction_verified",
        "replay_verified",
        "minimum_samples_retained",
    ):
        if record.get(key) is not True:
            reasons.append(key.upper())
    if record.get("referenced") is not False:
        reasons.append("REFERENCES_UNKNOWN_OR_PRESENT")
    if record.get("active_experiment") is not False:
        reasons.append("EXPERIMENT_PINS_UNKNOWN_OR_PRESENT")
    return {
        "event_id": record["event_id"],
        "retention_class": klass,
        "eligible": not reasons,
        "reasons": reasons,
    }


def retention_dry_run(
    records: list[dict], *, now_ms: int, minimum_age_ms=86_400_000
) -> dict:
    decisions = [
        retention_eligibility(r, now_ms=now_ms, minimum_age_ms=minimum_age_ms)
        for r in records
    ]
    return build_retention_receipt(
        decisions, now_ms=now_ms, minimum_age_ms=minimum_age_ms
    )


def build_retention_receipt(
    decisions: list[dict], *, now_ms: int, minimum_age_ms: int
) -> dict:
    if len({d["event_id"] for d in decisions}) != len(decisions):
        raise ValueError("duplicate retention identity")
    return seal(
        {
            "schema": "studious.retention.v2",
            "now_ms": now_ms,
            "minimum_age_ms": minimum_age_ms,
            "decisions": decisions,
            "physical_mutation": False,
            "model_authority": False,
        }
    )
