#!/usr/bin/env python3
"""Deterministic repeated-run MPR-2611 qualification snapshot.

This runner is sender-free and does not promote a release. It independently
recomputes the semantic qualification snapshot repeatedly and fails if the
result changes between identical runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _git_head(root: Path) -> str | None:
    head = root / ".git" / "HEAD"
    if not head.is_file():
        return None
    raw = head.read_text(encoding="utf-8").strip()
    if raw.startswith("ref: "):
        target = root / ".git" / raw[5:]
        return target.read_text(encoding="utf-8").strip() if target.is_file() else None
    return raw or None


def build_snapshot(root: Path, *, release_id: str, source_commit: str) -> dict[str, Any]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from scripts.qualify_release import collect_release_artifacts, resolve_debt_items

    inventory = json.loads(
        (root / "src" / "resources" / "production_debt.json").read_text(encoding="utf-8")
    )
    capabilities = json.loads(
        (root / "src" / "resources" / "capabilities.json").read_text(encoding="utf-8")
    )
    artifacts, by_id = collect_release_artifacts(
        root,
        source_commit=source_commit,
        release_id=release_id,
    )
    product_state = str(capabilities.get("product_state", "unknown"))
    runtime_modes = capabilities.get("runtime_modes", {})
    live_mode_available = bool(runtime_modes.get("live", {}).get("available"))
    debt = resolve_debt_items(
        inventory,
        by_id,
        product_state=product_state,
        live_mode_available=live_mode_available,
    )
    open_debt = sorted(key for key, value in debt.items() if not value["resolved"])
    missing = sorted(item["id"] for item in artifacts if item["status"] == "missing")
    invalid = sorted(item["id"] for item in artifacts if item["status"] == "invalid")
    passed = not missing and not invalid and not open_debt
    semantic_artifacts = {
        item["id"]: {
            "status": item["status"],
            "semantic_sha256": item.get("semantic_sha256"),
            "validation": item.get("validation"),
        }
        for item in artifacts
    }
    snapshot = {
        "schema_version": "mpr-2611.clean-qualification-snapshot.v1",
        "source_commit": source_commit,
        "release_id": release_id,
        "python": {
            "implementation": platform.python_implementation(),
            "version": ".".join(map(str, sys.version_info[:3])),
            "platform": sys.platform,
            "machine": platform.machine(),
        },
        "product_state": product_state,
        "missing_artifacts": missing,
        "invalid_artifacts": invalid,
        "open_debt_items": open_debt,
        "artifacts": semantic_artifacts,
        "debt_resolution": debt,
        "production_qualification_passed": passed,
        "eligible_for_release_review": passed,
        "release_claim_allowed": False,
        "live_enabled": False,
    }
    snapshot["semantic_bundle_sha256"] = _digest(snapshot)
    return snapshot


def run_repeated(
    root: Path,
    *,
    release_id: str,
    source_commit: str,
    repeat: int,
) -> dict[str, Any]:
    if repeat < 2:
        raise ValueError("repeat must be >= 2")
    snapshots = [
        build_snapshot(root, release_id=release_id, source_commit=source_commit)
        for _ in range(repeat)
    ]
    digests = [snapshot["semantic_bundle_sha256"] for snapshot in snapshots]
    stable = len(set(digests)) == 1
    independent = _digest({k: v for k, v in snapshots[0].items() if k != "semantic_bundle_sha256"})
    verified = stable and independent == digests[0]
    return {
        "schema_version": "mpr-2611.repeated-clean-qualification.v1",
        "repeat_count": repeat,
        "stable": stable,
        "independent_digest_match": independent == digests[0],
        "verified": verified,
        "semantic_bundle_sha256": digests[0],
        "run_digests": digests,
        "production_qualification_passed": snapshots[0]["production_qualification_passed"],
        "eligible_for_release_review": snapshots[0]["eligible_for_release_review"],
        "release_claim_allowed": False,
        "live_enabled": False,
        "snapshot": snapshots[0],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(ROOT))
    parser.add_argument("--release-id", default="mpr2611-ci")
    parser.add_argument("--source-commit", default=None)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--output", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    root = Path(args.project_root).resolve()
    source_commit = args.source_commit or _git_head(root)
    if not source_commit:
        raise SystemExit("source commit is required when .git identity is unavailable")
    payload = run_repeated(
        root,
        release_id=args.release_id,
        source_commit=source_commit,
        repeat=args.repeat,
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if payload["verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
