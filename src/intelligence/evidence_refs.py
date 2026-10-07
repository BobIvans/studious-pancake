"""Explicit reference inventory. Unknown coverage always blocks expiry."""

from .common import digest


def find_raw_references(records: list[dict]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for record in records:
        for event_id in record.get("raw_event_ids", []):
            result.setdefault(event_id, []).append(record["evidence_id"])
    return {key: sorted(set(value)) for key, value in sorted(result.items())}


def find_episode_references(records: list[dict]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for record in records:
        for episode in record.get("episode_ids", []):
            result.setdefault(episode, []).append(record["evidence_id"])
    return result


def find_experiment_pins(records: list[dict]) -> list[str]:
    return sorted(
        {
            ref
            for r in records
            if r.get("active_experiment") is True
            for ref in r.get("raw_event_ids", [])
        }
    )


def deletion_impact(
    event_ids: list[str], records: list[dict], *, inventory_complete: bool = False
) -> dict:
    refs = find_raw_references(records)
    pinned = find_experiment_pins(records)
    return {
        "inventory_complete": inventory_complete,
        "inventory_sha256": digest(records),
        "referenced": sorted(set(event_ids) & refs.keys()),
        "experiment_pinned": sorted(set(event_ids) & set(pinned)),
        "eligible": inventory_complete
        and not (set(event_ids) & (refs.keys() | set(pinned))),
    }
