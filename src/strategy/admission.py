"""Sender-free PR-005 evidence gate for strategy candidates."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Mapping

DISCOVERY_ONLY = frozenset({"okx", "okx_dex", "openocean", "odos"})


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


class PersistentOpportunityLedger:
    """Crash-safe, insert-once admission identity authority."""

    def __init__(self, path: str | Path) -> None:
        self._db = sqlite3.connect(str(path), isolation_level=None)
        self._db.execute("PRAGMA trusted_schema=OFF")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS pr005_admissions ("
            "opportunity_id TEXT PRIMARY KEY, admitted_at_ns INTEGER NOT NULL)"
        )

    def close(self) -> None:
        self._db.close()

    def reserve_once(self, opportunity_id: str, *, admitted_at_ns: int) -> bool:
        if type(admitted_at_ns) is not int or admitted_at_ns <= 0:
            raise AdmissionError("admitted_at_ns must be a positive integer")
        try:
            with self._db:
                self._db.execute(
                    "INSERT INTO pr005_admissions VALUES (?, ?)",
                    (opportunity_id, admitted_at_ns),
                )
        except sqlite3.IntegrityError:
            return False
        return True


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
