"""Genesis-bound program and mint identity generations."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass

from src.config.chain_registry import (
    ChainRegistry,
    validate_genesis_hash,
    validate_pubkey,
)

from .common import RootedTruthError, digest, integer, sha256, text


def _validated_loader_id(value: str | None) -> str | None:
    """Return a real loader pubkey, never reinterpret a human-readable label."""

    if not value:
        return None
    try:
        return validate_pubkey(value, field="loader_id")
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class ProgramDeployment:
    program_id: str
    loader_id: str | None
    programdata_address: str | None
    deployment_slot: int
    upgrade_authority: str | None
    binary_sha256: str
    layout_sha256: str
    evidence_sha256: str
    rooted_slot: int
    state: str
    expires_at_slot: int | None = None

    def __post_init__(self) -> None:
        validate_pubkey(self.program_id, field="program_id")
        if self.loader_id:
            validate_pubkey(self.loader_id, field="loader_id")
        if self.programdata_address:
            validate_pubkey(self.programdata_address, field="programdata_address")
        if self.upgrade_authority:
            validate_pubkey(self.upgrade_authority, field="upgrade_authority")
        integer(self.deployment_slot, "deployment_slot")
        integer(self.rooted_slot, "rooted_slot")
        if self.rooted_slot < self.deployment_slot:
            raise RootedTruthError("root precedes deployment")
        for name in ("binary_sha256", "layout_sha256", "evidence_sha256"):
            sha256(getattr(self, name), name)
        if self.state not in {
            "pinned-static",
            "rooted-attested",
            "blocked-unverified",
            "revoked",
        }:
            raise RootedTruthError("invalid deployment state")
        if self.state == "rooted-attested" and not self.loader_id:
            raise RootedTruthError(
                "rooted-attested deployment requires a loader pubkey"
            )
        if self.expires_at_slot is not None:
            integer(self.expires_at_slot, "expires_at_slot", positive=True)

    @property
    def digest(self) -> str:
        return digest(
            "rooted-program-deployment",
            "mpr-sys-01.program-deployment.v1",
            asdict(self),
        )

    def assert_usable(self, current_root_slot: int) -> None:
        if self.state not in {"pinned-static", "rooted-attested"}:
            raise RootedTruthError("program deployment is not admitted")
        if (
            self.expires_at_slot is not None
            and current_root_slot > self.expires_at_slot
        ):
            raise RootedTruthError("program evidence expired")


@dataclass(frozen=True, slots=True)
class DeployedIdentityRegistry:
    cluster: str
    genesis_hash: str
    generation: str
    programs: tuple[ProgramDeployment, ...]
    canonical_mints: tuple[str, ...]
    external_blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        text(self.cluster, "cluster")
        validate_genesis_hash(self.genesis_hash)
        sha256(self.generation, "generation")
        if not self.programs:
            raise RootedTruthError("registry must contain programs")
        program_ids = [item.program_id for item in self.programs]
        if len(program_ids) != len(set(program_ids)):
            raise RootedTruthError("duplicate program IDs")
        for mint in self.canonical_mints:
            validate_pubkey(mint, field="canonical_mint")
        expected = self.compute_generation(
            self.cluster,
            self.genesis_hash,
            self.programs,
            self.canonical_mints,
            self.external_blockers,
        )
        if self.generation != expected:
            raise RootedTruthError("registry generation mismatch")

    @staticmethod
    def compute_generation(
        cluster: str,
        genesis_hash: str,
        programs: Sequence[ProgramDeployment],
        canonical_mints: Sequence[str],
        external_blockers: Sequence[str],
    ) -> str:
        return digest(
            "deployed-identity-registry",
            "mpr-sys-01.deployed-identity-registry.v1",
            {
                "cluster": cluster,
                "genesis_hash": genesis_hash,
                "programs": [asdict(item) for item in programs],
                "canonical_mints": list(canonical_mints),
                "external_blockers": list(external_blockers),
            },
        )

    @classmethod
    def from_chain_registry(
        cls,
        registry: ChainRegistry,
        *,
        cluster: str,
        genesis_hash: str,
        external_blockers: Sequence[str] = (),
    ) -> "DeployedIdentityRegistry":
        registry.validate_cluster(cluster, genesis_hash)
        programs: list[ProgramDeployment] = []
        mints: list[str] = []
        for entry in registry.entries:
            if cluster not in entry.clusters:
                continue
            if entry.kind == "mint":
                mints.append(entry.address)
                continue
            if entry.kind != "program":
                continue
            identity = digest(
                "pinned-static-program",
                "mpr-sys-01.pinned-static-program.v1",
                {
                    "id": entry.id,
                    "address": entry.address,
                    "owner": entry.owner,
                    "source": entry.source,
                    "cluster": cluster,
                    "genesis_hash": genesis_hash,
                },
            )
            programs.append(
                ProgramDeployment(
                    program_id=entry.address,
                    loader_id=_validated_loader_id(entry.owner),
                    programdata_address=None,
                    deployment_slot=0,
                    upgrade_authority=None,
                    binary_sha256=identity,
                    layout_sha256=identity,
                    evidence_sha256=identity,
                    rooted_slot=0,
                    state=(
                        "pinned-static"
                        if entry.immutable
                        else "blocked-unverified"
                    ),
                )
            )
        program_tuple = tuple(programs)
        mint_tuple = tuple(mints)
        blocker_tuple = tuple(external_blockers)
        generation = cls.compute_generation(
            cluster,
            genesis_hash,
            program_tuple,
            mint_tuple,
            blocker_tuple,
        )
        return cls(
            cluster=cluster,
            genesis_hash=genesis_hash,
            generation=generation,
            programs=program_tuple,
            canonical_mints=mint_tuple,
            external_blockers=blocker_tuple,
        )

    @property
    def digest(self) -> str:
        return self.generation

    def program(self, program_id: str) -> ProgramDeployment:
        for item in self.programs:
            if item.program_id == program_id:
                return item
        raise RootedTruthError(f"program is not registered: {program_id}")

    def assert_programs(
        self,
        program_ids: Iterable[str],
        *,
        current_root_slot: int,
    ) -> None:
        for program_id in program_ids:
            self.program(program_id).assert_usable(current_root_slot)
