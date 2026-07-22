"""PR-137 simulation CPI call graph and route provenance gate.

This module is an offline, fail-closed evidence boundary for simulation reports.
It does not call RPC, providers, Jito, wallets, signers, senders or live paths.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any

PR137_SCHEMA_VERSION = "pr137.simulation-cpi-call-graph.v1"
PR137_RESULT_SCHEMA_VERSION = "pr137.simulation-cpi-call-graph-result.v1"
PR137_READY_STATE = "simulation-cpi-call-graph-review-ready"
PR137_BLOCKED_STATE = "blocked"

COMPUTE_BUDGET_PROGRAM_ID = "ComputeBudget111111111111111111111111111111"
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFJmNchboJLH2e2UrfW"
ATA_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA4knL"

_ALLOWED_UTILITY_PROGRAMS = frozenset(
    {
        COMPUTE_BUDGET_PROGRAM_ID,
        SYSTEM_PROGRAM_ID,
        TOKEN_PROGRAM_ID,
        TOKEN_2022_PROGRAM_ID,
        ATA_PROGRAM_ID,
    }
)
_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PR137CallGraphState(StrEnum):
    BLOCKED = PR137_BLOCKED_STATE
    REVIEW_READY = PR137_READY_STATE


class PR137CallGraphError(ValueError):
    """Raised when PR-137 call-graph evidence is malformed."""


@dataclass(frozen=True, slots=True)
class PR137RouteProgramIdentity:
    """Attested program identity for one planned route segment."""

    route_segment_id: str
    label: str
    program_id: str
    deployment_attestation_sha256: str
    expected_cpi_families: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty(self.route_segment_id, "route_segment_id")
        _require_non_empty(self.label, "label")
        _require_program_id(self.program_id, "program_id")
        _require_sha256(
            self.deployment_attestation_sha256,
            "deployment_attestation_sha256",
        )
        for family in self.expected_cpi_families:
            _require_non_empty(family, "expected_cpi_families[]")


@dataclass(frozen=True, slots=True)
class PR137InstructionObservation:
    """One observed top-level or inner instruction program call."""

    program_id: str
    instruction_path: tuple[int, ...]
    source: str
    route_segment_id: str | None = None
    semantic_family: str | None = None
    transfer_checked: bool = True

    def __post_init__(self) -> None:
        _require_program_id(self.program_id, "program_id")
        if not self.instruction_path:
            raise PR137CallGraphError("instruction_path is required")
        for index in self.instruction_path:
            if not isinstance(index, int) or index < 0:
                raise PR137CallGraphError("instruction_path values must be >= 0")
        if self.source not in {"top_level", "inner"}:
            raise PR137CallGraphError("source must be top_level or inner")
        if self.route_segment_id is not None:
            _require_non_empty(self.route_segment_id, "route_segment_id")
        if self.semantic_family is not None:
            _require_non_empty(self.semantic_family, "semantic_family")
        if type(self.transfer_checked) is not bool:
            raise PR137CallGraphError("transfer_checked must be boolean")


@dataclass(frozen=True, slots=True)
class PR137ExpectedRouteGraph:
    """Planned route graph that simulation evidence must match."""

    top_level_program_ids: tuple[str, ...]
    route_programs: tuple[PR137RouteProgramIdentity, ...]
    utility_program_ids: tuple[str, ...] = tuple(sorted(_ALLOWED_UTILITY_PROGRAMS))
    token_2022_transfer_hook_program_ids: tuple[str, ...] = ()
    allow_system_transfer: bool = False
    schema_version: str = PR137_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR137_SCHEMA_VERSION:
            raise PR137CallGraphError("unsupported PR-137 expected graph schema")
        if not self.top_level_program_ids:
            raise PR137CallGraphError("top_level_program_ids is required")
        for program_id in self.top_level_program_ids:
            _require_program_id(program_id, "top_level_program_ids[]")
        if not self.route_programs:
            raise PR137CallGraphError("route_programs is required")
        seen_segments: set[str] = set()
        seen_programs: set[str] = set()
        for route_program in self.route_programs:
            if route_program.route_segment_id in seen_segments:
                raise PR137CallGraphError("duplicate route_segment_id")
            seen_segments.add(route_program.route_segment_id)
            if route_program.program_id in seen_programs:
                raise PR137CallGraphError("duplicate route program identity")
            seen_programs.add(route_program.program_id)
        for program_id in self.utility_program_ids:
            _require_program_id(program_id, "utility_program_ids[]")
        for program_id in self.token_2022_transfer_hook_program_ids:
            _require_program_id(program_id, "token_2022_transfer_hook_program_ids[]")
        if type(self.allow_system_transfer) is not bool:
            raise PR137CallGraphError("allow_system_transfer must be boolean")


@dataclass(frozen=True, slots=True)
class PR137SimulationCallGraphEvidence:
    """Observed simulation CPI evidence produced with innerInstructions=true."""

    inner_instructions_requested: bool
    inner_instructions_present: bool
    loaded_addresses_present: bool
    return_data_preserved: bool
    account_keys_preserved: bool
    logs_truncated: bool
    observations: tuple[PR137InstructionObservation, ...]
    expected_call_graph_sha256: str | None = None
    schema_version: str = PR137_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR137_SCHEMA_VERSION:
            raise PR137CallGraphError("unsupported PR-137 evidence schema")
        for name in (
            "inner_instructions_requested",
            "inner_instructions_present",
            "loaded_addresses_present",
            "return_data_preserved",
            "account_keys_preserved",
            "logs_truncated",
        ):
            if type(getattr(self, name)) is not bool:
                raise PR137CallGraphError(f"{name} must be boolean")
        if not self.observations:
            raise PR137CallGraphError("observations are required")
        if self.expected_call_graph_sha256 is not None:
            _require_sha256(
                self.expected_call_graph_sha256,
                "expected_call_graph_sha256",
            )

    @property
    def observed_program_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted({observation.program_id for observation in self.observations})
        )

    @property
    def call_graph_sha256(self) -> str:
        payload = [
            {
                "instruction_path": list(observation.instruction_path),
                "program_id": observation.program_id,
                "route_segment_id": observation.route_segment_id,
                "semantic_family": observation.semantic_family,
                "source": observation.source,
                "transfer_checked": observation.transfer_checked,
            }
            for observation in sorted(
                self.observations,
                key=lambda item: (item.instruction_path, item.program_id),
            )
        ]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class PR137CallGraphReadiness:
    schema_version: str
    state: PR137CallGraphState
    review_ready: bool
    execution_allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    observed_program_ids: tuple[str, ...]
    expected_route_program_ids: tuple[str, ...]
    call_graph_sha256: str
    checks_evaluated: int
    metrics_summary: Mapping[str, int | str | bool]

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_pr137_simulation_cpi_call_graph(
    *,
    expected: PR137ExpectedRouteGraph,
    evidence: PR137SimulationCallGraphEvidence,
) -> PR137CallGraphReadiness:
    """Evaluate whether simulation call-graph evidence is review-ready."""

    blockers: list[str] = []
    checks = 0

    def check(condition: bool, reason: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            blockers.append(reason)

    check(evidence.inner_instructions_requested, "INNER_INSTRUCTIONS_NOT_REQUESTED")
    check(evidence.inner_instructions_present, "INNER_INSTRUCTIONS_MISSING")
    check(evidence.loaded_addresses_present, "LOADED_ADDRESSES_MISSING")
    check(evidence.return_data_preserved, "RETURN_DATA_NOT_PRESERVED")
    check(evidence.account_keys_preserved, "ACCOUNT_KEYS_NOT_PRESERVED")
    check(not evidence.logs_truncated, "SIMULATION_LOGS_TRUNCATED")

    top_level_seen = {
        item.program_id for item in evidence.observations if item.source == "top_level"
    }
    inner_seen = {
        item.program_id for item in evidence.observations if item.source == "inner"
    }
    route_by_segment = {
        item.route_segment_id: item.program_id for item in expected.route_programs
    }
    route_program_ids = {item.program_id for item in expected.route_programs}
    top_level_program_ids = set(expected.top_level_program_ids)
    utility_program_ids = set(expected.utility_program_ids)
    hook_program_ids = set(expected.token_2022_transfer_hook_program_ids)
    allowed_program_ids = (
        route_program_ids
        | top_level_program_ids
        | utility_program_ids
        | hook_program_ids
    )

    check(bool(top_level_seen), "TOP_LEVEL_PROGRAMS_MISSING")
    check(bool(inner_seen), "CPI_INNER_PROGRAMS_MISSING")

    for program_id in sorted(top_level_program_ids):
        check(program_id in top_level_seen, f"TOP_LEVEL_PROGRAM_MISSING:{program_id}")

    for route_program in expected.route_programs:
        observed_segment = any(
            item.route_segment_id == route_program.route_segment_id
            and item.program_id == route_program.program_id
            for item in evidence.observations
        )
        check(
            observed_segment,
            f"ROUTE_SEGMENT_PROGRAM_MISSING:{route_program.route_segment_id}",
        )

    for program_id in evidence.observed_program_ids:
        check(program_id in allowed_program_ids, f"UNEXPECTED_PROGRAM:{program_id}")

    for observation in evidence.observations:
        if observation.program_id == SYSTEM_PROGRAM_ID:
            check(
                expected.allow_system_transfer or observation.transfer_checked,
                "SYSTEM_TRANSFER_WITHOUT_SEMANTIC_CHECK",
            )
        if observation.program_id == TOKEN_2022_PROGRAM_ID:
            check(
                observation.transfer_checked,
                "TOKEN_2022_TRANSFER_WITHOUT_EXTENSION_POLICY",
            )
        if observation.route_segment_id is not None:
            check(
                route_by_segment.get(observation.route_segment_id)
                == observation.program_id,
                f"ROUTE_SEGMENT_PROGRAM_MISMATCH:{observation.route_segment_id}",
            )

    if evidence.expected_call_graph_sha256 is not None:
        check(
            evidence.call_graph_sha256 == evidence.expected_call_graph_sha256,
            "CALL_GRAPH_HASH_MISMATCH",
        )

    unique = tuple(dict.fromkeys(blockers))
    ready = not unique
    return PR137CallGraphReadiness(
        schema_version=PR137_RESULT_SCHEMA_VERSION,
        state=(
            PR137CallGraphState.REVIEW_READY
            if ready
            else PR137CallGraphState.BLOCKED
        ),
        review_ready=ready,
        execution_allowed=False,
        blockers=unique,
        warnings=("PR137_REVIEW_ONLY_ACTIVE_RUNTIME_UNCHANGED",),
        observed_program_ids=evidence.observed_program_ids,
        expected_route_program_ids=tuple(sorted(route_program_ids)),
        call_graph_sha256=evidence.call_graph_sha256,
        checks_evaluated=checks,
        metrics_summary={
            "observed_program_count": len(evidence.observed_program_ids),
            "route_program_count": len(route_program_ids),
            "top_level_program_count": len(top_level_seen),
            "inner_program_count": len(inner_seen),
            "execution_allowed": False,
        },
    )


def assert_pr137_simulation_cpi_call_graph(
    *,
    expected: PR137ExpectedRouteGraph,
    evidence: PR137SimulationCallGraphEvidence,
) -> PR137CallGraphReadiness:
    result = evaluate_pr137_simulation_cpi_call_graph(
        expected=expected,
        evidence=evidence,
    )
    if not result.review_ready:
        raise PR137CallGraphError(f"PR137_BLOCKED:{','.join(result.blockers)}")
    return result


def _require_non_empty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PR137CallGraphError(f"{name} is required")


def _require_program_id(value: str, name: str) -> None:
    _require_non_empty(value, name)
    if not _BASE58_RE.fullmatch(value):
        raise PR137CallGraphError(f"{name} must be a base58 Solana program id")


def _require_sha256(value: str, name: str) -> None:
    _require_non_empty(value, name)
    if not _SHA256_RE.fullmatch(value):
        raise PR137CallGraphError(f"{name} must be a SHA-256 digest")


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value
