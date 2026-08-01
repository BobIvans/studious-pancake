"""Sender-free PR-005 evidence gate for strategy candidates."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Mapping

DISCOVERY_ONLY = frozenset({"okx", "openocean", "odos"})


class AdmissionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AdmissionEvidence:
    quota_reserved: bool
    provenance_verified: bool
    fresh: bool
    rooted_quorum: bool
    account_locks_reserved: bool
    oracle_coherent: bool
    protocol_accounts_verified: bool
    token_accounts_verified: bool
    economic_preconditions: bool
    durable_reservation: bool
    model_or_research_origin: bool = False


def admit_sender_free(
    *,
    provider: str,
    amount: object,
    identity_parts: Mapping[str, object],
    evidence: AdmissionEvidence,
) -> str:
    from src.lending.account_truth import validate_route_amount

    validate_route_amount(amount)
    if provider.lower() in DISCOVERY_ONLY:
        raise AdmissionError("discovery-only provider is not executable")
    if evidence.model_or_research_origin:
        raise AdmissionError("model/research output is advisory only")
    failed = [
        name
        for name in (
            "quota_reserved",
            "provenance_verified",
            "fresh",
            "rooted_quorum",
            "account_locks_reserved",
            "oracle_coherent",
            "protocol_accounts_verified",
            "token_accounts_verified",
            "economic_preconditions",
            "durable_reservation",
        )
        if getattr(evidence, name) is not True
    ]
    if failed:
        raise AdmissionError("missing durable admission evidence: " + ",".join(failed))
    required = {
        "asset",
        "venue_program",
        "generation",
        "rooted_snapshot",
        "provider_request",
        "route_evidence",
        "policy_release",
    }
    if set(identity_parts) != required or any(
        v in (None, "") for v in identity_parts.values()
    ):
        raise AdmissionError("incomplete canonical opportunity identity")
    payload = {
        "schema": "pr005.opportunity.v1",
        "provider": provider,
        "amount": amount,
        "identity": identity_parts,
    }
    # Structured canonical JSON avoids delimiter collisions.
    return sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()
