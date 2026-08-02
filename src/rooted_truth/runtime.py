"""Aggregate rooted runtime truth and candidate binding."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from src.config.chain_registry import ChainRegistry

from .admission import (
    AdmissionDecision,
    AssetVenueAdmission,
    LSTSnapshot,
    MintSnapshot,
    OracleSnapshot,
    PoolSnapshot,
    RuntimeTruthPolicy,
    build_admission,
    evaluate_mint,
    evaluate_pool,
)
from .common import (
    AdmissionState,
    ROOTED_TRUTH_EVIDENCE_SCHEMA_ID,
    ROOTED_TRUTH_POLICY_SCHEMA_ID,
    ROOTED_TRUTH_SCHEMA_ID,
    RootedTruthError,
    digest,
    sha256,
    text,
)
from .context import AddressLookupTableState, BlockhashLease, ForkContext
from .identity import DeployedIdentityRegistry, ProgramDeployment


@dataclass(frozen=True, slots=True)
class CandidateTruthBinding:
    candidate_id: str
    message_sha256: str
    registry_generation: str
    fork_context_sha256: str
    blockhash_lease_sha256: str
    alt_sha256s: tuple[str, ...]
    admission_generation: str
    rooted_truth_sha256: str


@dataclass(frozen=True, slots=True)
class RootedRuntimeTruth:
    registry: DeployedIdentityRegistry
    fork: ForkContext
    blockhash: BlockhashLease
    alts: tuple[AddressLookupTableState, ...]
    admission: AssetVenueAdmission

    def __post_init__(self) -> None:
        self.fork.assert_registry(self.registry)
        if self.blockhash.registry_generation != self.registry.generation:
            raise RootedTruthError("blockhash uses a mixed registry generation")
        if self.admission.mint.registry_generation != self.registry.generation:
            raise RootedTruthError("mint uses a mixed registry generation")
        if self.admission.pool.registry_generation != self.registry.generation:
            raise RootedTruthError("pool uses a mixed registry generation")
        if any(
            item.registry_generation != self.registry.generation for item in self.alts
        ):
            raise RootedTruthError("ALT uses a mixed registry generation")

    @property
    def digest(self) -> str:
        return digest(
            "rooted-runtime-truth",
            ROOTED_TRUTH_SCHEMA_ID,
            {
                "registry_generation": self.registry.generation,
                "fork_context": self.fork.digest,
                "blockhash_lease": self.blockhash.digest,
                "alts": [item.digest for item in self.alts],
                "admission_generation": self.admission.generation,
            },
        )

    def bind_candidate(
        self,
        *,
        candidate_id: str,
        message_sha256: str,
        required_program_ids: Sequence[str],
        expected_alt_digests: Sequence[str],
        current_root_slot: int,
        current_block_height: int,
        rpc_reports_blockhash_valid: bool,
    ) -> CandidateTruthBinding:
        text(candidate_id, "candidate_id")
        sha256(message_sha256, "message_sha256")
        if current_root_slot < self.fork.root_slot:
            raise RootedTruthError("current root regressed behind fork context")
        self.registry.assert_programs(
            required_program_ids,
            current_root_slot=current_root_slot,
        )
        self.blockhash.assert_valid(
            current_block_height=current_block_height,
            registry_generation=self.registry.generation,
            rpc_reports_valid=rpc_reports_blockhash_valid,
        )
        actual_alt_digests = tuple(item.digest for item in self.alts)
        if tuple(expected_alt_digests) != actual_alt_digests:
            raise RootedTruthError("compiled message ALT set/order changed")
        for item in self.alts:
            item.assert_usable(
                current_root_slot=current_root_slot,
                registry_generation=self.registry.generation,
            )
        self.admission.assert_admitted(current_root_slot=current_root_slot)
        return CandidateTruthBinding(
            candidate_id=candidate_id,
            message_sha256=message_sha256,
            registry_generation=self.registry.generation,
            fork_context_sha256=self.fork.digest,
            blockhash_lease_sha256=self.blockhash.digest,
            alt_sha256s=actual_alt_digests,
            admission_generation=self.admission.generation,
            rooted_truth_sha256=self.digest,
        )


def canonical_static_programs() -> tuple[str, ...]:
    return tuple(
        entry.address
        for entry in ChainRegistry.load_default().entries
        if entry.kind == "program"
    )


__all__ = [
    "AdmissionDecision",
    "AdmissionState",
    "AddressLookupTableState",
    "AssetVenueAdmission",
    "BlockhashLease",
    "CandidateTruthBinding",
    "DeployedIdentityRegistry",
    "ForkContext",
    "LSTSnapshot",
    "MintSnapshot",
    "OracleSnapshot",
    "PoolSnapshot",
    "ProgramDeployment",
    "ROOTED_TRUTH_EVIDENCE_SCHEMA_ID",
    "ROOTED_TRUTH_POLICY_SCHEMA_ID",
    "ROOTED_TRUTH_SCHEMA_ID",
    "RootedRuntimeTruth",
    "RootedTruthError",
    "RuntimeTruthPolicy",
    "build_admission",
    "canonical_static_programs",
    "evaluate_mint",
    "evaluate_pool",
]
