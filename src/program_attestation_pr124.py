"""PR-124 on-chain program deployment attestation and drift gate.

This module is intentionally offline. It models the evidence boundary that a
future online attestor must satisfy before an allowlisted Solana program address
can contribute to execution capability.

PR-124 invariant: address + owner alone can never grant execution capability.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any

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
    }
)

_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ISO8601_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ACTIONS_REQUIRING_ATTESTATION = frozenset(
    {"startup", "periodic", "promotion", "release", "programdata-change"}
)


class PR124AttestationError(ValueError):
    """Raised when PR-124 input is structurally invalid."""


class ProgramAdmission(StrEnum):
    """Program execution admission requested by the registry."""

    ACTIVE = "active"
    DISCOVERY_ONLY = "discovery-only"
    DISABLED = "disabled"


class AuthorityPolicy(StrEnum):
    """Expected authority semantics for a program deployment."""

    IMMUTABLE = "immutable"
    FIXED = "fixed-upgrade-authority"
    ALLOWLIST = "allowlisted-upgrade-authority"


@dataclass(frozen=True, slots=True)
class ClusterIdentity:
    """Reviewed cluster identity expected before any execution promotion."""

    cluster: str
    expected_genesis_hash: str
    observed_genesis_hash: str | None
    reviewed: bool
    reviewer: str | None
    evidence_hash: str | None
    source: str = ""


@dataclass(frozen=True, slots=True)
class SourcePin:
    """Optional verified build/source pin."""

    source_ref: str
    sha256: str
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class ProgramExpectation:
    """Registry expectation for one active or discovery program."""

    label: str
    program_id: str
    admission: ProgramAdmission
    expected_account_owner: str
    expected_loader: str
    expected_executable: bool
    expected_code_hash: str | None
    authority_policy: AuthorityPolicy
    expected_upgrade_authority: str | None = None
    allowed_upgrade_authorities: tuple[str, ...] = ()
    expected_programdata_address: str | None = None
    verified_source_pin: SourcePin | None = None
    required: bool = True


@dataclass(frozen=True, slots=True)
class ProgramEvidence:
    """Observed deployment evidence collected from chain state."""

    program_id: str
    account_owner: str | None
    executable: bool | None
    loader: str | None
    programdata_address: str | None
    deployed_slot: int | None
    upgrade_authority: str | None
    executable_hash: str | None
    attested_at_slot: int | None
    attested_at_utc: str | None
    evidence_hash: str | None
    observed_programdata_address: str | None = None


@dataclass(frozen=True, slots=True)
class ProgramAttestation:
    """Evaluation result for one program."""

    label: str
    program_id: str
    execution_allowed: bool
    degraded_discovery_allowed: bool
    operator_alert: bool
    blockers: tuple[str, ...]
    drift_events: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PR124EvaluationResult:
    """Whole-registry PR-124 deployment-attestation decision."""

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
    """Evaluate PR-124 deployment attestation without making network calls."""

    if attestation_action not in _ACTIONS_REQUIRING_ATTESTATION:
        raise PR124AttestationError(f"unsupported attestation action: {attestation_action}")

    blockers: list[str] = []
    drift_events: list[str] = []

    schema_version = _string(registry, "schema_version")
    if schema_version != PR124_SCHEMA_VERSION:
        blockers.append(f"PR124_SCHEMA_UNSUPPORTED:{schema_version}")

    cluster = _parse_cluster_identity(_mapping(registry.get("cluster"), "cluster"))
    _validate_cluster_identity(cluster, blockers, drift_events)

    expectations = _parse_expectations(registry)
    observed_by_program_id = {
        item.program_id: item
        for item in _parse_program_evidence(_sequence(evidence, "programs", default=()))
    }

    program_results: list[ProgramAttestation] = []
    covered_labels = {expectation.label for expectation in expectations}
    missing_required_labels = REQUIRED_PROGRAM_LABELS.difference(covered_labels)
    for label in sorted(missing_required_labels):
        blockers.append(f"PR124_REQUIRED_PROGRAM_CLASS_MISSING:{label}")

    for expectation in expectations:
        result = _evaluate_program(
            expectation,
            observed_by_program_id.get(expectation.program_id),
            explicit_degraded_discovery_mode=explicit_degraded_discovery_mode,
        )
        program_results.append(result)
        blockers.extend(result.blockers)
        drift_events.extend(result.drift_events)

    unique_blockers = tuple(dict.fromkeys(blockers))
    unique_drift = tuple(dict.fromkeys(drift_events))
    active_results = [
        result
        for result in program_results
        if _expectation_by_program_id(expectations, result.program_id).admission
        is ProgramAdmission.ACTIVE
    ]
    execution_allowed = (
        cluster.reviewed
        and not unique_blockers
        and not unique_drift
        and bool(active_results)
        and all(result.execution_allowed for result in active_results)
    )
    degraded_discovery_allowed = (
        explicit_degraded_discovery_mode
        and not execution_allowed
        and any(result.degraded_discovery_allowed for result in program_results)
    )
    operator_alert = bool(unique_drift) or any(
        result.operator_alert for result in program_results
    )

    return PR124EvaluationResult(
        schema_version=PR124_RESULT_SCHEMA_VERSION,
        attestation_action=attestation_action,
        execution_capability_allowed=execution_allowed,
        degraded_discovery_allowed=degraded_discovery_allowed,
        operator_alert=operator_alert,
        cluster_identity_reviewed=cluster.reviewed,
        program_results=tuple(program_results),
        blockers=unique_blockers,
        drift_events=unique_drift,
        reattestation_required=attestation_action in _ACTIONS_REQUIRING_ATTESTATION,
    )


def _expectation_by_program_id(
    expectations: Sequence[ProgramExpectation],
    program_id: str,
) -> ProgramExpectation:
    for expectation in expectations:
        if expectation.program_id == program_id:
            return expectation
    raise PR124AttestationError(f"missing expectation for {program_id}")


def _parse_cluster_identity(payload: Mapping[str, object]) -> ClusterIdentity:
    return ClusterIdentity(
        cluster=_string(payload, "cluster"),
        expected_genesis_hash=_string(payload, "expected_genesis_hash"),
        observed_genesis_hash=_optional_string(payload, "observed_genesis_hash"),
        reviewed=_bool(payload, "reviewed", default=False),
        reviewer=_optional_string(payload, "reviewer"),
        evidence_hash=_optional_string(payload, "evidence_hash"),
        source=_string(payload, "source", default=""),
    )


def _validate_cluster_identity(
    cluster: ClusterIdentity,
    blockers: list[str],
    drift_events: list[str],
) -> None:
    if not _BASE58_RE.fullmatch(cluster.expected_genesis_hash):
        blockers.append("PR124_CLUSTER_EXPECTED_GENESIS_HASH_INVALID")
    if not cluster.observed_genesis_hash:
        blockers.append("PR124_CLUSTER_OBSERVED_GENESIS_HASH_MISSING")
    elif not _BASE58_RE.fullmatch(cluster.observed_genesis_hash):
        blockers.append("PR124_CLUSTER_OBSERVED_GENESIS_HASH_INVALID")
    elif cluster.observed_genesis_hash != cluster.expected_genesis_hash:
        drift_events.append("PR124_CLUSTER_GENESIS_HASH_DRIFT")
    if not cluster.reviewed or not (cluster.reviewer or "").strip():
        blockers.append("PR124_CLUSTER_IDENTITY_NOT_REVIEWED")
    if not _valid_sha256(cluster.evidence_hash):
        blockers.append("PR124_CLUSTER_EVIDENCE_HASH_INVALID")


def _parse_expectations(payload: Mapping[str, object]) -> tuple[ProgramExpectation, ...]:
    expectations: list[ProgramExpectation] = []
    seen: set[str] = set()
    for index, item in enumerate(_sequence(payload, "programs")):
        program = _mapping(item, f"programs[{index}]")
        expectation = ProgramExpectation(
            label=_string(program, "label"),
            program_id=_pubkey(program, "program_id"),
            admission=ProgramAdmission(_string(program, "admission")),
            expected_account_owner=_pubkey(program, "expected_account_owner"),
            expected_loader=_pubkey(program, "expected_loader"),
            expected_executable=_bool(program, "expected_executable", default=True),
            expected_code_hash=_optional_sha(program, "expected_code_hash"),
            authority_policy=AuthorityPolicy(_string(program, "authority_policy")),
            expected_upgrade_authority=_optional_pubkey(
                program, "expected_upgrade_authority"
            ),
            allowed_upgrade_authorities=tuple(
                _pubkey_value(value, "allowed_upgrade_authorities[]")
                for value in _sequence(
                    program,
                    "allowed_upgrade_authorities",
                    default=(),
                )
            ),
            expected_programdata_address=_optional_pubkey(
                program, "expected_programdata_address"
            ),
            verified_source_pin=_optional_source_pin(program.get("verified_source_pin")),
            required=_bool(program, "required", default=True),
        )
        if expectation.program_id in seen:
            raise PR124AttestationError(
                f"duplicate program expectation: {expectation.program_id}"
            )
        seen.add(expectation.program_id)
        expectations.append(expectation)
    return tuple(expectations)


def _parse_program_evidence(
    payload: Sequence[object],
) -> tuple[ProgramEvidence, ...]:
    evidence_items: list[ProgramEvidence] = []
    seen: set[str] = set()
    for index, item in enumerate(payload):
        observed = _mapping(item, f"evidence.programs[{index}]")
        evidence = ProgramEvidence(
            program_id=_pubkey(observed, "program_id"),
            account_owner=_optional_pubkey(observed, "account_owner"),
            executable=_optional_bool(observed, "executable"),
            loader=_optional_pubkey(observed, "loader"),
            programdata_address=_optional_pubkey(observed, "programdata_address"),
            deployed_slot=_optional_positive_int(observed, "deployed_slot"),
            upgrade_authority=_optional_pubkey(observed, "upgrade_authority"),
            executable_hash=_optional_sha(observed, "executable_hash"),
            attested_at_slot=_optional_positive_int(observed, "attested_at_slot"),
            attested_at_utc=_optional_utc(observed, "attested_at_utc"),
            evidence_hash=_optional_sha(observed, "evidence_hash"),
            observed_programdata_address=_optional_pubkey(
                observed,
                "observed_programdata_address",
            ),
        )
        if evidence.program_id in seen:
            raise PR124AttestationError(
                f"duplicate program evidence: {evidence.program_id}"
            )
        seen.add(evidence.program_id)
        evidence_items.append(evidence)
    return tuple(evidence_items)


def _optional_source_pin(value: object) -> SourcePin | None:
    if value is None:
        return None
    payload = _mapping(value, "verified_source_pin")
    return SourcePin(
        source_ref=_string(payload, "source_ref"),
        sha256=_sha(payload, "sha256"),
        evidence_hash=_sha(payload, "evidence_hash"),
    )


def _evaluate_program(
    expectation: ProgramExpectation,
    evidence: ProgramEvidence | None,
    *,
    explicit_degraded_discovery_mode: bool,
) -> ProgramAttestation:
    blockers: list[str] = []
    drift_events: list[str] = []

    if expectation.admission is not ProgramAdmission.ACTIVE:
        return ProgramAttestation(
            label=expectation.label,
            program_id=expectation.program_id,
            execution_allowed=False,
            degraded_discovery_allowed=expectation.admission
            is ProgramAdmission.DISCOVERY_ONLY,
            operator_alert=False,
            blockers=(),
            drift_events=(),
        )

    if evidence is None:
        return ProgramAttestation(
            label=expectation.label,
            program_id=expectation.program_id,
            execution_allowed=False,
            degraded_discovery_allowed=explicit_degraded_discovery_mode,
            operator_alert=True if expectation.required else False,
            blockers=(f"PR124_PROGRAM_EVIDENCE_MISSING:{expectation.label}",),
            drift_events=(),
        )

    _validate_complete_evidence(expectation, evidence, blockers)
    _validate_evidence_hash(evidence, blockers)

    if evidence.account_owner != expectation.expected_account_owner:
        drift_events.append(f"PR124_ACCOUNT_OWNER_DRIFT:{expectation.label}")
    if evidence.loader != expectation.expected_loader:
        drift_events.append(f"PR124_LOADER_DRIFT:{expectation.label}")
    if evidence.executable is not expectation.expected_executable:
        drift_events.append(f"PR124_EXECUTABLE_FLAG_DRIFT:{expectation.label}")
    if evidence.executable_hash != expectation.expected_code_hash:
        drift_events.append(f"PR124_EXECUTABLE_HASH_DRIFT:{expectation.label}")
    if (
        expectation.expected_programdata_address
        and evidence.programdata_address != expectation.expected_programdata_address
    ):
        drift_events.append(f"PR124_PROGRAMDATA_ADDRESS_DRIFT:{expectation.label}")
    if (
        evidence.observed_programdata_address
        and evidence.programdata_address != evidence.observed_programdata_address
    ):
        drift_events.append(f"PR124_OBSERVED_PROGRAMDATA_CHANGE:{expectation.label}")

    _validate_authority(expectation, evidence, blockers, drift_events)

    execution_allowed = not blockers and not drift_events
    degraded_discovery_allowed = explicit_degraded_discovery_mode and not execution_allowed
    return ProgramAttestation(
        label=expectation.label,
        program_id=expectation.program_id,
        execution_allowed=execution_allowed,
        degraded_discovery_allowed=degraded_discovery_allowed,
        operator_alert=bool(drift_events),
        blockers=tuple(dict.fromkeys(blockers)),
        drift_events=tuple(dict.fromkeys(drift_events)),
    )


def _validate_complete_evidence(
    expectation: ProgramExpectation,
    evidence: ProgramEvidence,
    blockers: list[str],
) -> None:
    prefix = expectation.label
    if evidence.account_owner is None:
        blockers.append(f"PR124_ACCOUNT_OWNER_MISSING:{prefix}")
    if evidence.executable is None:
        blockers.append(f"PR124_EXECUTABLE_FLAG_MISSING:{prefix}")
    if evidence.loader is None:
        blockers.append(f"PR124_LOADER_MISSING:{prefix}")
    if evidence.programdata_address is None:
        blockers.append(f"PR124_PROGRAMDATA_ADDRESS_MISSING:{prefix}")
    if evidence.deployed_slot is None:
        blockers.append(f"PR124_DEPLOYED_SLOT_MISSING:{prefix}")
    if evidence.attested_at_slot is None:
        blockers.append(f"PR124_ATTESTED_SLOT_MISSING:{prefix}")
    if evidence.attested_at_utc is None:
        blockers.append(f"PR124_ATTESTED_TIME_MISSING:{prefix}")
    if not _valid_sha256(evidence.executable_hash):
        blockers.append(f"PR124_EXECUTABLE_HASH_MISSING:{prefix}")
    if not _valid_sha256(expectation.expected_code_hash):
        blockers.append(f"PR124_EXPECTED_CODE_HASH_MISSING:{prefix}")
    if expectation.verified_source_pin is not None and not _valid_sha256(
        expectation.verified_source_pin.sha256
    ):
        blockers.append(f"PR124_VERIFIED_SOURCE_PIN_INVALID:{prefix}")


def _validate_evidence_hash(evidence: ProgramEvidence, blockers: list[str]) -> None:
    if not _valid_sha256(evidence.evidence_hash):
        blockers.append(f"PR124_EVIDENCE_HASH_INVALID:{evidence.program_id}")
        return
    expected = _canonical_evidence_hash(evidence)
    if evidence.evidence_hash != expected:
        blockers.append(f"PR124_EVIDENCE_HASH_MISMATCH:{evidence.program_id}")


def _canonical_evidence_hash(evidence: ProgramEvidence) -> str:
    payload = asdict(evidence)
    payload["evidence_hash"] = None
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_authority(
    expectation: ProgramExpectation,
    evidence: ProgramEvidence,
    blockers: list[str],
    drift_events: list[str],
) -> None:
    prefix = expectation.label
    if expectation.authority_policy is AuthorityPolicy.IMMUTABLE:
        if evidence.upgrade_authority is not None:
            drift_events.append(f"PR124_UPGRADE_AUTHORITY_DRIFT:{prefix}")
    elif expectation.authority_policy is AuthorityPolicy.FIXED:
        if expectation.expected_upgrade_authority is None:
            blockers.append(f"PR124_EXPECTED_UPGRADE_AUTHORITY_MISSING:{prefix}")
        elif evidence.upgrade_authority != expectation.expected_upgrade_authority:
            drift_events.append(f"PR124_UPGRADE_AUTHORITY_DRIFT:{prefix}")
    elif expectation.authority_policy is AuthorityPolicy.ALLOWLIST:
        if not expectation.allowed_upgrade_authorities:
            blockers.append(f"PR124_UPGRADE_AUTHORITY_ALLOWLIST_MISSING:{prefix}")
        elif evidence.upgrade_authority not in expectation.allowed_upgrade_authorities:
            drift_events.append(f"PR124_UPGRADE_AUTHORITY_DRIFT:{prefix}")


def make_program_evidence_hash(payload: Mapping[str, object]) -> str:
    """Return the canonical PR-124 evidence hash for operator attestations."""

    evidence = _parse_program_evidence((payload,))[0]
    return _canonical_evidence_hash(evidence)


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


def _string(
    payload: Mapping[str, object],
    field: str,
    *,
    default: str | None = None,
) -> str:
    value = payload.get(field, default)
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


def _optional_bool(payload: Mapping[str, object], field: str) -> bool | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise PR124AttestationError(f"FIELD_NOT_BOOL:{field}")
    return value


def _optional_positive_int(payload: Mapping[str, object], field: str) -> int | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PR124AttestationError(f"FIELD_NOT_POSITIVE_INT:{field}")
    return value


def _pubkey(payload: Mapping[str, object], field: str) -> str:
    return _pubkey_value(_string(payload, field), field)


def _optional_pubkey(payload: Mapping[str, object], field: str) -> str | None:
    value = _optional_string(payload, field)
    if value is None:
        return None
    return _pubkey_value(value, field)


def _pubkey_value(value: object, field: str) -> str:
    if not isinstance(value, str) or not _BASE58_RE.fullmatch(value):
        raise PR124AttestationError(f"FIELD_NOT_PUBKEY:{field}")
    return value


def _sha(payload: Mapping[str, object], field: str) -> str:
    value = _string(payload, field)
    if not _valid_sha256(value):
        raise PR124AttestationError(f"FIELD_NOT_SHA256:{field}")
    return value


def _optional_sha(payload: Mapping[str, object], field: str) -> str | None:
    value = _optional_string(payload, field)
    if value is None:
        return None
    if not _valid_sha256(value):
        raise PR124AttestationError(f"FIELD_NOT_SHA256:{field}")
    return value


def _optional_utc(payload: Mapping[str, object], field: str) -> str | None:
    value = _optional_string(payload, field)
    if value is None:
        return None
    if not _ISO8601_UTC_RE.fullmatch(value):
        raise PR124AttestationError(f"FIELD_NOT_UTC_SECOND:{field}")
    return value


def _valid_sha256(value: str | None) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value)) and value != (
        "0" * 64
    )


def _self_check_payload() -> tuple[dict[str, object], dict[str, object]]:
    program_id = "Prog111111111111111111111111111111111111111"
    registry = {
        "schema_version": PR124_SCHEMA_VERSION,
        "cluster": {
            "cluster": "mainnet-beta",
            "expected_genesis_hash": "Gen111111111111111111111111111111111111111",
            "observed_genesis_hash": "Gen111111111111111111111111111111111111111",
            "reviewed": True,
            "reviewer": "operator",
            "evidence_hash": "a" * 64,
            "source": "offline self-check fixture",
        },
        "programs": [
            {
                "label": "marginfi",
                "program_id": "Marg11111111111111111111111111111111111111",
                "admission": "discovery-only",
                "expected_account_owner": BPF_UPGRADEABLE_LOADER_ID,
                "expected_loader": BPF_UPGRADEABLE_LOADER_ID,
                "expected_executable": True,
                "expected_code_hash": "b" * 64,
                "authority_policy": "immutable",
                "expected_programdata_address": (
                    "Mrgn111111111111111111111111111111111111111"
                ),
                "required": True,
            },
            {
                "label": "jupiter-aggregator",
                "program_id": "Jup1111111111111111111111111111111111111111",
                "admission": "discovery-only",
                "expected_account_owner": BPF_UPGRADEABLE_LOADER_ID,
                "expected_loader": BPF_UPGRADEABLE_LOADER_ID,
                "expected_executable": True,
                "expected_code_hash": "b" * 64,
                "authority_policy": "immutable",
                "expected_programdata_address": (
                    "Jupd111111111111111111111111111111111111111"
                ),
                "required": True,
            },
            {
                "label": "token",
                "program_id": program_id,
                "admission": "active",
                "expected_account_owner": BPF_UPGRADEABLE_LOADER_ID,
                "expected_loader": BPF_UPGRADEABLE_LOADER_ID,
                "expected_executable": True,
                "expected_code_hash": "b" * 64,
                "authority_policy": "immutable",
                "expected_programdata_address": (
                    "Data111111111111111111111111111111111111111"
                ),
                "required": True,
            },
            {
                "label": "token-2022",
                "program_id": "T2211111111111111111111111111111111111111",
                "admission": "discovery-only",
                "expected_account_owner": BPF_UPGRADEABLE_LOADER_ID,
                "expected_loader": BPF_UPGRADEABLE_LOADER_ID,
                "expected_executable": True,
                "expected_code_hash": "b" * 64,
                "authority_policy": "immutable",
                "expected_programdata_address": (
                    "T22d111111111111111111111111111111111111111"
                ),
                "required": True,
            },
            {
                "label": "associated-token-account",
                "program_id": "ATA111111111111111111111111111111111111111",
                "admission": "discovery-only",
                "expected_account_owner": BPF_UPGRADEABLE_LOADER_ID,
                "expected_loader": BPF_UPGRADEABLE_LOADER_ID,
                "expected_executable": True,
                "expected_code_hash": "b" * 64,
                "authority_policy": "immutable",
                "expected_programdata_address": (
                    "ATAd111111111111111111111111111111111111111"
                ),
                "required": True,
            },
        ],
    }
    evidence_item = {
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
    }
    evidence_item["evidence_hash"] = make_program_evidence_hash(evidence_item)
    return registry, {"programs": [evidence_item]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the offline PR-124 deployment attestation self-check."
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
        print(f"PR-124 execution capability allowed: {result.execution_capability_allowed}")
        for blocker in result.blockers:
            print(f"BLOCKER: {blocker}")
        for drift in result.drift_events:
            print(f"DRIFT: {drift}")
    return 0 if result.execution_capability_allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AuthorityPolicy",
    "BPF_UPGRADEABLE_LOADER_ID",
    "ClusterIdentity",
    "PR124AttestationError",
    "PR124EvaluationResult",
    "PR124_RESULT_SCHEMA_VERSION",
    "PR124_SCHEMA_VERSION",
    "ProgramAdmission",
    "ProgramAttestation",
    "ProgramEvidence",
    "ProgramExpectation",
    "REQUIRED_PROGRAM_LABELS",
    "SourcePin",
    "evaluate_pr124_program_attestation",
    "main",
    "make_program_evidence_hash",
]
