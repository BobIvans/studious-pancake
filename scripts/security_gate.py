#!/usr/bin/env python3
"""Offline PR-043 security gate.

The gate intentionally does not call the network. It can scan local text files
for plaintext wallet/signing key material and evaluate normalized dependency
vulnerability records produced by another scanner.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.security.secret_scan import (
    PlaintextKeyMaterialError,
    assert_no_plaintext_key_material,
)
from src.security.supply_chain import (
    DEFAULT_DEPENDENCY_AUDIT_POLICY,
    Severity,
    VulnerabilityRecord,
)

_TEXT_SUFFIXES = {
    ".env",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_DEFAULT_SCAN_DIRS = ("config", "docs", "scripts", "src", "tests")


def _iter_scan_files(repo_root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for relative_dir in _DEFAULT_SCAN_DIRS:
        directory = repo_root / relative_dir
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix in _TEXT_SUFFIXES:
                paths.append(path)
    return tuple(sorted(paths))


def _scan_repo(repo_root: Path) -> None:
    values: dict[str, str] = {}
    for path in _iter_scan_files(repo_root):
        try:
            values[str(path.relative_to(repo_root))] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
    assert_no_plaintext_key_material(values, source="repo")


def _load_records(path: Path | None) -> tuple[VulnerabilityRecord, ...]:
    if path is None:
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("vulnerability input must be a list of records")
    records: list[VulnerabilityRecord] = []
    known_severities = {severity.value for severity in Severity}
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("vulnerability records must be JSON objects")
        raw_severity = str(item.get("severity", "unknown")).lower()
        severity = (
            Severity(raw_severity)
            if raw_severity in known_severities
            else Severity.UNKNOWN
        )
        records.append(
            VulnerabilityRecord(
                package=str(item["package"]),
                vulnerability_id=str(item["vulnerability_id"]),
                severity=severity,
                fixed_versions=tuple(
                    str(value) for value in item.get("fixed_versions", ())
                ),
                source=str(item.get("source", "normalized-json")),
            )
        )
    return tuple(records)


def _load_policy_marker(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "pr043.security-supply-chain-policy.v1":
        raise ValueError("unexpected security supply-chain policy schema")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--policy",
        default="config/security_supply_chain_policy.json",
        help="PR-043 supply-chain policy marker JSON",
    )
    parser.add_argument(
        "--vulnerabilities-json",
        default=None,
        help="Optional normalized vulnerability records JSON",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    policy_path = repo_root / args.policy
    _load_policy_marker(policy_path)

    try:
        _scan_repo(repo_root)
    except PlaintextKeyMaterialError as exc:
        print(str(exc))
        return 1

    records = _load_records(
        None if args.vulnerabilities_json is None else Path(args.vulnerabilities_json)
    )
    decision = DEFAULT_DEPENDENCY_AUDIT_POLICY.evaluate(records)
    if not decision.allowed:
        print(decision.reason)
        for blocker in decision.blockers:
            print(blocker)
        return 1
    print("PR-043 security gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
