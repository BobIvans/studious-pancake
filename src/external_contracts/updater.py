"""Create human-reviewable pin proposals without mutating the registry."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any

from src.external_contracts.registry import ExternalContractRegistry


def propose_artifact_rotation(
    registry: ExternalContractRegistry,
    contract_id: str,
    artifact_path: str,
    candidate_file: str | Path,
) -> dict[str, Any]:
    contract = registry.get(contract_id)
    pin = next(
        (item for item in contract.artifacts if item.path == artifact_path), None
    )
    if pin is None:
        raise ValueError(
            f"contract {contract_id} has no artifact pin for {artifact_path}"
        )
    candidate = Path(candidate_file)
    if not candidate.is_file():
        raise ValueError(f"candidate artifact does not exist: {candidate}")
    observed = hashlib.sha256(candidate.read_bytes()).hexdigest()
    return {
        "schema_version": "pr054.contract-rotation-proposal.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "review_required": True,
        "canonical_registry_mutated": False,
        "contract_id": contract.id,
        "provider": contract.provider,
        "artifact_path": pin.path,
        "current_sha256": pin.sha256,
        "candidate_sha256": observed,
        "changed": observed != pin.sha256,
        "official_source_url": contract.official_source_url,
        "source_ref": contract.source_ref,
        "promotion_state": contract.promotion_state.value,
        "evidence": contract.evidence.model_dump(),
        "review_checklist": [
            "verify the candidate came from the official allowlisted source",
            "review schema/layout and semantic changes",
            "run offline drift and focused tests",
            "run opt-in read-only conformance when credentials are available",
            "do not treat local hash integrity as execution readiness",
            "rotate the canonical pin only in a separately reviewed commit",
        ],
    }
