"""Immutable history and bounded dependency invalidation."""

from pathlib import Path
from .common import load_json


def list_snapshots(root: str | Path) -> list[dict]:
    return [load_json(path) for path in sorted(Path(root).glob("*/manifest.json"))]


def delta_between_snapshots(
    before: dict, after: dict, *, offset: int = 0, limit: int = 100
) -> dict:
    if offset < 0 or limit < 1:
        raise ValueError("invalid delta page")
    old = {e["path"]: e for e in before["entries"]}
    new = {e["path"]: e for e in after["entries"]}
    changes = [
        {
            "path": path,
            "kind": (
                "ADDED"
                if path not in old
                else "REMOVED" if path not in new else "MODIFIED"
            ),
            "before": old.get(path),
            "after": new.get(path),
        }
        for path in sorted(old.keys() | new.keys())
        if old.get(path) != new.get(path)
    ]
    return {
        "from": before["snapshot_id"],
        "to": after["snapshot_id"],
        "changes": changes[offset : offset + limit],
        "total": len(changes),
        "next_offset": offset + limit if offset + limit < len(changes) else None,
    }


def affected_dependents(changed: list[str], reverse: dict[str, list[str]]) -> list[str]:
    seen, stack = set(changed), list(changed)
    while stack:
        for target in reverse.get(stack.pop(), []):
            if target not in seen:
                seen.add(target)
                stack.append(target)
    return sorted(seen)
