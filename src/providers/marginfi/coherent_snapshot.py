"""PR-116 coherent MarginFi snapshot and oracle freshness gate.

Offline evidence gate only: no RPC, signer, sender, Jito, transaction submission,
or live/canary activation. A passing result only says that a materialized
read-only MarginFi snapshot proves one coherent context-slot/root contract with
fresh oracle evidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum, StrEnum
import hashlib
import json
import re
from typing import Any

PR116_SCHEMA_VERSION = "pr116.marginfi-coherent-snapshot.v1"
PR116_RESULT_SCHEMA_VERSION = "pr116.marginfi-coherent-snapshot-result.v1"
MAXIMUM_SNAPSHOT_CAPABILITY = "marginfi-readonly-coherent-snapshot-capable"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_ROLES = frozenset(
    {
        "program",
        "programdata",
        "group",
        "margin-account",
        "target-bank",
        "liquidity-vault",
        "oracle",
    }
)


class MarginfiCoherentSnapshotError(ValueError):
    """Raised when PR-116 evidence is explicitly asserted but blocked."""


class MarginfiAccountRole(StrEnum):
    PROGRAM = "program"
    PROGRAMDATA = "programdata"
    GROUP = "group"
    MARGIN_ACCOUNT = "margin-account"
    TARGET_BANK = "target-bank"
    ACTIVE_BANK = "active-bank"
    LIQUIDITY_VAULT = "liquidity-vault"
    ORACLE = "oracle"


@dataclass(frozen=True, slots=True)
class RpcBatchEvidence:
    batch_id: str
    context_slot: int
    min_context_slot: int
    rooted_slot: int
    commitment: str
    addresses: Sequence[str]
    response_sha256: str


@dataclass(frozen=True, slots=True)
class MarginfiSnapshotAccountEvidence:
    address: str
    owner: str
    role: MarginfiAccountRole
    slot: int
    data_sha256: str
    lamports: int
    executable: bool = False
    decoded_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class MarginfiOracleEvidence:
    oracle_address: str
    bank_address: str
    source: str
    owner: str
    price_mantissa: int
    exponent: int
    confidence_mantissa: int
    publish_slot: int
    context_slot: int
    max_staleness_slots: int
    relationship_verified: bool
    evidence_sha256: str


@dataclass(frozen=True, slots=True)
class MarginfiCoherentSnapshotPackage:
    context_slot: int
    min_context_slot: int
    rooted_slot: int
    rpc_batches: Sequence[RpcBatchEvidence]
    accounts: Sequence[MarginfiSnapshotAccountEvidence]
    oracle_evidence: Sequence[MarginfiOracleEvidence]
    risk_remaining_account_order: Sequence[str]
    snapshot_fingerprint_sha256: str
    pr101_complete_evidence_sha256: str
    pr115_simulation_evidence_sha256: str
    pr101_shadow_execution_capable: bool
    pr115_simulation_owned_decoding_ready: bool
    multi_call_slot_vector_verified: bool
    account_set_stable_after_discovery: bool
    human_reviewed: bool
    live_allowed: bool = False
    assembled_at: datetime | None = None
    schema_version: str = PR116_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class MarginfiCoherentSnapshotEvaluation:
    coherent_snapshot_capable: bool
    live_execution_allowed: bool
    state: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_hash: str
    calculated_snapshot_fingerprint_sha256: str
    checks_evaluated: int
    metrics_summary: Mapping[str, int | str | bool]
    schema_version: str = PR116_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "coherent_snapshot_capable": self.coherent_snapshot_capable,
            "live_execution_allowed": self.live_execution_allowed,
            "state": self.state,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "evidence_hash": self.evidence_hash,
            "calculated_snapshot_fingerprint_sha256": (
                self.calculated_snapshot_fingerprint_sha256
            ),
            "checks_evaluated": self.checks_evaluated,
            "metrics_summary": dict(self.metrics_summary),
        }


def calculate_pr116_state_fingerprint(
    accounts: Sequence[MarginfiSnapshotAccountEvidence],
) -> str:
    """Hash address, role, owner, data and slot so mixed-slot bytes cannot hide."""

    return _sha256_payload(
        [
            {
                "address": account.address,
                "owner": account.owner,
                "role": account.role.value,
                "slot": account.slot,
                "data_sha256": account.data_sha256,
                "decoded_sha256": account.decoded_sha256,
                "lamports": str(account.lamports),
                "executable": account.executable,
            }
            for account in sorted(
                accounts,
                key=lambda item: (item.address, item.role.value),
            )
        ]
    )


def evaluate_marginfi_coherent_snapshot(
    package: MarginfiCoherentSnapshotPackage,
) -> MarginfiCoherentSnapshotEvaluation:
    blockers: list[str] = []
    warnings: list[str] = []
    checks = 0

    def check(condition: bool, reason: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            blockers.append(reason)

    check(package.schema_version == PR116_SCHEMA_VERSION, "PR116_SCHEMA_MISMATCH")
    check(_positive(package.context_slot), "PR116_CONTEXT_SLOT_INVALID")
    check(package.min_context_slot <= package.context_slot, "PR116_MIN_SLOT_TOO_HIGH")
    check(package.context_slot <= package.rooted_slot, "PR116_CONTEXT_ABOVE_ROOT")
    check(_sha256(package.pr101_complete_evidence_sha256), "PR101_HASH_INVALID")
    check(_sha256(package.pr115_simulation_evidence_sha256), "PR115_HASH_INVALID")
    check(package.pr101_shadow_execution_capable, "PR101_NOT_SHADOW_CAPABLE")
    check(
        package.pr115_simulation_owned_decoding_ready,
        "PR115_SIMULATION_DECODING_NOT_READY",
    )
    check(package.human_reviewed, "PR116_HUMAN_REVIEW_MISSING")
    check(not package.live_allowed, "PR116_LIVE_ALLOWED_TRUE")
    check(
        package.account_set_stable_after_discovery,
        "PR116_ACCOUNT_SET_CHANGED_AFTER_DISCOVERY",
    )

    batches = tuple(package.rpc_batches)
    accounts = tuple(package.accounts)
    check(bool(batches), "PR116_RPC_BATCHES_MISSING")
    check(bool(accounts), "PR116_ACCOUNTS_MISSING")

    batch_slots = {batch.context_slot for batch in batches}
    check(batch_slots == {package.context_slot}, "PR116_BATCH_CONTEXT_SLOT_MISMATCH")
    check(
        all(batch.min_context_slot <= package.context_slot for batch in batches),
        "PR116_BATCH_MIN_CONTEXT_ABOVE_SNAPSHOT_SLOT",
    )
    check(
        all(batch.rooted_slot >= package.rooted_slot for batch in batches),
        "PR116_BATCH_ROOT_BELOW_PACKAGE_ROOT",
    )
    check(
        all(len(tuple(batch.addresses)) <= 100 for batch in batches),
        "PR116_BATCH_TOO_LARGE",
    )
    if len(batches) > 1:
        check(
            package.multi_call_slot_vector_verified,
            "PR116_MULTI_CALL_SLOT_VECTOR_NOT_VERIFIED",
        )
        warnings.append("PR116_MULTIPLE_RPC_BATCHES_WITH_EQUAL_CONTEXT_SLOT")

    account_pairs = [(account.address, account.role.value) for account in accounts]
    check(len(set(account_pairs)) == len(account_pairs), "PR116_DUPLICATE_ACCOUNT_ROLE")
    account_addresses = {account.address for account in accounts}
    batch_addresses = {address for batch in batches for address in batch.addresses}
    check(batch_addresses == account_addresses, "PR116_BATCH_ACCOUNT_SET_MISMATCH")
    check(
        all(account.slot == package.context_slot for account in accounts),
        "PR116_ACCOUNT_SLOT_MISMATCH",
    )
    check(
        all(_sha256(account.data_sha256) for account in accounts),
        "PR116_ACCOUNT_DATA_HASH_INVALID",
    )
    check(
        all(
            account.decoded_sha256 is None or _sha256(account.decoded_sha256)
            for account in accounts
        ),
        "PR116_ACCOUNT_DECODED_HASH_INVALID",
    )

    roles = {account.role.value for account in accounts}
    for role in sorted(_REQUIRED_ROLES):
        check(role in roles, f"PR116_REQUIRED_ROLE_MISSING:{role}")

    program_accounts = [
        account for account in accounts if account.role is MarginfiAccountRole.PROGRAM
    ]
    check(
        bool(program_accounts)
        and all(account.executable for account in program_accounts),
        "PR116_PROGRAM_NOT_EXECUTABLE",
    )

    bank_addresses = {
        account.address
        for account in accounts
        if account.role
        in (MarginfiAccountRole.TARGET_BANK, MarginfiAccountRole.ACTIVE_BANK)
    }
    oracle_accounts = {
        account.address
        for account in accounts
        if account.role is MarginfiAccountRole.ORACLE
    }
    oracle_banks = {oracle.bank_address for oracle in package.oracle_evidence}
    check(bool(package.oracle_evidence), "PR116_ORACLE_EVIDENCE_MISSING")
    check(bank_addresses.issubset(oracle_banks), "PR116_BANK_WITHOUT_ORACLE_EVIDENCE")

    for oracle in package.oracle_evidence:
        check(
            oracle.oracle_address in oracle_accounts,
            f"PR116_ORACLE_ACCOUNT_MISSING:{oracle.oracle_address}",
        )
        check(
            oracle.bank_address in bank_addresses,
            f"PR116_ORACLE_BANK_UNKNOWN:{oracle.bank_address}",
        )
        check(
            oracle.context_slot == package.context_slot,
            f"PR116_ORACLE_CONTEXT_SLOT_MISMATCH:{oracle.oracle_address}",
        )
        check(
            oracle.publish_slot <= package.context_slot,
            f"PR116_ORACLE_PUBLISH_SLOT_IN_FUTURE:{oracle.oracle_address}",
        )
        check(
            package.context_slot - oracle.publish_slot <= oracle.max_staleness_slots,
            f"PR116_ORACLE_STALE:{oracle.oracle_address}",
        )
        check(
            oracle.relationship_verified,
            f"PR116_ORACLE_RELATIONSHIP_UNVERIFIED:{oracle.oracle_address}",
        )
        check(_sha256(oracle.evidence_sha256), "PR116_ORACLE_HASH_INVALID")

    risk_order = tuple(package.risk_remaining_account_order)
    check(bool(risk_order), "PR116_RISK_ACCOUNT_ORDER_MISSING")
    check(len(set(risk_order)) == len(risk_order), "PR116_RISK_ACCOUNT_ORDER_DUPLICATE")
    check(
        set(bank_addresses).issubset(risk_order),
        "PR116_RISK_ACCOUNT_ORDER_MISSING_BANK",
    )

    calculated = calculate_pr116_state_fingerprint(accounts)
    check(
        _sha256(package.snapshot_fingerprint_sha256), "PR116_STATE_FINGERPRINT_INVALID"
    )
    check(
        calculated == package.snapshot_fingerprint_sha256,
        "PR116_STATE_FINGERPRINT_MISMATCH",
    )

    unique_blockers = tuple(dict.fromkeys(blockers))
    ready = not unique_blockers
    return MarginfiCoherentSnapshotEvaluation(
        coherent_snapshot_capable=ready,
        live_execution_allowed=False,
        state=MAXIMUM_SNAPSHOT_CAPABILITY if ready else "blocked",
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        evidence_hash=_sha256_payload(package.to_dict()),
        calculated_snapshot_fingerprint_sha256=calculated,
        checks_evaluated=checks,
        metrics_summary={
            "context_slot": package.context_slot,
            "rooted_slot": package.rooted_slot,
            "rpc_batches": len(batches),
            "accounts": len(accounts),
            "banks": len(bank_addresses),
            "oracles": len(package.oracle_evidence),
            "multi_call_slot_vector_verified": package.multi_call_slot_vector_verified,
        },
    )


def assert_marginfi_coherent_snapshot(
    package: MarginfiCoherentSnapshotPackage,
) -> MarginfiCoherentSnapshotEvaluation:
    evaluation = evaluate_marginfi_coherent_snapshot(package)
    if not evaluation.coherent_snapshot_capable:
        blockers = ",".join(evaluation.blockers)
        raise MarginfiCoherentSnapshotError(
            f"PR116_MARGINFI_SNAPSHOT_BLOCKED:{blockers}"
        )
    return evaluation


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {
            item.name: _jsonable(getattr(value, item.name)) for item in fields(value)
        }
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _sha256_payload(payload: Any) -> str:
    encoded = json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(value: str) -> bool:
    lowered = str(value).lower()
    return bool(_SHA256_RE.fullmatch(lowered)) and lowered != "0" * 64


def _positive(value: int) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


__all__ = [
    "MAXIMUM_SNAPSHOT_CAPABILITY",
    "PR116_RESULT_SCHEMA_VERSION",
    "PR116_SCHEMA_VERSION",
    "MarginfiAccountRole",
    "MarginfiCoherentSnapshotError",
    "MarginfiCoherentSnapshotEvaluation",
    "MarginfiCoherentSnapshotPackage",
    "MarginfiOracleEvidence",
    "MarginfiSnapshotAccountEvidence",
    "RpcBatchEvidence",
    "assert_marginfi_coherent_snapshot",
    "calculate_pr116_state_fingerprint",
    "evaluate_marginfi_coherent_snapshot",
]
