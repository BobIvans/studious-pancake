"""PR-153 immutable external conformance and program-attestation evidence.

The runner collects read-only provider probe results and independently supplied
rooted on-chain program attestations. It seals review evidence but never mutates
or promotes the external contract registry.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import re
import time
from typing import Callable, Mapping, Protocol

from src.external_contracts.conformance import (
    ConformanceResult,
    Transport,
    run_read_only_conformance,
)
from src.external_contracts.models import ExternalContract
from src.external_contracts.registry import ExternalContractRegistry

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class ProbeRunner(Protocol):
    def __call__(
        self,
        contract: ExternalContract,
        *,
        enable_online: bool,
        environ: Mapping[str, str] | None,
        transport: Transport | None,
    ) -> ConformanceResult: ...


@dataclass(frozen=True, slots=True)
class ProgramAttestationEvidence:
    contract_id: str
    program_id: str
    cluster: str
    loader_owner: str
    executable: bool
    programdata_address: str
    upgrade_authority: str | None
    upgrade_authority_reviewed: bool
    deployed_binary_sha256: str
    reproduced_binary_sha256: str
    source_commit: str
    rooted_slot: int
    observed_at_ns: int
    expires_at_ns: int

    def __post_init__(self) -> None:
        for name in ("deployed_binary_sha256", "reproduced_binary_sha256"):
            if not _SHA256.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a lowercase sha256 digest")
        if not _GIT_SHA.fullmatch(self.source_commit):
            raise ValueError("source_commit must be a full lowercase git sha")
        if not all(
            (
                self.contract_id,
                self.program_id,
                self.cluster,
                self.loader_owner,
                self.programdata_address,
            )
        ):
            raise ValueError("program attestation identity fields are required")
        if min(self.rooted_slot, self.observed_at_ns, self.expires_at_ns) < 0:
            raise ValueError("slot and timestamps must be non-negative")
        if self.expires_at_ns <= self.observed_at_ns:
            raise ValueError("attestation expiry must follow observation")

    def blockers(self, *, now_ns: int) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.cluster != "mainnet-beta":
            blockers.append("PR153_PROGRAM_CLUSTER_MISMATCH")
        if not self.executable:
            blockers.append("PR153_PROGRAM_NOT_EXECUTABLE")
        if not self.upgrade_authority_reviewed:
            blockers.append("PR153_UPGRADE_AUTHORITY_UNREVIEWED")
        if self.deployed_binary_sha256 != self.reproduced_binary_sha256:
            blockers.append("PR153_REPRODUCED_BINARY_HASH_MISMATCH")
        if now_ns > self.expires_at_ns:
            blockers.append("PR153_PROGRAM_ATTESTATION_EXPIRED")
        return tuple(blockers)

    @property
    def evidence_hash(self) -> str:
        return _hash_json(asdict(self))


@dataclass(frozen=True, slots=True)
class ExternalEvidenceRecord:
    contract_id: str
    provider: str
    probe_state: str
    probe_verified: bool
    response_sha256: str | None
    request_method: str | None
    request_url: str | None
    assertions: tuple[str, ...]
    error_category: str | None

    @classmethod
    def from_result(
        cls, contract: ExternalContract, result: ConformanceResult
    ) -> "ExternalEvidenceRecord":
        error_category = None
        if result.error:
            error_category = result.error.split(":", 1)[0][:80]
        return cls(
            contract_id=contract.id,
            provider=contract.provider,
            probe_state=result.state,
            probe_verified=result.verified,
            response_sha256=result.response_sha256,
            request_method=result.request_method,
            request_url=result.request_url,
            assertions=result.assertions,
            error_category=error_category,
        )

    @property
    def evidence_hash(self) -> str:
        return _hash_json(asdict(self))


@dataclass(frozen=True, slots=True)
class ExternalConformanceBundle:
    schema_version: str
    generated_at: str
    registry_sha256: str
    probe_records: tuple[ExternalEvidenceRecord, ...]
    program_attestations: tuple[ProgramAttestationEvidence, ...]
    blockers: tuple[str, ...]
    registry_mutated: bool = False
    automatic_promotion_allowed: bool = False

    @property
    def review_ready(self) -> bool:
        return not self.blockers and bool(self.probe_records)

    @property
    def bundle_sha256(self) -> str:
        return _hash_json(
            {
                "schema_version": self.schema_version,
                "generated_at": self.generated_at,
                "registry_sha256": self.registry_sha256,
                "probe_records": [asdict(item) for item in self.probe_records],
                "program_attestations": [
                    asdict(item) for item in self.program_attestations
                ],
                "blockers": self.blockers,
                "registry_mutated": self.registry_mutated,
                "automatic_promotion_allowed": self.automatic_promotion_allowed,
            }
        )

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "registry_sha256": self.registry_sha256,
            "probe_records": [
                {**asdict(item), "evidence_hash": item.evidence_hash}
                for item in self.probe_records
            ],
            "program_attestations": [
                {**asdict(item), "evidence_hash": item.evidence_hash}
                for item in self.program_attestations
            ],
            "blockers": list(self.blockers),
            "review_ready": self.review_ready,
            "registry_mutated": self.registry_mutated,
            "automatic_promotion_allowed": self.automatic_promotion_allowed,
            "bundle_sha256": self.bundle_sha256,
        }


class ExternalConformanceEvidenceRunner:
    def __init__(
        self,
        registry: ExternalContractRegistry,
        *,
        probe_runner: ProbeRunner = run_read_only_conformance,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.registry = registry
        self.probe_runner = probe_runner
        self.clock_ns = clock_ns

    def run(
        self,
        *,
        contract_ids: tuple[str, ...],
        required_program_contract_ids: tuple[str, ...] = (),
        program_attestations: tuple[ProgramAttestationEvidence, ...] = (),
        enable_online: bool = False,
        environ: Mapping[str, str] | None = None,
        transport: Transport | None = None,
    ) -> ExternalConformanceBundle:
        now_ns = self.clock_ns()
        blockers: list[str] = []
        records: list[ExternalEvidenceRecord] = []
        if not contract_ids:
            blockers.append("PR153_NO_CONTRACTS_SELECTED")
        if len(set(contract_ids)) != len(contract_ids):
            blockers.append("PR153_DUPLICATE_CONTRACT_SELECTION")

        for contract_id in contract_ids:
            contract = self.registry.get(contract_id)
            result = self.probe_runner(
                contract,
                enable_online=enable_online,
                environ=environ,
                transport=transport,
            )
            record = ExternalEvidenceRecord.from_result(contract, result)
            records.append(record)
            if not result.verified:
                blockers.append(f"PR153_PROBE_NOT_VERIFIED:{contract_id}")
            if result.response_sha256 is not None and not _SHA256.fullmatch(
                result.response_sha256
            ):
                blockers.append(f"PR153_INVALID_RESPONSE_HASH:{contract_id}")

        observed_ids: set[str] = set()
        for attestation in program_attestations:
            if attestation.contract_id in observed_ids:
                blockers.append(
                    f"PR153_DUPLICATE_PROGRAM_ATTESTATION:{attestation.contract_id}"
                )
            observed_ids.add(attestation.contract_id)
            blockers.extend(
                f"{blocker}:{attestation.contract_id}"
                for blocker in attestation.blockers(now_ns=now_ns)
            )
            self._validate_registry_identity(attestation, blockers)

        for contract_id in required_program_contract_ids:
            if contract_id not in observed_ids:
                blockers.append(f"PR153_PROGRAM_ATTESTATION_MISSING:{contract_id}")

        registry_sha256 = _hash_json(self.registry.status_payload())
        generated_at = datetime.fromtimestamp(now_ns / 1_000_000_000, UTC).isoformat()
        return ExternalConformanceBundle(
            schema_version="pr153.external-conformance-evidence.v1",
            generated_at=generated_at,
            registry_sha256=registry_sha256,
            probe_records=tuple(records),
            program_attestations=program_attestations,
            blockers=tuple(sorted(set(blockers))),
        )

    def _validate_registry_identity(
        self,
        attestation: ProgramAttestationEvidence,
        blockers: list[str],
    ) -> None:
        contract = self.registry.get(attestation.contract_id)
        if contract.deployment_program_id != attestation.program_id:
            blockers.append(
                f"PR153_PROGRAM_ID_MISMATCH:{attestation.contract_id}"
            )
        if contract.cluster != attestation.cluster:
            blockers.append(
                f"PR153_REGISTRY_CLUSTER_MISMATCH:{attestation.contract_id}"
            )


def _hash_json(value: object) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
