"""PR-124 on-chain program deployment attestation and drift gate.

Offline evidence contract for proving that an allowlisted Solana program address
matches the expected deployed code before it can grant execution capability.
Address + owner alone must never be enough.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re

PR124_SCHEMA_VERSION = "pr124.program-deployment-attestation.v1"
PR124_RESULT_SCHEMA_VERSION = "pr124.program-deployment-attestation-result.v1"
BPF_UPGRADEABLE_LOADER_ID = "BPFLoaderUpgradeab1e11111111111111111111111"
REQUIRED_PROGRAM_LABELS = frozenset(
    {
        "marginfi",
        "jupiter-aggregator",
        "token",
        "token-2022",
        "associated-token-account",
    },
)

_PUBKEY_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ACTIONS = frozenset(
    {"startup", "periodic", "promotion", "release", "programdata-change"},
)


class PR124AttestationError(ValueError):
    """Raised when PR-124 attestation input is invalid."""


class ProgramAdmission(StrEnum):
    ACTIVE = "active"
    DISCOVERY_ONLY = "discovery-only"
    DISABLED = "disabled"


class AuthorityPolicy(StrEnum):
    IMMUTABLE = "immutable"
    FIXED = "fixed-upgrade-authority"
    ALLOWLIST = "allowlisted-upgrade-authority"


@dataclass(frozen=True, slots=True)
class ProgramAttestation:
    label: str
    program_id: str
    execution_allowed: bool
    degraded_discovery_allowed: bool
    operator_alert: bool
    blockers: tuple[str, ...]
    drift_events: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PR124EvaluationResult:
    schema_version: str
    attestation_action: str
    execution_capability_allowed: bool
    degraded_discovery_allowed: bool
    operator_alert: bool
    cluster_identity_reviewed: bool
    program_results: tuple[ProgramAttestation, ...]
    blockers: tuple[str, ...]
    drift_events: tuple[str, ...]
    reattestation_required: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_pr124_program_attestation(
    registry: Mapping[str, object],
    evidence: Mapping[str, object],
    *,
    attestation_action: str,
    explicit_degraded_discovery_mode: bool = False,
) -> PR124EvaluationResult:
    """Evaluate deployment evidence without live RPC/network calls."""

    if attestation_action not in _ACTIONS:
        raise PR124AttestationError(f"unsupported action: {attestation_action}")

    blockers: list[str] = []
    drift: list[str] = []
    if _string(registry, "schema_version") != PR124_SCHEMA_VERSION:
        blockers.append("PR124_SCHEMA_UNSUPPORTED")

    cluster_reviewed = _check_cluster(registry, blockers, drift)
    programs = tuple(_program(item) for item in _sequence(registry, "programs"))
    evidence_by_id = _evidence_by_program_id(evidence)

    covered = {str(item["label"]) for item in programs}
    for label in sorted(REQUIRED_PROGRAM_LABELS - covered):
        blockers.append(f"PR124_REQUIRED_PROGRAM_CLASS_MISSING:{label}")

    results = []
    for program in programs:
        result = _check_program(
            program,
            evidence_by_id.get(str(program["program_id"])),
            explicit_degraded_discovery_mode,
        )
        results.append(result)
        blockers.extend(result.blockers)
        drift.extend(result.drift_events)

    unique_blockers = tuple(dict.fromkeys(blockers))
    unique_drift = tuple(dict.fromkeys(drift))
    active_results = _active_results(programs, results)
    execution_allowed = (
        cluster_reviewed
        and bool(active_results)
        and not unique_blockers
        and not unique_drift
        and all(item.execution_allowed for item in active_results)
    )
    degraded_allowed = (
        explicit_degraded_discovery_mode
        and not execution_allowed
        and any(item.degraded_discovery_allowed for item in results)
    )
    operator_alert = bool(unique_drift) or any(item.operator_alert for item in results)

    return PR124EvaluationResult(
        schema_version=PR124_RESULT_SCHEMA_VERSION,
        attestation_action=attestation_action,
        execution_capability_allowed=execution_allowed,
        degraded_discovery_allowed=degraded_allowed,
        operator_alert=operator_alert,
        cluster_identity_reviewed=cluster_reviewed,
        program_results=tuple(results),
        blockers=unique_blockers,
        drift_events=unique_drift,
        reattestation_required=True,
    )


def make_program_evidence_hash(payload: Mapping[str, object]) -> str:
    """Return canonical PR-124 hash for one program evidence object."""

    canonical = dict(payload)
    canonical["evidence_hash"] = None
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _evidence_by_program_id(
    evidence: Mapping[str, object],
) -> dict[str, Mapping[str, object]]:
    by_program_id = {}
    for item in _sequence(evidence, "programs", default=()):
        observed = _mapping(item, "evidence")
        by_program_id[_pubkey(observed, "program_id")] = observed
    return by_program_id


def _active_results(
    programs: Sequence[Mapping[str, object]],
    results: Sequence[ProgramAttestation],
) -> tuple[ProgramAttestation, ...]:
    active = []
    for result in results:
        program = _find_program(programs, result.program_id)
        if program["admission"] is ProgramAdmission.ACTIVE:
            active.append(result)
    return tuple(active)


def _check_cluster(
    registry: Mapping[str, object],
    blockers: list[str],
    drift: list[str],
) -> bool:
    cluster = _mapping(registry.get("cluster"), "cluster")
    expected = _string(cluster, "expected_genesis_hash")
    observed = _optional_string(cluster, "observed_genesis_hash")
    reviewed = _bool(cluster, "reviewed", default=False)
    reviewer = _optional_string(cluster, "reviewer")

    if not _PUBKEY_RE.fullmatch(expected):
        blockers.append("PR124_CLUSTER_EXPECTED_GENESIS_HASH_INVALID")
    if observed is None:
        blockers.append("PR124_CLUSTER_OBSERVED_GENESIS_HASH_MISSING")
    elif not _PUBKEY_RE.fullmatch(observed):
        blockers.append("PR124_CLUSTER_OBSERVED_GENESIS_HASH_INVALID")
    elif observed != expected:
        drift.append("PR124_CLUSTER_GENESIS_HASH_DRIFT")
    if not reviewed or not (reviewer or "").strip():
        blockers.append("PR124_CLUSTER_IDENTITY_NOT_REVIEWED")
    if not _valid_sha(_optional_string(cluster, "evidence_hash")):
        blockers.append("PR124_CLUSTER_EVIDENCE_HASH_INVALID")
    return reviewed and bool((reviewer or "").strip())


def _program(raw: object) -> dict[str, object]:
    item = _mapping(raw, "program")
    return {
        "label": _string(item, "label"),
        "program_id": _pubkey(item, "program_id"),
        "admission": ProgramAdmission(_string(item, "admission")),
        "owner": _pubkey(item, "expected_account_owner"),
        "loader": _pubkey(item, "expected_loader"),
        "executable": _bool(item, "expected_executable", default=True),
        "code_hash": _optional_sha(item, "expected_code_hash"),
        "authority_policy": AuthorityPolicy(_string(item, "authority_policy")),
        "programdata_address": _optional_pubkey(
            item,
            "expected_programdata_address",
        ),
        "expected_authority": _optional_pubkey(
            item,
            "expected_upgrade_authority",
        ),
        "allowed_authorities": _allowed_authorities(item),
        "required": _bool(item, "required", default=True),
    }


def _allowed_authorities(item: Mapping[str, object]) -> tuple[str, ...]:
    authorities = []
    for value in _sequence(item, "allowed_upgrade_authorities", default=()):
        authorities.append(_pubkey_value(value, "allowed_upgrade_authorities[]"))
    return tuple(authorities)


def _check_program(
    expected: Mapping[str, object],
    observed: Mapping[str, object] | None,
    explicit_degraded: bool,
) -> ProgramAttestation:
    label = str(expected["label"])
    program_id = str(expected["program_id"])
    admission = expected["admission"]
    if admission is not ProgramAdmission.ACTIVE:
        return ProgramAttestation(
            label=label,
            program_id=program_id,
            execution_allowed=False,
            degraded_discovery_allowed=admission is ProgramAdmission.DISCOVERY_ONLY,
            operator_alert=False,
            blockers=(),
            drift_events=(),
        )
    if observed is None:
        return ProgramAttestation(
            label=label,
            program_id=program_id,
            execution_allowed=False,
            degraded_discovery_allowed=explicit_degraded,
            operator_alert=bool(expected["required"]),
            blockers=(f"PR124_PROGRAM_EVIDENCE_MISSING:{label}",),
            drift_events=(),
        )

    blockers = _evidence_blockers(expected, observed)
    drift = _drift_events(expected, observed)
    allowed = not blockers and not drift
    return ProgramAttestation(
        label=label,
        program_id=program_id,
        execution_allowed=allowed,
        degraded_discovery_allowed=explicit_degraded and not allowed,
        operator_alert=bool(drift),
        blockers=tuple(blockers),
        drift_events=tuple(drift),
    )


def _evidence_blockers(
    expected: Mapping[str, object],
    observed: Mapping[str, object],
) -> list[str]:
    label = str(expected["label"])
    blockers: list[str] = []
    required = {
        "ACCOUNT_OWNER": observed.get("account_owner"),
        "EXECUTABLE_FLAG": observed.get("executable"),
        "LOADER": observed.get("loader"),
        "PROGRAMDATA_ADDRESS": observed.get("programdata_address"),
        "DEPLOYED_SLOT": observed.get("deployed_slot"),
        "ATTESTED_SLOT": observed.get("attested_at_slot"),
        "ATTESTED_TIME": observed.get("attested_at_utc"),
    }
    for name, value in required.items():
        if value is None:
            blockers.append(f"PR124_{name}_MISSING:{label}")
    if not _valid_sha(_optional_string(observed, "executable_hash")):
        blockers.append(f"PR124_EXECUTABLE_HASH_MISSING:{label}")
    if not _valid_sha(str(expected["code_hash"])):
        blockers.append(f"PR124_EXPECTED_CODE_HASH_MISSING:{label}")
    if not _valid_sha(_optional_string(observed, "evidence_hash")):
        program_id = observed.get("program_id")
        blockers.append(f"PR124_EVIDENCE_HASH_INVALID:{program_id}")
    elif observed["evidence_hash"] != make_program_evidence_hash(observed):
        blockers.append(f"PR124_EVIDENCE_HASH_MISMATCH:{observed['program_id']}")
    if expected["authority_policy"] is AuthorityPolicy.FIXED:
        if expected["expected_authority"] is None:
            blockers.append(f"PR124_EXPECTED_UPGRADE_AUTHORITY_MISSING:{label}")
    if expected["authority_policy"] is AuthorityPolicy.ALLOWLIST:
        if not expected["allowed_authorities"]:
            blockers.append(f"PR124_UPGRADE_AUTHORITY_ALLOWLIST_MISSING:{label}")
    return blockers


def _drift_events(
    expected: Mapping[str, object],
    observed: Mapping[str, object],
) -> list[str]:
    label = str(expected["label"])
    drift: list[str] = []
    checks = (
        ("ACCOUNT_OWNER", observed.get("account_owner"), expected["owner"]),
        ("LOADER", observed.get("loader"), expected["loader"]),
        ("EXECUTABLE_FLAG", observed.get("executable"), expected["executable"]),
        ("EXECUTABLE_HASH", observed.get("executable_hash"), expected["code_hash"]),
        (
            "PROGRAMDATA_ADDRESS",
            observed.get("programdata_address"),
            expected["programdata_address"],
        ),
    )
    for name, actual, wanted in checks:
        if wanted is not None and actual != wanted:
            drift.append(f"PR124_{name}_DRIFT:{label}")

    policy = expected["authority_policy"]
    authority = observed.get("upgrade_authority")
    if policy is AuthorityPolicy.IMMUTABLE and authority is not None:
        drift.append(f"PR124_UPGRADE_AUTHORITY_DRIFT:{label}")
    if policy is AuthorityPolicy.FIXED and authority != expected["expected_authority"]:
        drift.append(f"PR124_UPGRADE_AUTHORITY_DRIFT:{label}")
    if policy is AuthorityPolicy.ALLOWLIST:
        if authority not in expected["allowed_authorities"]:
            drift.append(f"PR124_UPGRADE_AUTHORITY_DRIFT:{label}")
    if (
        observed.get("observed_programdata_address") is not None
        and observed.get("observed_programdata_address")
        != observed.get("programdata_address")
    ):
        drift.append(f"PR124_OBSERVED_PROGRAMDATA_CHANGE:{label}")
    return drift


def _find_program(
    programs: Sequence[Mapping[str, object]],
    program_id: str,
) -> Mapping[str, object]:
    for program in programs:
        if program["program_id"] == program_id:
            return program
    raise PR124AttestationError(f"missing expectation for {program_id}")


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PR124AttestationError(f"FIELD_NOT_OBJECT:{field}")
    return value


def _sequence(
    payload: Mapping[str, object],
    field: str,
    *,
    default: Sequence[object] | None = None,
) -> Sequence[object]:
    value = payload.get(field, default)
    if not isinstance(value, (list, tuple)):
        raise PR124AttestationError(f"FIELD_NOT_LIST:{field}")
    return value


def _string(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise PR124AttestationError(f"FIELD_NOT_STRING:{field}")
    return value


def _optional_string(payload: Mapping[str, object], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise PR124AttestationError(f"FIELD_NOT_STRING:{field}")
    return value


def _bool(
    payload: Mapping[str, object],
    field: str,
    *,
    default: bool | None = None,
) -> bool:
    value = payload.get(field, default)
    if not isinstance(value, bool):
        raise PR124AttestationError(f"FIELD_NOT_BOOL:{field}")
    return value


def _pubkey(payload: Mapping[str, object], field: str) -> str:
    return _pubkey_value(_string(payload, field), field)


def _optional_pubkey(payload: Mapping[str, object], field: str) -> str | None:
    value = _optional_string(payload, field)
    if value is None:
        return None
    return _pubkey_value(value, field)


def _pubkey_value(value: object, field: str) -> str:
    if not isinstance(value, str) or not _PUBKEY_RE.fullmatch(value):
        raise PR124AttestationError(f"FIELD_NOT_PUBKEY:{field}")
    return value


def _optional_sha(payload: Mapping[str, object], field: str) -> str | None:
    value = _optional_string(payload, field)
    if value is None:
        return None
    if not _valid_sha(value):
        raise PR124AttestationError(f"FIELD_NOT_SHA256:{field}")
    return value


def _valid_sha(value: str | None) -> bool:
    return (
        isinstance(value, str)
        and bool(_SHA_RE.fullmatch(value))
        and value != ("0" * 64)
    )


def _optional_positive_int(payload: Mapping[str, object], field: str) -> int | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PR124AttestationError(f"FIELD_NOT_POSITIVE_INT:{field}")
    return value


def _optional_utc(payload: Mapping[str, object], field: str) -> str | None:
    value = _optional_string(payload, field)
    if value is None:
        return None
    if not _UTC_RE.fullmatch(value):
        raise PR124AttestationError(f"FIELD_NOT_UTC_SECOND:{field}")
    return value


def _self_check_payload() -> tuple[dict[str, object], dict[str, object]]:
    program_id = "Prog111111111111111111111111111111111111111"
    registry = _fixture_registry(program_id)
    evidence: dict[str, object] = {
        "program_id": program_id,
        "account_owner": BPF_UPGRADEABLE_LOADER_ID,
        "executable": True,
        "loader": BPF_UPGRADEABLE_LOADER_ID,
        "programdata_address": "Data111111111111111111111111111111111111111",
        "deployed_slot": 123,
        "upgrade_authority": None,
        "executable_hash": "b" * 64,
        "attested_at_slot": 456,
        "attested_at_utc": "2026-07-21T00:00:00Z",
        "evidence_hash": None,
        "observed_programdata_address": "Data111111111111111111111111111111111111111",
    }
    evidence["evidence_hash"] = make_program_evidence_hash(evidence)
    return registry, {"programs": [evidence]}


def _fixture_registry(active_program_id: str) -> dict[str, object]:
    def entry(
        label: str,
        program_id: str,
        admission: str,
    ) -> dict[str, object]:
        return {
            "label": label,
            "program_id": program_id,
            "admission": admission,
            "expected_account_owner": BPF_UPGRADEABLE_LOADER_ID,
            "expected_loader": BPF_UPGRADEABLE_LOADER_ID,
            "expected_executable": True,
            "expected_code_hash": "b" * 64,
            "authority_policy": "immutable",
            "expected_programdata_address": (
                "Data111111111111111111111111111111111111111"
            ),
            "required": True,
        }

    return {
        "schema_version": PR124_SCHEMA_VERSION,
        "cluster": {
            "cluster": "mainnet-beta",
            "expected_genesis_hash": "Gen111111111111111111111111111111111111111",
            "observed_genesis_hash": "Gen111111111111111111111111111111111111111",
            "reviewed": True,
            "reviewer": "operator",
            "evidence_hash": "a" * 64,
        },
        "programs": [
            entry(
                "marginfi",
                "Marg11111111111111111111111111111111111111",
                "discovery-only",
            ),
            entry(
                "jupiter-aggregator",
                "Jup1111111111111111111111111111111111111111",
                "discovery-only",
            ),
            entry("token", active_program_id, "active"),
            entry(
                "token-2022",
                "T2211111111111111111111111111111111111111",
                "discovery-only",
            ),
            entry(
                "associated-token-account",
                "ATA111111111111111111111111111111111111111",
                "discovery-only",
            ),
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the offline PR-124 deployment-attestation self-check.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    registry, evidence = _self_check_payload()
    result = evaluate_pr124_program_attestation(
        registry,
        evidence,
        attestation_action="startup",
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(
            "PR-124 execution capability allowed: "
            f"{result.execution_capability_allowed}",
        )
    return 0 if result.execution_capability_allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AuthorityPolicy",
    "BPF_UPGRADEABLE_LOADER_ID",
    "PR124AttestationError",
    "PR124EvaluationResult",
    "PR124_RESULT_SCHEMA_VERSION",
    "PR124_SCHEMA_VERSION",
    "ProgramAdmission",
    "ProgramAttestation",
    "REQUIRED_PROGRAM_LABELS",
    "evaluate_pr124_program_attestation",
    "main",
    "make_program_evidence_hash",
]
