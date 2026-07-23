#!/usr/bin/env python3
"""Verify a signed PR-07 soak checkpoint chain without enabling live execution."""

from __future__ import annotations

import argparse
from datetime import datetime
from enum import StrEnum
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.release_soak_pr07 import (  # noqa: E402
    SoakVerdict,
    evaluate_soak,
    render_report_json,
    run_identity_from_mapping,
    signed_checkpoint_from_mapping,
)
from src.security.trust_anchors import (  # noqa: E402
    TrustAnchor,
    TrustAnchorRegistry,
    TrustAnchorState,
    TrustUsage,
)


class CommandMode(StrEnum):
    INSPECT = "inspect"
    CHECK = "check"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=tuple(CommandMode))
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)
    mode = CommandMode(args.mode)
    try:
        data = _strict_json_load(Path(args.manifest))
        identity = run_identity_from_mapping(_mapping(data["run_identity"]))
        registry = _registry_from_mapping(_mapping(data["trust_registry"]))
        checkpoints = tuple(
            signed_checkpoint_from_mapping(_mapping(item))
            for item in _sequence(data["checkpoints"])
        )
        evaluated_at = _parse_time(data["evaluated_at"])
        report = evaluate_soak(
            identity,
            checkpoints,
            registry,
            evaluated_at=evaluated_at,
        )
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        payload = {
            "schema_version": "pr07.command-result.v1",
            "verdict": "error",
            "reason_codes": [f"PR07_MANIFEST_INVALID:{type(exc).__name__}"],
            "live_enabled": False,
            "sender_reachable": False,
            "signer_reachable": False,
            "submission_allowed": False,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    print(render_report_json(report), end="")
    if mode is CommandMode.CHECK and report.verdict is not SoakVerdict.READY_FOR_REVIEW:
        return 3
    return 0


def _registry_from_mapping(data: Mapping[str, Any]) -> TrustAnchorRegistry:
    anchors = tuple(
        _anchor_from_mapping(_mapping(item)) for item in _sequence(data["anchors"])
    )
    return TrustAnchorRegistry(
        anchors,
        generation=str(data["generation"]),
    )


def _anchor_from_mapping(data: Mapping[str, Any]) -> TrustAnchor:
    return TrustAnchor(
        key_id=str(data["key_id"]),
        algorithm=str(data["algorithm"]),
        public_key_base58=str(data["public_key_base58"]),
        usages=tuple(TrustUsage(str(item)) for item in _sequence(data["usages"])),
        issuer=str(data["issuer"]),
        environment=str(data["environment"]),
        valid_from=_parse_time(data["valid_from"]),
        valid_until=_parse_time(data["valid_until"]),
        state=TrustAnchorState(str(data.get("state", "staged"))),
        revoked_at=(
            _parse_time(data["revoked_at"])
            if data.get("revoked_at") is not None
            else None
        ),
        minimum_security_level=_strict_int(data.get("minimum_security_level", 128)),
    )


def _strict_json_load(path: Path) -> Mapping[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    data = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicates,
    )
    return _mapping(data)


def _parse_time(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return parsed


def _strict_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("integer required")
    return value


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("mapping required")
    return value


def _sequence(value: object) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError("sequence required")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
