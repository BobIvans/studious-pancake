"""PR-355 proof-carrying research receipts bound to existing evidence authority."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping

from .core import stable_hash
from .evidence_native_core import EvidenceNativeError, ResearchReceipt, record, require_digest, require_text


def build_research_receipt_manifest(payload: Mapping[str, Any]) -> ResearchReceipt:
    return ResearchReceipt(
        source_snapshot_ids=tuple(str(x) for x in payload.get("source_snapshot_ids", ())),
        raw_hashes=tuple(str(x) for x in payload.get("raw_hashes", ())),
        code_commit=str(payload.get("code_commit", "")),
        tree_hash=str(payload.get("tree_hash", "")),
        config_hash=str(payload.get("config_hash", "")),
        model_hash=str(payload.get("model_hash", "")),
        environment_lock_hash=str(payload.get("environment_lock_hash", "")),
        deterministic_seed=int(payload.get("deterministic_seed", 0)),
        command=str(payload.get("command", "")),
        output_hashes=tuple(str(x) for x in payload.get("output_hashes", ())),
        verdict=str(payload.get("verdict", "")),
        redaction_policy=str(payload.get("redaction_policy", "")),
        proof_backend=payload.get("proof_backend"),
        proof_version=payload.get("proof_version"),
    )


def replay_receipt_computation(
    receipt: ResearchReceipt,
    *,
    observed_output_hashes: tuple[str, ...],
    latest_state_read: bool = False,
):
    if latest_state_read:
        raise EvidenceNativeError("HIDDEN_LATEST_STATE_READ")
    if tuple(observed_output_hashes) != receipt.output_hashes:
        raise EvidenceNativeError("RECEIPT_OUTPUT_MISMATCH")
    return record(
        "replay_receipt_computation",
        {"receipt_hash": receipt.receipt_hash, "replay_match": True, "latest_state_read": False},
    )


def verify_receipt_components(
    receipt: ResearchReceipt,
    *,
    raw_hashes: tuple[str, ...],
    code_commit: str,
    tree_hash: str,
    config_hash: str,
    model_hash: str,
    environment_lock_hash: str,
    output_hashes: tuple[str, ...],
):
    observed = {
        "raw_hashes": tuple(raw_hashes),
        "code_commit": code_commit,
        "tree_hash": tree_hash,
        "config_hash": config_hash,
        "model_hash": model_hash,
        "environment_lock_hash": environment_lock_hash,
        "output_hashes": tuple(output_hashes),
    }
    expected = {
        "raw_hashes": receipt.raw_hashes,
        "code_commit": receipt.code_commit,
        "tree_hash": receipt.tree_hash,
        "config_hash": receipt.config_hash,
        "model_hash": receipt.model_hash,
        "environment_lock_hash": receipt.environment_lock_hash,
        "output_hashes": receipt.output_hashes,
    }
    mismatches = tuple(
        key for key in expected if observed[key] != expected[key]
    )
    if mismatches:
        raise EvidenceNativeError(
            "RECEIPT_COMPONENT_MISMATCH:" + ",".join(mismatches)
        )
    return record(
        "verify_receipt_components",
        {
            "receipt_hash": receipt.receipt_hash,
            "verified": True,
            "component_count": len(expected),
            "live_authority": False,
            "profitability_claim": False,
        },
    )


def generate_optional_computation_proof(payload: Mapping[str, Any]):
    backend = require_text(payload.get("backend"), "backend").upper()
    if backend not in {"NONE", "MOCK_SP1"}:
        raise EvidenceNativeError("PROOF_BACKEND_NOT_ADMITTED")
    receipt_hash = require_digest(payload.get("receipt_hash"), "receipt_hash")
    proof_hash = stable_hash(
        "pr355:optional-computation-proof",
        {"backend": backend, "receipt_hash": receipt_hash, "version": str(payload.get("version", "none"))},
    )
    return record(
        "generate_optional_computation_proof",
        {"backend": backend, "proof_hash": proof_hash, "receipt_hash": receipt_hash, "production_proof": False},
    )


def verify_computation_proof(payload: Mapping[str, Any]):
    backend = require_text(payload.get("backend"), "backend").upper()
    receipt_hash = require_digest(payload.get("receipt_hash"), "receipt_hash")
    proof_hash = require_digest(payload.get("proof_hash"), "proof_hash")
    expected = stable_hash(
        "pr355:optional-computation-proof",
        {"backend": backend, "receipt_hash": receipt_hash, "version": str(payload.get("version", "none"))},
    )
    return record(
        "verify_computation_proof",
        {
            "verified": proof_hash == expected,
            "backend": backend,
            "profitability_claim": False,
            "live_authority": False,
        },
    )


def redact_receipt_for_sharing(payload: Mapping[str, Any]):
    forbidden = {
        "private_key", "secret_key", "authorization", "auth_header",
        "signed_transaction", "raw_signed_transaction", "sensitive_route",
    }
    redacted = {str(k): v for k, v in payload.items() if str(k).lower() not in forbidden}
    removed = tuple(sorted(str(k) for k in payload if str(k).lower() in forbidden))
    return record(
        "redact_receipt_for_sharing",
        {"redacted_payload_hash": stable_hash("pr355:redacted-receipt", redacted), "removed_fields": removed},
    )


def bind_receipt_to_evidence_ledger(payload: Mapping[str, Any]):
    return record(
        "bind_receipt_to_evidence_ledger",
        {
            "receipt_hash": require_digest(payload.get("receipt_hash"), "receipt_hash"),
            "existing_evidence_ref": require_text(payload.get("existing_evidence_ref"), "existing_evidence_ref"),
            "new_ledger_created": False,
            "append_only_binding": True,
        },
    )
