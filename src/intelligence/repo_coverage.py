"""Explicit exclusions and analysis gaps."""


def coverage_gaps(manifest: dict, analyses: list[dict] = ()) -> list[dict]:
    return [
        {"path": e["path"], "reason": e["status"]}
        for e in manifest["entries"]
        if e["status"] != "EXACT"
    ] + [
        {"path": a["path"], "reason": a["status"]}
        for a in analyses
        if a["status"] != "ANALYZED"
    ]


def coverage_summary(manifest: dict, analyses: list[dict] = ()) -> dict:
    return {
        "tracked_entries": len(manifest["entries"]),
        "exact_entries": sum(e["status"] == "EXACT" for e in manifest["entries"]),
        "gaps": coverage_gaps(manifest, analyses),
    }


def format_gaps(gaps: list[dict]) -> str:
    return "\n".join(f"{g['path']}: {g['reason']}" for g in gaps)
