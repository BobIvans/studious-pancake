"""Fork, blockhash and address-lookup-table coherence."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from src.config.chain_registry import (
    ADDRESS_LOOKUP_TABLE_PROGRAM_ADDRESS,
    validate_genesis_hash,
    validate_pubkey,
)

from .common import RootedTruthError, digest, integer, sha256, text
from .identity import DeployedIdentityRegistry


@dataclass(frozen=True, slots=True)
class ForkContext:
    cluster: str
    genesis_hash: str
    provider_id: str
    context_slot: int
    root_slot: int
    block_height: int
    commitment: str
    feature_set_sha256: str
    registry_generation: str
    observed_monotonic_ns: int
    observed_at_utc: str

    def __post_init__(self) -> None:
        text(self.cluster, "cluster")
        validate_genesis_hash(self.genesis_hash)
        text(self.provider_id, "provider_id")
        integer(self.context_slot, "context_slot")
        integer(self.root_slot, "root_slot")
        integer(self.block_height, "block_height")
        if self.root_slot > self.context_slot:
            raise RootedTruthError("root exceeds context")
        if self.commitment not in {"processed", "confirmed", "finalized"}:
            raise RootedTruthError("invalid commitment")
        if self.commitment == "finalized" and self.root_slot != self.context_slot:
            raise RootedTruthError("finalized context must be rooted")
        sha256(self.feature_set_sha256, "feature_set_sha256")
        sha256(self.registry_generation, "registry_generation")
        integer(self.observed_monotonic_ns, "observed_monotonic_ns")
        text(self.observed_at_utc, "observed_at_utc")

    @property
    def digest(self) -> str:
        return digest("fork-context", "mpr-sys-01.fork-context.v1", asdict(self))

    def assert_registry(self, registry: DeployedIdentityRegistry) -> None:
        actual = (self.cluster, self.genesis_hash, self.registry_generation)
        expected = (registry.cluster, registry.genesis_hash, registry.generation)
        if actual != expected:
            raise RootedTruthError(
                "fork context uses a mixed registry generation or another chain"
            )


@dataclass(frozen=True, slots=True)
class BlockhashLease:
    blockhash: str
    last_valid_block_height: int
    observed_block_height: int
    context_slot: int
    registry_generation: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        validate_genesis_hash(self.blockhash, field="blockhash")
        integer(self.last_valid_block_height, "last_valid_block_height")
        integer(self.observed_block_height, "observed_block_height")
        integer(self.context_slot, "context_slot")
        if self.observed_block_height > self.last_valid_block_height:
            raise RootedTruthError("blockhash was already expired when observed")
        sha256(self.registry_generation, "registry_generation")
        sha256(self.evidence_sha256, "evidence_sha256")

    @property
    def digest(self) -> str:
        return digest(
            "blockhash-lease",
            "mpr-sys-01.blockhash-lease.v1",
            asdict(self),
        )

    def assert_valid(
        self,
        *,
        current_block_height: int,
        registry_generation: str,
        rpc_reports_valid: bool,
    ) -> None:
        integer(current_block_height, "current_block_height")
        if registry_generation != self.registry_generation:
            raise RootedTruthError("blockhash belongs to another registry generation")
        if current_block_height > self.last_valid_block_height:
            raise RootedTruthError("blockhash expired by lastValidBlockHeight")
        if not rpc_reports_valid:
            raise RootedTruthError("trusted RPC reports blockhash invalid")


@dataclass(frozen=True, slots=True)
class AddressLookupTableState:
    table_address: str
    owner_program_id: str
    authority: str | None
    deactivation_slot: int | None
    last_extended_slot: int
    ordered_addresses: tuple[str, ...]
    account_sha256: str
    context_slot: int
    root_slot: int
    registry_generation: str

    def __post_init__(self) -> None:
        validate_pubkey(self.table_address, field="table_address")
        validate_pubkey(self.owner_program_id, field="owner_program_id")
        if self.owner_program_id != ADDRESS_LOOKUP_TABLE_PROGRAM_ADDRESS:
            raise RootedTruthError("ALT owner is not the canonical ALT program")
        if self.authority:
            validate_pubkey(self.authority, field="authority")
        if self.deactivation_slot is not None:
            integer(self.deactivation_slot, "deactivation_slot")
        integer(self.last_extended_slot, "last_extended_slot")
        integer(self.context_slot, "context_slot")
        integer(self.root_slot, "root_slot")
        if self.root_slot > self.context_slot:
            raise RootedTruthError("ALT root exceeds context")
        for address in self.ordered_addresses:
            validate_pubkey(address, field="ordered_address")
        if len(self.ordered_addresses) != len(set(self.ordered_addresses)):
            raise RootedTruthError("ALT contains duplicate addresses")
        sha256(self.account_sha256, "account_sha256")
        sha256(self.registry_generation, "registry_generation")

    @property
    def digest(self) -> str:
        return digest(
            "address-lookup-table",
            "mpr-sys-01.address-lookup-table.v1",
            asdict(self),
        )

    def assert_usable(
        self,
        *,
        current_root_slot: int,
        registry_generation: str,
    ) -> None:
        if registry_generation != self.registry_generation:
            raise RootedTruthError("ALT belongs to another registry generation")
        if (
            self.deactivation_slot is not None
            and current_root_slot >= self.deactivation_slot
        ):
            raise RootedTruthError("ALT is deactivated for the current root")
