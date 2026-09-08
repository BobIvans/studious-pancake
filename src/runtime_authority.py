"""Canonical MPR-4X-02 runtime composition and lifecycle authority.

This module is sender-free and live-disabled. It owns the installed runtime
contract for one composition root, one lifecycle authority, one capital
reservation authority, fenced sensitive writes, irreversible terminal state,
terminal/outbox atomicity, and semantic idempotency.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from importlib import resources
import json
from typing import Any, Mapping

from src.kernel import canonical_json_bytes, domain_sha256

RUNTIME_AUTHORITY_SCHEMA = "mpr-4x-02.runtime-authority.v1"
EXPECTED_ENTRYPOINT = "flashloan-bot"
EXPECTED_MODULE = "src.cli_pr189"
EXPECTED_CALLABLE = "main"
EXPECTED_PACKAGE_SCRIPT = "src.cli_pr189:main"
EXPECTED_CANONICAL_SERVICE = (
    "src.paper_shadow.durable_service_a3:build_installed_durable_paper_service"
)
EXPECTED_LIFECYCLE_AUTHORITY = (
    "src.durability.unified_authority_pr02:UnifiedLifecycleAuthority"
)
EXPECTED_CAPITAL_AUTHORITY = (
    "src.economics.durable_reservations:DurableCapitalCoordinator"
)

SENSITIVE_WRITE_INVARIANTS: tuple[str, ...] = (
    "owner_id",
    "fencing_token",
    "lease_generation",
    "boot_id",
    "process_generation",
    "payload_hash",
)


class RuntimeAuthorityError(ValueError):
    """Raised when the canonical runtime-authority contract is malformed."""


class AttemptGeneration:
    """Positive attempt generation shared by lifecycle, reservation and outbox."""

    def __init__(self, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuntimeAuthorityError("attempt_generation must be an integer")
        if value < 1:
            raise RuntimeAuthorityError("attempt_generation must be >= 1")
        self.value = value

    def __int__(self) -> int:
        return self.value

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return f"AttemptGeneration({self.value})"


@dataclass(frozen=True, slots=True)
class SemanticCommandIdentity:
    """Canonical payload identity for replay-safe idempotency."""

    attempt_id: str
    attempt_generation: int
    candidate_id: str
    reservation_id: str
    policy_bundle_hash: str
    payload_hash: str

    def __post_init__(self) -> None:
        AttemptGeneration(self.attempt_generation)
        for field, value in asdict(self).items():
            if isinstance(value, str) and not value:
                raise RuntimeAuthorityError(f"{field} is required")

    def digest(self) -> str:
        return domain_sha256(
            domain="runtime-semantic-command",
            schema_id=RUNTIME_AUTHORITY_SCHEMA,
            payload=canonical_json_bytes(asdict(self)),
        )


class SemanticIdempotencyLedger:
    """Deterministic ledger used by adapters to reject semantic replay drift."""

    def __init__(self) -> None:
        self._seen: dict[str, str] = {}

    def record(self, idempotency_key: str, identity: SemanticCommandIdentity) -> bool:
        if not idempotency_key:
            raise RuntimeAuthorityError("idempotency_key is required")
        digest = identity.digest()
        previous = self._seen.get(idempotency_key)
        if previous is None:
            self._seen[idempotency_key] = digest
            return False
        if previous != digest:
            raise RuntimeAuthorityError("IDEMPOTENCY_SEMANTIC_CONFLICT")
        return True


class TerminalState(StrEnum):
    NONTERMINAL = "NONTERMINAL"
    TERMINAL = "TERMINAL"
    RECONCILED = "RECONCILED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    DEAD_LETTER = "DEAD_LETTER"


TERMINAL_STATES: frozenset[str] = frozenset(
    state.value for state in TerminalState if state is not TerminalState.NONTERMINAL
)
_KNOWN_STATES: frozenset[str] = frozenset(state.value for state in TerminalState)


@dataclass(frozen=True, slots=True)
class TransitionDecision:
    accepted: bool
    reason: str


class TerminalTransitionTable:
    """Fail-closed transition table: terminal states are irreversible."""

    def decide(self, current: str, requested: str) -> TransitionDecision:
        if current not in _KNOWN_STATES:
            return TransitionDecision(False, "UNKNOWN_CURRENT_STATE")
        if requested not in _KNOWN_STATES:
            return TransitionDecision(False, "UNKNOWN_REQUESTED_STATE")
        if current in TERMINAL_STATES and requested != current:
            return TransitionDecision(False, "TERMINAL_REGRESSION_FORBIDDEN")
        return TransitionDecision(True, "TRANSITION_ACCEPTED")


@dataclass(frozen=True, slots=True)
class RuntimeAuthorityReport:
    accepted: bool
    schema_version: str
    active_composition_root: str | None
    lifecycle_authority: str | None
    capital_authority: str | None
    blockers: tuple[str, ...]
    observed: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_default_authority_map() -> dict[str, Any]:
    path = resources.files("src.resources").joinpath("runtime_authority.json")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeAuthorityError("runtime authority map must be an object")
    return value


def evaluate_runtime_authority_map(
    payload: Mapping[str, Any] | None = None,
) -> RuntimeAuthorityReport:
    data = dict(payload or load_default_authority_map())
    blockers: list[str] = []

    if data.get("schema_version") != RUNTIME_AUTHORITY_SCHEMA:
        blockers.append("RUNTIME_AUTHORITY_SCHEMA_INVALID")

    root = _mapping(data, "active_composition_root", blockers)
    observed_root = _root_name(root)
    if root.get("entrypoint") != EXPECTED_ENTRYPOINT:
        blockers.append("CANONICAL_ENTRYPOINT_MISMATCH")
    if root.get("module") != EXPECTED_MODULE or root.get("callable") != EXPECTED_CALLABLE:
        blockers.append("CANONICAL_MODULE_MISMATCH")
    if root.get("package_script") != EXPECTED_PACKAGE_SCRIPT:
        blockers.append("PACKAGE_SCRIPT_MISMATCH")
    if root.get("paper_service") != EXPECTED_CANONICAL_SERVICE:
        blockers.append("PAPER_SERVICE_AUTHORITY_MISMATCH")
    if root.get("sender_free") is not True or root.get("live_enabled") is not False:
        blockers.append("RUNTIME_SAFETY_BOUNDARY_INVALID")

    lifecycle = str(data.get("lifecycle_authority", ""))
    capital = str(data.get("capital_authority", ""))
    if lifecycle != EXPECTED_LIFECYCLE_AUTHORITY:
        blockers.append("LIFECYCLE_AUTHORITY_MISMATCH")
    if capital != EXPECTED_CAPITAL_AUTHORITY:
        blockers.append("CAPITAL_AUTHORITY_MISMATCH")

    alternates = _object_list(data, "alternate_runtime_surfaces", blockers)
    for item in alternates:
        if item.get("active") is True:
            blockers.append(f"ALTERNATE_RUNTIME_ACTIVE:{item.get('path')}")
        if item.get("disposition") not in {
            "compatibility-wrapper",
            "quarantined",
            "removed-from-package",
        }:
            blockers.append(
                f"ALTERNATE_RUNTIME_DISPOSITION_INVALID:{item.get('path')}"
            )

    sensitive_writes = _object_list(data, "sensitive_writes", blockers)
    required = set(SENSITIVE_WRITE_INVARIANTS)
    for item in sensitive_writes:
        invariants = set(_strings(item, "invariants", blockers))
        missing = required - invariants
        if missing:
            blockers.append(
                "SENSITIVE_WRITE_INVARIANTS_MISSING:"
                f"{item.get('surface')}:{sorted(missing)}"
            )
        if item.get("single_transaction") is not True:
            blockers.append(
                f"SENSITIVE_WRITE_NOT_TRANSACTIONAL:{item.get('surface')}"
            )

    terminal = _mapping(data, "terminal_policy", blockers)
    if terminal.get("irreversible") is not True:
        blockers.append("TERMINAL_POLICY_MUST_BE_IRREVERSIBLE")
    if terminal.get("terminal_and_outbox_same_transaction") is not True:
        blockers.append("TERMINAL_OUTBOX_ATOMICITY_MISSING")
    if terminal.get("terminal_visibility_after_result_commit_only") is not True:
        blockers.append("TERMINAL_VISIBILITY_ORDERING_MISSING")

    capital_policy = _mapping(data, "capital_reservation_policy", blockers)
    for key in (
        "compare_balance_and_reserve_same_transaction",
        "global_unique_reservation_id",
        "restart_reconciliation_required",
        "release_on_terminal_reject_or_expiry",
    ):
        if capital_policy.get(key) is not True:
            blockers.append(f"CAPITAL_POLICY_MISSING:{key}")
    bindings = set(_strings(capital_policy, "reservation_id_bindings", blockers))
    required_bindings = {
        "attempt_id",
        "attempt_generation",
        "candidate_id",
        "message_hash",
        "policy_bundle_hash",
    }
    if missing := required_bindings - bindings:
        blockers.append(f"CAPITAL_BINDINGS_MISSING:{sorted(missing)}")

    worker_policy = _mapping(data, "worker_supervision", blockers)
    if worker_policy.get("critical_worker_death_closes_readiness") is not True:
        blockers.append("CRITICAL_WORKER_DEATH_NOT_READINESS_BLOCKER")
    if worker_policy.get("bounded_queues_required") is not True:
        blockers.append("BOUNDED_QUEUES_NOT_REQUIRED")

    return RuntimeAuthorityReport(
        accepted=not blockers,
        schema_version=RUNTIME_AUTHORITY_SCHEMA,
        active_composition_root=observed_root,
        lifecycle_authority=lifecycle or None,
        capital_authority=capital or None,
        blockers=tuple(dict.fromkeys(blockers)),
        observed={
            "alternate_runtime_surfaces": len(alternates),
            "sensitive_write_surfaces": len(sensitive_writes),
            "terminal_states": sorted(TERMINAL_STATES),
            "required_sensitive_write_invariants": list(SENSITIVE_WRITE_INVARIANTS),
        },
    )


def _root_name(root: Mapping[str, Any]) -> str | None:
    module = root.get("module")
    callable_name = root.get("callable")
    if isinstance(module, str) and isinstance(callable_name, str):
        return f"{module}:{callable_name}"
    return None


def _mapping(
    data: Mapping[str, Any], key: str, blockers: list[str]
) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        blockers.append(f"{key.upper()}_MUST_BE_OBJECT")
        return {}
    return value


def _object_list(
    data: Mapping[str, Any], key: str, blockers: list[str]
) -> tuple[Mapping[str, Any], ...]:
    value = data.get(key)
    if not isinstance(value, list):
        blockers.append(f"{key.upper()}_MUST_BE_ARRAY")
        return ()
    output: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            blockers.append(f"{key.upper()}_ENTRIES_MUST_BE_OBJECTS")
            continue
        output.append(item)
    return tuple(output)


def _strings(
    data: Mapping[str, Any], key: str, blockers: list[str]
) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        blockers.append(f"{key.upper()}_MUST_BE_STRING_ARRAY")
        return ()
    return tuple(value)


__all__ = [
    "AttemptGeneration",
    "RuntimeAuthorityError",
    "RuntimeAuthorityReport",
    "SemanticCommandIdentity",
    "SemanticIdempotencyLedger",
    "TerminalState",
    "TerminalTransitionTable",
    "TransitionDecision",
    "evaluate_runtime_authority_map",
    "load_default_authority_map",
]
