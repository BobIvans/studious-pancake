#!/usr/bin/env python3
"""Fail-closed verification of PR-008's shipped supply-chain objects."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_deployment_sandbox import validate_files  # noqa: E402
from scripts.verify_workflow_authority import evaluate_workflow_authority  # noqa: E402

PINNED_BASE = "python:3.13.13-slim-bookworm@sha256:355bfa66770995d7e9a0da4b3473b44d0cb451f6b56f5615ad9c39e3c4eca03f"
HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root: Path) -> dict[str, object]:
    errors: list[str] = []
    docker = (root / "Dockerfile").read_text()
    lock = (root / "requirements.lock").read_text()
    requirements = (root / "requirements.txt").read_text().lower()
    for alias in ("httpx2", "httpcore2", "jsonalias"):
        if re.search(rf"(?m)^{alias}==", requirements):
            errors.append(f"ambiguous dependency alias remains: {alias}")
    if docker.count(f"FROM {PINNED_BASE}") != 3:
        errors.append("every Docker stage must use the reviewed digest")
    for token in ("--require-hashes", "--no-index", "/reviewed-wheel/*.whl"):
        if token not in docker:
            errors.append(f"Dockerfile missing offline-wheel control: {token}")
    if "COPY src ./src" in docker.split(" AS runtime", 1)[-1]:
        errors.append("runtime image contains source checkout")
    pins = [line for line in lock.splitlines() if "==" in line and not line.startswith("#")]
    if not pins or len(HASH.findall(lock)) < len(pins):
        errors.append("lock entries are not fully hash constrained")
    workflow = evaluate_workflow_authority(root, strict=True)
    errors.extend(workflow.violations)
    try:
        validate_files(root / "deploy/production/container_sandbox_policy.json", root / "deploy/production/docker-compose.sandbox.yml")
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    compose = (root / "deploy/production/docker-compose.sandbox.yml").read_text()
    if "runtime.env" in compose or "internal: true" not in compose:
        errors.append("compose must omit raw env files and deny default egress")
    artifacts = {p.relative_to(root).as_posix(): sha(p) for p in (
        root / "Dockerfile", root / "requirements.lock",
        root / "deploy/production/docker-compose.sandbox.yml",
        root / "deploy/production/seccomp-runtime.json",
        root / "deploy/production/apparmor-flashloan-bot",
        root / "deploy/production/egress-policy.json")}
    blockers = ["missing-wheel-signature", "missing-image-signature", "missing-sbom-signature",
                "missing-target-apparmor-seccomp-execution", "pr007-final-parity-not-available",
                "missing-real-secret-incident-drill"]
    return {"schema_version": "pr008.supply-chain.v1", "ready": not errors and not blockers,
            "verified_controls": not errors, "errors": errors, "blockers": blockers,
            "artifacts": artifacts, "live_submission": False, "signer_ipc": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify(args.root.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    # Verification defects fail always. Named external blockers are honest release
    # blockers, but do not prevent this static preflight command from being used.
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
