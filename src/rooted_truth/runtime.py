"""Genesis-bound, rooted and revocable runtime truth for sender-free execution.

This module is deliberately dependency-light and does not perform RPC, signing or
submission. It validates already materialized observations and produces immutable
bindings that active runtime consumers can persist with candidates and messages.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from importlib import resources
import json
import re
from typing import Iterable, Sequence

from src.config.chain_registry import (
    ADDRESS_LOOKUP_TABLE_PROGRAM_ADDRESS,
    ASSOCIATED_TOKEN_PROGRAM_ADDRESS,
    COMPUTE_BUDGET_PROGRAM_ADDRESS,
    SYSTEM_PROGRAM_ADDRESS,
    TOKEN_2022_PROGRAM_ADDRESS,
    TOKEN_PROGRAM_ADDRESS,
    ChainRegistry,
    validate_genesis_hash,
    validate_pubkey,
)
from src.kernel import canonical_json_bytes, domain_sha256

ROOTED_TRUTH_SCHEMA_ID = "mpr-sys-01.rooted-runtime-truth.v1"
ROOTED_TRUTH_EVIDENCE_SCHEMA_ID = "mpr-sys-01.rooted-runtime-truth-evidence.v1"
ROOTED_TRUTH_POLICY_SCHEMA_ID = "mpr-sys-01.rooted-runtime-policy.v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_COMMITMENTS = frozenset({"processed", "confirmed", "finalized"})
_ALLOWED_DEPLOYMENT_STATES = frozenset(
    {"pinned-static", "rooted-attested", "blocked-unverified", "revoked"}
)


class RootedTruthError(ValueError):
    """Raised when materialized chain truth is inconsistent or unsafe."""


class AdmissionState(StrEnum):
    ADMITTED = "admitted"
    BLOCKED = "blocked"
    REVOKED = "revoked"


def _sha256(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise RootedTruthError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _non_empty(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise RootedTruthError(f"{field} must be a non-empty normalized string")
    return value


def _non_negative(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RootedTruthError(f"{field} must be a non-negative integer")
    return value


def _positive(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RootedTruthError(f"{field} must be a positive integer")
    return value


def _canonical_digest(domain: str, schema_id: str, payload: object) -> str:
    return domain_sha256(
        domain=domain,
        schema_id=schema_id,
        payload=canonical_json_bytes(payload),
    )


@dataclass(frozen=True, slots=True)
class ProgramDeployment:
    """One immutable or rooted-attested program deployment identity."""

    program_id: str
    loader_id: str
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
        validate_pubkey(self.loader_id, field="loader_id")
        if self.programdata_address is not None:
            validate_pubkey(self.programdata_address, field="programdata_address")
        if self.upgrade_authority is not None:
            validate_pubkey(self.upgrade_authority, field="upgrade_authority")
        _non_negative(self.deployment_slot, "deployment_slot")
        _non_negative(self.rooted_slot, "rooted_slot")
        if self.rooted_slot < self.deployment_slot:
            raise RootedTruthError("rooted_slot cannot precede deployment_slot")
        _sha256(self.binary_sha256, "binary_sha256")
        _sha256(self.layout_sha256, "layout_sha256")
        _sha256(self.evidence_sha256, "evidence_sha256")
        if self.state not in _ALLOWED_DEPLOYMENT_STATES:
            raise RootedTruthError(f"unsupported deployment state: {self.state}")
        if self.expires_at_slot is not None:
            _positive(self.expires_at_slot, "expires_at_slot")
            if self.expires_at_slot < self.rooted_slot:
                raise RootedTruthError("deployment evidence expires before rooted observation")

    @property
    def digest(self) -> str:
        return _canonical_digest(
            "rooted-program-deployment",
            "mpr-sys-01.program-deployment.v1",
            asdict(self),
        )

    def assert_usable(self, *, current_root_slot: int) -> None:
        _non_negative(current_root_slot, "current_root_slot")
        if self.state not in {"pinned-static", "rooted-attested"}:
            raise RootedTruthError(
                f"program {self.program_id} is not admitted: {self.state}"
            )
        if self.expires_at_slot is not None and current_root_slot > self.expires_at_slot:
            raise RootedTruthError(f"program evidence expired: {self.program_id}")


@dataclass(frozen=True, slots=True)
class DeployedIdentityRegistry:
    """One genesis-bound immutable generation for program and mint identities."""

    cluster: str
    genesis_hash: str
    generation: str
    programs: tuple[ProgramDeployment, ...]
    canonical_mints: tuple[str, ...]
    external_blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _non_empty(self.cluster, "cluster")
        validate_genesis_hash(self.genesis_hash)
        _sha256(self.generation, "generation")
        if not self.programs:
            raise RootedTruthError("identity registry must contain programs")
        program_ids = [item.program_id for item in self.programs]
        if len(program_ids) != len(set(program_ids)):
            raise RootedTruthError("identity registry contains duplicate program IDs")
        for mint in self.canonical_mints:
            validate_pubkey(mint, field="canonical_mints[]")
        if len(self.canonical_mints) != len(set(self.canonical_mints)):
            raise RootedTruthError("identity registry contains duplicate canonical mints")
        for blocker in self.external_blockers:
            _non_empty(blocker, "external_blockers[]")
        expected = self.compute_generation(
            cluster=self.cluster,
            genesis_hash=self.genesis_hash,
            programs=self.programs,
            canonical_mints=self.canonical_mints,
            external_blockers=self.external_blockers,
        )
        if self.generation != expected:
            raise RootedTruthError("identity registry generation does not match contents")

    @classmethod
    def from_chain_registry(
        cls,
        chain_registry: ChainRegistry,
        *,
        cluster: str,
        genesis_hash: str,
        external_blockers: Sequence[str] = (),
    ) -> "DeployedIdentityRegistry":
        chain_registry.validate_cluster(cluster, genesis_hash)
        programs: list[ProgramDeployment] = []
        canonical_mints: list[str] = []
        for entry in chain_registry.entries:
            if cluster not in entry.clusters:
                continue
            if entry.kind == "mint":
                canonical_mints.append(entry.address)
                continue
            if entry.kind != "program":
                continue
            identity_payload = {
                "entry_id": entry.id,
                "address": entry.address,
                "owner": entry.owner,
                "source": entry.source,
                "cluster": cluster,
                "genesis_hash": genesis_hash,
            }
            identity_digest = _canonical_digest(
                "pinned-static-program",
                "mpr-sys-01.pinned-static-program.v1",
                identity_payload,
            )
            programs.append(
                ProgramDeployment(
                    program_id=entry.address,
                    loader_id=entry.owner or SYSTEM_PROGRAM_ADDRESS,
                    programdata_address=None,
                    deployment_slot=0,
                    upgrade_authority=None,
                    binary_sha256=identity_digest,
                    layout_sha256=identity_digest,
                    evidence_sha256=identity_digest,
                    rooted_slot=0,
                    state="pinned-static" if entry.immutable else "blocked-unverified",
                )
            )
        generation = cls.compute_generation(
            cluster=cluster,
            genesis_hash=genesis_hash,
            programs=tuple(programs),
            canonical_mints=tuple(canonical_mints),
            external_blockers=tuple(external_blockers),
        )
        return cls(
            cluster=cluster,
            genesis_hash=genesis_hash,
            generation=generation,
            programs=tuple(programs),
            canonical_mints=tuple(canonical_mints),
            external_blockers=tuple(external_blockers),
        )

    @staticmethod
    def compute_generation(
        *,
        cluster: str,
        genesis_hash: str,
        programs: Sequence[ProgramDeployment],
        canonical_mints: Sequence[str],
        external_blockers: Sequence[str],
    ) -> str:
        return _canonical_digest(
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

    @property
    def digest(self) -> str:
        return self.generation

    def program(self, program_id: str) -> ProgramDeployment:
        validate_pubkey(program_id, field="program_id")
        for item in self.programs:
            if item.program_id == program_id:
                return item
        raise RootedTruthError(f"program is not present in registry: {program_id}")

    def assert_programs(
        self,
        program_ids: Iterable[str],
        *,
        current_root_slot: int,
    ) -> None:
        for program_id in program_ids:
            self.program(program_id).assert_usable(current_root_slot=current_root_slot)


@dataclass(frozen=True, slots=True)
class ForkContext:
    """Exact chain/fork context shared by planning, simulation and settlement."""

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
        _non_empty(self.cluster, "cluster")
        validate_genesis_hash(self.genesis_hash)
        _non_empty(self.provider_id, "provider_id")
        _non_negative(self.context_slot, "context_slot")
        _non_negative(self.root_slot, "root_slot")
        _non_negative(self.block_height, "block_height")
        if self.root_slot > self.context_slot:
            raise RootedTruthError("root_slot cannot exceed context_slot")
        if self.commitment not in _ALLOWED_COMMITMENTS:
            raise RootedTruthError(f"unsupported commitment: {self.commitment}")
        if self.commitment == "finalized" and self.context_slot != self.root_slot:
            raise RootedTruthError("finalized context must be rooted")
        _sha256(self.feature_set_sha256, "feature_set_sha256")
        _sha256(self.registry_generation, "registry_generation")
        _non_negative(self.observed_monotonic_ns, "observed_monotonic_ns")
        _non_empty(self.observed_at_utc, "observed_at_utc")

    @property
    def digest(self) -> str:
        return _canonical_digest(
            "fork-context", "mpr-sys-01.fork-context.v1", asdict(self)
        )

    def assert_registry(self, registry: DeployedIdentityRegistry) -> None:
        if self.cluster != registry.cluster or self.genesis_hash != registry.genesis_hash:
            raise RootedTruthError("fork context belongs to another chain")
        if self.registry_generation != registry.generation:
            raise RootedTruthError("fork context uses a mixed registry generation")


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
        _non_negative(self.last_valid_block_height, "last_valid_block_height")
        _non_negative(self.observed_block_height, "observed_block_height")
        _non_negative(self.context_slot, "context_slot")
        if self.observed_block_height > self.last_valid_block_height:
            raise RootedTruthError("blockhash was already expired when observed")
        _sha256(self.registry_generation, "registry_generation")
        _sha256(self.evidence_sha256, "evidence_sha256")

    @property
    def digest(self) -> str:
        return _canonical_digest(
            "blockhash-lease", "mpr-sys-01.blockhash-lease.v1", asdict(self)
        )

    def assert_valid(
        self,
        *,
        current_block_height: int,
        registry_generation: str,
        rpc_reports_valid: bool,
    ) -> None:
        _non_negative(current_block_height, "current_block_height")
        if self.registry_generation != registry_generation:
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
        if self.authority is not None:
            validate_pubkey(self.authority, field="authority")
        if self.deactivation_slot is not None:
            _non_negative(self.deactivation_slot, "deactivation_slot")
        _non_negative(self.last_extended_slot, "last_extended_slot")
        _non_negative(self.context_slot, "context_slot")
        _non_negative(self.root_slot, "root_slot")
        if self.root_slot > self.context_slot:
            raise RootedTruthError("ALT root cannot exceed context slot")
        for address in self.ordered_addresses:
            validate_pubkey(address, field="ordered_addresses[]")
        if len(self.ordered_addresses) != len(set(self.ordered_addresses)):
            raise RootedTruthError("ALT contains duplicate addresses")
        _sha256(self.account_sha256, "account_sha256")
        _sha256(self.registry_generation, "registry_generation")

    @property
    def ordered_addresses_sha256(self) -> str:
        return _canonical_digest(
            "alt-address-order",
            "mpr-sys-01.alt-address-order.v1",
            list(self.ordered_addresses),
        )

    @property
    def digest(self) -> str:
        return _canonical_digest(
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
        if self.registry_generation != registry_generation:
            raise RootedTruthError("ALT belongs to another registry generation")
        if self.deactivation_slot is not None and current_root_slot >= self.deactivation_slot:
            raise RootedTruthError("ALT is deactivated for the current root")


@dataclass(frozen=True, slots=True)
class MintSnapshot:
    mint: str
    token_program_id: str
    decimals: int
    mint_authority: str | None
    freeze_authority: str | None
    permanent_delegate: str | None
    transfer_hook_program: str | None
    extensions: tuple[str, ...]
    transfer_fee_bps: int
    witheld_amount: int
    account_length: int
    rent_lamports: int
    context_slot: int
    root_slot: int
    registry_generation: str
    evidence_sha256: str
    expires_at_slot: int

    def __post_init__(self) -> None:
        validate_pubkey(self.mint, field="mint")
        validate_pubkey(self.token_program_id, field="token_program_id")
        if self.token_program_id not in {TOKEN_PROGRAM_ADDRESS, TOKEN_2022_PROGRAM_ADDRESS}:
            raise RootedTruthError("mint owner is not a canonical token program")
        _non_negative(self.decimals, "decimals")
        if self.decimals > 255:
            raise RootedTruthError("mint decimals exceed u8")
        for field_name in (
            "mint_authority",
            "freeze_authority",
            "permanent_delegate",
            "transfer_hook_program",
        ):
            value = getattr(self, field_name)
            if value is not None:
                validate_pubkey(value, field=field_name)
        for extension in self.extensions:
            _non_empty(extension, "extensions[]")
        if len(self.extensions) != len(set(self.extensions)):
            raise RootedTruthError("duplicate Token-2022 extensions")
        _non_negative(self.transfer_fee_bps, "transfer_fee_bps")
        if self.transfer_fee_bps > 10_000:
            raise RootedTruthError("transfer fee bps exceeds 10000")
        _non_negative(self.witheld_amount, "witheld_amount")
        _positive(self.account_length, "account_length")
        _non_negative(self.rent_lamports, "rent_lamports")
        _non_negative(self.context_slot, "context_slot")
        _non_negative(self.root_slot, "root_slot")
        if self.root_slot > self.context_slot:
            raise RootedTruthError("mint root cannot exceed context slot")
        _sha256(self.registry_generation, "registry_generation")
        _sha256(self.evidence_sha256, "evidence_sha256")
        _positive(self.expires_at_slot, "expires_at_slot")

    @property
    def digest(self) -> str:
        return _canonical_digest(
            "mint-snapshot", "mpr-sys-01.mint-snapshot.v1", asdict(self)
        )


@dataclass(frozen=True, slots=True)
class OracleSnapshot:
    oracle_id: str
    price_atomic: int
    confidence_bps: int
    divergence_bps: int
    observed_slot: int
    root_slot: int
    source_ids: tuple[str, ...]
    evidence_sha256: str

    def __post_init__(self) -> None:
        _non_empty(self.oracle_id, "oracle_id")
        _non_negative(self.price_atomic, "price_atomic")
        _non_negative(self.confidence_bps, "confidence_bps")
        _non_negative(self.divergence_bps, "divergence_bps")
        _non_negative(self.observed_slot, "observed_slot")
        _non_negative(self.root_slot, "root_slot")
        if self.root_slot > self.observed_slot:
            raise RootedTruthError("oracle root cannot exceed observation slot")
        if not self.source_ids:
            raise RootedTruthError("oracle requires at least one source")
        for source in self.source_ids:
            _non_empty(source, "source_ids[]")
        _sha256(self.evidence_sha256, "evidence_sha256")


@dataclass(frozen=True, slots=True)
class PoolSnapshot:
    pool_id: str
    program_id: str
    vault_owners: tuple[str, ...]
    fee_bps: int
    oracle_id: str
    context_slot: int
    root_slot: int
    registry_generation: str
    evidence_sha256: str
    expires_at_slot: int

    def __post_init__(self) -> None:
        _non_empty(self.pool_id, "pool_id")
        validate_pubkey(self.program_id, field="program_id")
        if not self.vault_owners:
            raise RootedTruthError("pool must declare vault owners")
        for owner in self.vault_owners:
            validate_pubkey(owner, field="vault_owners[]")
        _non_negative(self.fee_bps, "fee_bps")
        if self.fee_bps > 10_000:
            raise RootedTruthError("pool fee bps exceeds 10000")
        _non_empty(self.oracle_id, "oracle_id")
        _non_negative(self.context_slot, "context_slot")
        _non_negative(self.root_slot, "root_slot")
        if self.root_slot > self.context_slot:
            raise RootedTruthError("pool root cannot exceed context slot")
        _sha256(self.registry_generation, "registry_generation")
        _sha256(self.evidence_sha256, "evidence_sha256")
        _positive(self.expires_at_slot, "expires_at_slot")

    @property
    def digest(self) -> str:
        return _canonical_digest(
            "pool-snapshot", "mpr-sys-01.pool-snapshot.v1", asdict(self)
        )


@dataclass(frozen=True, slots=True)
class LSTSnapshot:
    mint: str
    redeemable: bool
    withdrawal_delay_slots: int
    validator_concentration_bps: int
    protocol_paused: bool
    redemption_liquidity_atomic: int
    evidence_sha256: str
    expires_at_slot: int

    def __post_init__(self) -> None:
        validate_pubkey(self.mint, field="lst.mint")
        _non_negative(self.withdrawal_delay_slots, "withdrawal_delay_slots")
        _non_negative(self.validator_concentration_bps, "validator_concentration_bps")
        if self.validator_concentration_bps > 10_000:
            raise RootedTruthError("validator concentration exceeds 10000 bps")
        _non_negative(self.redemption_liquidity_atomic, "redemption_liquidity_atomic")
        _sha256(self.evidence_sha256, "evidence_sha256")
        _positive(self.expires_at_slot, "expires_at_slot")


@dataclass(frozen=True, slots=True)
class RuntimeTruthPolicy:
    allow_token_2022: bool
    supported_token_2022_extensions: frozenset[str]
    maximum_transfer_fee_bps: int
    allowed_transfer_hook_programs: frozenset[str]
    maximum_oracle_confidence_bps: int
    maximum_oracle_divergence_bps: int
    maximum_oracle_staleness_slots: int
    maximum_lst_withdrawal_delay_slots: int
    maximum_validator_concentration_bps: int
    minimum_redemption_liquidity_atomic: int
    external_required_programs: tuple[str, ...]

    def __post_init__(self) -> None:
        for value in self.supported_token_2022_extensions:
            _non_empty(value, "supported_token_2022_extensions[]")
        for value in self.allowed_transfer_hook_programs:
            validate_pubkey(value, field="allowed_transfer_hook_programs[]")
        for value, field_name in (
            (self.maximum_transfer_fee_bps, "maximum_transfer_fee_bps"),
            (self.maximum_oracle_confidence_bps, "maximum_oracle_confidence_bps"),
            (self.maximum_oracle_divergence_bps: "maximum_oracle_divergence_bps"),
            (self.maximum_oracle_staleness_slots, "maximum_oracle_staleness_slots"),
            (self.maximum_lst_withdrawal_delay_slots, "maximum_lst_withdrawal_delay_slots"),
            (self.maximum_validator_concentration_bps, "maximum_validator_concentration_bps"),
        ):
            _non_negative(value, field_name)
            if value > 10_000:
                raise RootedTruthError(f" {field_name} exceeds 10000 bps")
        _non_negative(self.minimum_redemption_liquidity_atomic, "minimum_redemption_liquidity_atomic")
        for program in self.external_required_programs:
            _non_empty(program, "external_required_programs[]")

    @classmethod
    def load_default(cls) -> "RuntimeTruthPolicy":
        resource = resources.files("src.resources").joinpath("rooted_runtime_truth_policy.json")
        payload = json.loads(resource.read_text(encoding="utf-8"))
        if payload.get("schema_id") != ROOTED_TRUTH_POLICY_SCHEMA_ID:
            raise RootedTruthError("unexpected rooted runtime policy schema")
        return cls.from_mapping(payload)

    @classmethod
    def from_mapping(cls, payload: dict[str, object]) -> "RuntimeTruthPolicy":
        expected = {
            "schema_id",
            "allow_token_2022",
            "supported_token_2022_extensions",
            "maximum_transfer_fee_bps",
            "allowed_transfer_hook_programs",
            "maximum_oracle_confidence_bps",
            "maximum_oracle_divergence_bps",
            "maximum_oracle_staleness_slots",
            "maximum_lst_withdrawal_delay_slots",
            "maximum_validator_concentration_bps",
            "minimum_redemption_liquidity_atomic",
            "external_required_programs",
        }
        unknown = set(payload) - expected
        missing = expected - set(payload)
        if unknown:
            raise RootedTruthError(f"unknown rooted runtime policy fields: {sorted(unknown)}")
        if missing:
            raise RootedTruthError(f"missing rooted runtime policy fields: {sorted(missing)}")
        return cls(
            allow_token_2022=bool(payload["allow_token_2022"]),
            supported_token_2022_extensions=frozenset(str(value) for value in payload["supported_token_2022_extensions"]),
            maximum_transfer_fee_bps=int(payload["maximum_transfer_fee_bps"]),
            allowed_transfer_hook_programs=frozenset(str(value) for value in payload["allowed_transfer_hook_programs"]),
            maximum_oracle_confidence_bps=int(payload["maximum_oracle_confidence_bps"]),
            maximum_oracle_divergence_bps=int(payload["maximum_oracle_divergence_bps"]),
            maximum_oracle_staleness_slots=int(payload["maximum_oracle_staleness_slots"]),
            maximum_lst_withdrawal_delay_slots=int(payload["maximum_lst_withdrawal_delay_slots"]),
            maximum_validator_concentration_bps=int(payload["maximum_validator_concentration_bps"]),
            minimum_redemption_liquidity_atomic=int(payload["minimum_redemption_liquidity_atomic"]),
            external_required_programs=tuple(str(value) for value in payload["external_required_programs"]),
        )


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    state: AdmissionState
    reasons: tuple[str, ...]
    digest: str

    @property
    def admitted(self) -> bool:
        return self.state == AdmissionState.ADMITTED


@dataclass(frozen=True, slots=True)
class AssetVenueAdmission:
    mint: MintSnapshot
    oracle: OracleSnapshot
    pool: PoolSnapshot
    mint_decision: AdmissionDecision
    pool_decision: AdmissionDecision
    generation: str
    expires_at_slot: int
    lst: LSTSnapshot | None = None

    def __post_init__(self) -> None:
        _sha256(self.generation, "generation")
        _positive(self.expires_at_slot, "expires_at_slot")
        expected = self.compute_generation(
            mint=self.mint,
            oracle=self.oracle,
            pool=self.pool,
            mint_decision=self.mint_decision,
            pool_decision=self.pool_decision,
            expires_at_slot=self.expires_at_slot,
            lst=self.lst,
        )
        if self.generation != expected:
            raise RootedTruthError("admission generation does not match contents")

    @staticmethod
    def compute_generation(
        *,
        mint: MintSnapshot,
        oracle: OracleSnapshot,
        pool: PoolSnapshot,
        mint_decision: AdmissionDecision,
        pool_decision: AdmissionDecision,
        expires_at_slot: int,
        lst: LSTSnapshot | None,
    ) -> str:
        return _canonical_digest(
            "asset-venue-admission",
            "mpr-sys-01.asset-venue-admission.v1",
            {
                "mint": asdict(mint),
                "oracle": asdict(oracle),
                "pool": asdict(pool),
                "mint_decision": asdict(mint_decision),
                "pool_decision": asdict(pool_decision),
                "expires_at_slot": expires_at_slot,
                "lst": None if lst is None else asdict(lst),
            },
        )

    @property
    def admitted(self) -> bool:
        return self.mint_decision.admitted and self.pool_decision.admitted

    def assert_admitted(self, *, current_root_slot: int) -> None:
        if current_root_slot > self.expires_at_slot:
            raise RootedTruthError("admission evidence expired")
        if not self.admitted:
            reasons = self.mint_decision.reasons + self.pool_decision.reasons
            raise RootedTruthError("admission is blocked: " + ",".join(reasons))


def evaluate_mint(
    snapshot: MintSnapshot,
     ,
    policy: RuntimeTruthPolicy,
    current_root_slot: int,
    expected_registry_generation: str,
    lst: LSTSnapshot | None = None,
) -> AdmissionDecision:
    reasons: list[str] = []
    if snapshot.registry_generation != expected_registry_generation:
        reasons.append("MIXED_REGISTRY_GENERATION")
    if current_root_slot > snapshot.expires_at_slot:
        reasons.append("MINT_EVIDENCE_EXPIRED")
    if snapshot.mint_authority is not None:
        reasons.append("MINT_AUTHORITY_PRESENT")
    if snapshot.freeze_authority is not None:
        reasons.append("FREEZE_AUTHORITY_PRESENT")
    if snapshot.permanent_delegate is not None:
        reasons.append("PERMANENT_DELEGATE_PRESENT")
    if snapshot.witheld_amount != 0:
        reasons.append("WITHHELD_FEE_PRESENT")
    if snapshot.transfer_fee_bps > policy.maximum_transfer_fee_bps:
        reasons.append("TRANSFER_FEE_EXCEEDS_POLICY")
    if snapshot.token_program_id == TOKEN_2022_PROGRAM_ADDRESS:
        if not policy.allow_token_2022:
            reasons.append("TOKEN_2022_DEFAULT_DENY")
        unsupported = set(snapshot.extensions) - set(policy.supported_token_2022_extensions)
        if unsupported:
            reasons.append("UNSUPPORTED_TOKEN_2022_EXTENSIONS:" + ",".join(sorted(unsupported)))
        if snapshot.transfer_hook_program is not None and snapshot.transfer_hook_program not in policy.allowed_transfer_hook_programs:
            reasons.append("TRANSFER_HOOK_NOT_ALLOWLISTED")
    if lst is not None:
        if lst.mint != snapshot.mintè(€€€€€€€€€€€É•…Í½¹Ì¹…ÁÁ•¹ ‰1MQ}5%9Q}5%M5Q ˆ¤(€€€€€€€¥˜ÕÉÉ•¹Ñ}É½½Ñ}Í±½Ð€ø±ÍÐ¹•áÁ¥É•Í}…Ñ}Í±½Ðè(€€€€€€€€€€€É•…Í½¹Ì¹…ÁÁ•¹ ‰1MQ}Y%9}aA%Iˆ¤(€€€€€€€¥˜¹½Ð±ÍÐ¹É•‘••µ…‰±”½È±ÍÐ¹ÁÉ½Ñ½½±}Á…ÕÍ•è(€€€€€€€€€€€É•…Í½¹Ì¹…ÁÁ•¹ ‰1MQ}I5AQ%=9}U9Y%1	1ˆ¤(€€€€€€€¥˜±ÍÐ¹Ý¥Ñ¡‘É…Ý…±}‘•±…å}Í±½ÑÌ€øÁ½±¥ä¹µ…á¥µÕµ}±ÍÑ}Ý¥Ñ¡‘É…Ý…±}‘•±…å}Í±½ÑÌè(€€€€€€€€€€€É•…Í½¹Ì¹…ÁÁ•¹ ‰1MQ}]%Q!I]1}1e}U9AQ	1ˆ¤(€€€€€€€¥˜±ÍÐ¹Ù…±¥‘…Ñ½É}½¹•¹ÑÉ…Ñ¥½¹}‰ÁÌ€øÁ½±¥ä¹µ…á¥µÕµ}Ù…±¥‘…Ñ½É}½¹•¹ÑÉ…Ñ¥½¹}‰ÁÌè(€€€€€€€€€€€É•…Í½¹Ì¹…ÁÁ•¹ ‰1MQ}Y1%Q=I}=99QIQ%=9}U9AQ	1ˆ¤(€€€€€€€¥˜±ÍÐ¹É•‘•µÁÑ¥½¹}±¥ÅÕ¥‘¥Ñå}…Ñ½µ¥Œ€ðÁ½±¥ä¹µ¥¹¥µÕµ}É•‘•µÁÑ¥½¹}±¥ÅÕ¥‘¥Ñå}…Ñ½µ¥Œè(€€€€€€€€€€€É•…Í½¹Ì¹…ÁÁ•¹ ‰1MQ}I5AQ%=9}1%EU%%Qe}U9AQ	1ˆ¤(€€€ÍÑ…Ñ”€ô‘µ¥ÍÍ¥½¹MÑ…Ñ”¹5%QQ¥˜¹½ÐÉ•…Í½¹Ì•±Í”‘µ¥ÍÍ¥½¹MÑ…Ñ”¹	1=-(€€€‘¥•ÍÐ€ô}…¹½¹¥…±}‘¥•ÍÐ (€€€€€€€€‰µ¥¹Ðµ…‘µ¥ÍÍ¥½¸µ‘•¥Í¥½¸ˆ°(€€€€€€€€‰µÁÈµÍåÌ´ÀÄ¹µ¥¹Ðµ…‘µ¥ÍÍ¥½¸µ‘•¥Í¥½¸¹ØÄˆ°(€€€€€€€ì(€€€€€€€€€€€€‰µ¥¹Ñ}‘¥•ÍÐˆèÍ¹…ÁÍ¡½Ð¹‘¥•ÍÐ°(€€€€€€€€€€€€‰ÕÉÉ•¹Ñ}É½½Ñ}Í±½ÐˆèÕÉÉ•¹Ñ}É½½Ñ}Í±½Ð°(€€€€€€€€€€€€‰É•…Í½¹ÌˆèÉ•…Í½¹Ì°(€€€€€€€€€€€€‰±ÍÐˆè9½¹”¥˜±ÍÐ¥Ì9½¹”•±Í”…Í‘¥Ð¡±ÍÐ¤°(€€€€€€€ô°(€€€€¤(€€€É•ÑÕÉ¸‘µ¥ÍÍ¥½¹•¥Í¥½¸¡ÍÑ…Ñ”°ÑÕÁ±”¡É•…Í½¹Ì¤°‘¥•ÍÐ¤(()‘•˜•Ù…±Õ…Ñ•}Á½½° (€€€Í¹…ÁÍ¡½ÐèA½½±M¹…ÁÍ¡½Ð°(€€€½É…±”è=É…±•M¹…ÁÍ¡½Ð°(€€€€€°(€€€Á½±¥äèIÕ¹Ñ¥µ•QÉÕÑ¡A½±¥ä°(€€€É•¥ÍÑÉäè•Á±½å•‘%‘•¹Ñ¥ÑåI•¥ÍÑÉä°(€€€ÕÉÉ•¹Ñ}É½½Ñ}Í±½Ðè¥¹Ð°(¤€´ø‘µ¥ÍÍ¥½¹•¥Í¥½¸è(€€€É•…Í½¹Ìè±¥ÍÑmÍÑÉt€ômt(€€€¥˜Í¹…ÁÍ¡½Ð¹É•¥ÍÑÉå}•¹•É…Ñ¥½¸€„ôÉ•¥ÍÑÉä¹•¹•É…Ñ¥½¸è(€€€€€€€É•…Í½¹Ì¹…ÁÁ•¹ ‰5%a}I%MQIe}9IQ%=8ˆ¤(€€€ÑÉäè(€€€€€€€É•¥ÍÑÉä¹ÁÉ½É…´¡Í¹…ÁÍ¡½Ð¹ÁÉ½É…µ}¥¤¹…ÍÍ•ÉÑ}ÕÍ…‰±” (€€€€€€€€€€€ÕÉÉ•¹Ñ}É½½Ñ}Í±½ÐõÕÉÉ•¹Ñ}É½½Ñ}Í±½Ð(€€€€€€€€€¤(€€€•á•ÁÐI½½Ñ•‘QÉÕÑ¡ÉÉ½Èè(€€€€€€€É•…Í½¹Ì¹…ÁÁ•¹ ‰A==1}AI=I5}9=Q}QQMQˆ¤(€€€¥˜Í¹…ÁÍ¡½Ð¹½É…±•}¥€„ô½É…±”¹½É…±•}¥è(€€€€€€€É•…Í½¹Ì¹…ÁÁ•¹ ‰=I1}%}5%M5Q ˆ¤(€€€¥˜ÕÉÉ•¹Ñ}É½½Ñ}Í±½Ð€øÍ¹…ÁÍ¡½Ð¹•áÁ¥É•Í}…Ñ}Í±½Ðè(€€€€€€€É•…Í½¹Ì¹…ÁÁ•¹ ‰A==1}Y%9}aA%Iˆ¤(€€€¥˜ÕÉÉ•¹Ñ}É½½Ñ}Í±½Ð€´½É…±”¹½‰Í•ÉÙ•‘}Í±½Ð€øÁ½±¥ä¹µ…á¥µÕµ}½É…±•}ÍÑ…±•¹•ÍÍ}Í±½ÑÌè(€€€€€€€É•…Í½¹Ì¹…ÁÁ•¹ ‰=I1}MQ1ˆ¤(€€€¥˜½É…±”¹½¹™¥‘•¹•}‰ÁÌ€øÁ½±¥ä¹µ…á¥µÕµ}½É…±•}½¹™¥‘•¹•}‰ÁÌè(€€€€€€€É•…Í½¹Ì¹…ÁÁ•¹ ‰=I1}=9%9}U9AQ	1ˆ¤(€€€¥˜½É…±”¹‘¥Ù•É•¹•}‰ÁÌ€øÁ½±¥ä¹µ…á¥µÕµ}½É…±•}‘¥Ù•É•¹•}‰ÁÌè(€€€€€€€É•…Í½¹Ì¹…ÁÁ•¹ ‰=I1}%YI9}U9AQ	1ˆ¤(€€€ÍÑ…Ñ”€ô‘µ¥ÍÍ¥½¹MÑ…Ñ”¹5%QQ¥˜¹½ÐÉ•…Í½¹Ì•±Í”‘µ¥ÍÍ¥½¹MÑ…Ñ”¹	1=-(€€€‘¥•ÍÐ€ô}…¹½¹¥…±}‘¥•ÍÐ (€€€€€€€€‰Á½½°µ…‘µ¥ÍÍ¥½¸µ‘•¥Í¥½¸ˆ°(€€€€€€€€‰µÁÈµÍåÌ´ÀÄ¹Á½½°µ…‘µ¥ÍÍ¥½¸µ‘•¥Í¥½¸¹ØÄˆ°(€€€€€€€ì(€€€€€€€€€€€€‰Á½½±}‘¥•ÍÐˆèÍ¹…ÁÍ¡½Ð¹‘¥•ÍÐ°(€€€€€€€€€€€€‰½É…±”ˆè…Í‘¥Ð¡½É…±”¤°(€€€€€€€€€€€€‰É•¥ÍÑÉå}•¹•É…Ñ¥½¸ˆèÉ•¥ÍÑÉä¹•¹•É…Ñ¥½¸°(€€€€€€€€€€€€‰ÕÉÉ•¹Ñ}É½½Ñ}Í±½ÐˆèÕÉÉ•¹Ñ}É½½Ñ}Í±½Ð°(€€€€€€€€€€€€‰É•…Í½¹ÌˆèÉ•…Í½¹Ì°(€€€€€€€ô°(€€€€¤(€€€É•ÑÕÉ¸‘µ¥ÍÍ¥½¹•¥Í¥½¸¡ÍÑ…Ñ”°ÑÕÁ±”¡É•…Í½¹Ì¤°‘¥•ÍÐ¤(()‘…Ñ…±…ÍÌ¡™É½é•¸õQÉÕ”°Í±½ÑÌõQÉÕ”¤)±…ÍÌ…¹‘¥‘…Ñ•QÉÕÑ¡	¥¹‘¥¹œè(€€€…¹‘¥‘…Ñ•}¥èÍÑÈ(€€€µ•ÍÍ…•}Í¡„ÈÔØèÍÑÈ(€€€É•¥ÍÑÉå}•¹•É…Ñ¥½¸èÍÑÈ(€€€™½É­}½¹Ñ•áÑ}Í¡„ÈÔØèÍÑÈ(€€€‰±½­¡…Í¡}±•…Í•}Í¡„ÈÔØèÍÑÈ(€€€…±Ñ}Í¡„ÈÔÙÌèÑÕÁ±•mÍÑÈ°€¸¸¹t(€€€…‘µ¥ÍÍ¥½¹}•¹•É…Ñ¥½¸èÍÑÈ(€€€É½½Ñ•‘}ÑÉÕÑ¡}Í¡„ÈÔØèÍÑÈ((€€€‘•˜}}Á½ÍÑ}¥¹¥Ñ}|¡Í•±˜¤€´ø9½¹”è(€€€€€€€}¹½¹}•µÁÑä¡Í•±˜¹…¹‘¥‘…Ñ•}¥°€‰…¹‘¥‘…Ñ•}¥ˆ¤(€€€€€€€™½È™¥•±‘}¹…µ”¥¸€ (€€€€€€€€€€€€‰µ•ÍÍ…•}Í¡„ÈÔØˆ°(€€€€€€€€€€€€‰É•¥ÍÑÉå}•¹•É…Ñ¥½¸ˆ°(€€€€€€€€€€€€‰™½É­}½¹Ñ•áÑ}Í¡„ÈÔØˆ°(€€€€€€€€€€€€‰‰±½­¡…Í¡}±•…Í•}Í¡„ÈÔØˆ°(€€€€€€€€€€€€‰…‘µ¥ÍÍ¥½¹}•¹•É…Ñ¥½¸ˆ°(€€€€€€€€€€€€‰É½½Ñ•‘}ÑÉÕÑ¡}Í¡„ÈÔØˆ°(€€€€€€€€¤è(€€€€€€€€€€€}Í¡„ÈÔØ¡•Ñ…ÑÑÈ¡Í•±˜°™¥•±‘}¹…µ”¤°™¥•±‘}¹…µ”¤(€€€€€€€™½ÈÙ…±Õ”¥¸Í•±˜¹…±Ñ}Í¡„ÈÔÙÌè(€€€€€€€€€€€}Í¡„ÈÔØ¡Ù…±Õ”°€‰…±Ñ}Í¡„ÈÔÙÍmtˆ¤(()‘…Ñ…±…ÍÌ¡™É½é•¸õQÉÕ”°Í±½ÑÌõQÉÕ”¤)±…ÍÌI½½Ñ•‘IÕ¹Ñ¥µ•QÉÕÑ è(€€€É•¥ÍÑÉäè•Á±½å•‘%‘•¹Ñ¥ÑåI•¥ÍÑÉä(€€€™½É¬è½É­½¹Ñ•áÐ(€€€‰±½­¡…Í è	±½­¡…Í¡1•…Í”(€€€…±ÑÌèÑÕÁ±•m‘‘É•ÍÍ1½½­ÕÁQ…‰±•MÑ…Ñ”°€¸¸¹t(€€€…‘µ¥ÍÍ¥½¸èÍÍ•ÑY•¹Õ•‘µ¥ÍÍ¥½¸((€€€‘•˜}}Á½ÍÑ}¥¹¥Ñ}|¡Í•±˜¤€´ø9½¹”è(€€€€€€€Í•±˜¹™½É¬¹…ÍÍ•ÉÑ}É•¥ÍÑÉä¡Í•±˜¹É•¥ÍÑÉä¤(€€€€€€€¥˜Í•±˜¹‰±½­¡…Í ¹É•¥ÍÑÉå}•¹•É…Ñ¥½¸€„ôÍ•±˜¹É•¥ÍÑÉä¹•¹•É…Ñ¥½¸è(€€€€€€€€€€€É…¥Í”I½½Ñ•‘QÉÕÑ¡ÉÉ½È ‰‰±½­¡…Í ÕÍ•Ì„µ¥á•É•¥ÍÑÉä•¹•É…Ñ¥½¸ˆ¤(€€€€€€€¥˜Í•±˜¹…‘µ¥ÍÍ¥½¸¹µ¥¹Ð¹É•¥ÍÑÉå}•¹•É…Ñ¥½¸€„ôÍ•±˜¹É•¥ÍÑÉä¹•¹•É…Ñ¥½¸è(€€€€€€€€€€€É…¥Í”I½½Ñ•‘QÉÕÑ¡ÉÉ½È ‰µ¥¹ÐÕÍ•Ì„µ¥á•É•¥ÍÑÉä•¹•É…Ñ¥½¸ˆ¤(€€€€€€€¥˜Í•±˜¹…‘µ¥ÍÍ¥½¸¹Á½½°¹É•¥ÍÑÉå}•¹•É…Ñ¥½¸€„ôÍ•±˜¹É•¥ÍÑÉä¹•¹•É…Ñ¥½¸è(€€€€€€€€€€€É…¥Í”I½½Ñ•‘QÉÕÑ¡ÉÉ½È ‰Á½½°ÕÍ•Ì„µ¥á•É•¥ÍÑÉä•¹•É…Ñ¥½¸ˆ¤(€€€€€€€™½È…±Ð¥¸Í•±˜¹…±ÑÌè(€€€€€€€€€€€¥˜…±Ð¹É•¥ÍÑÉå}•¹•É…Ñ¥½¸€„ôÍ•±˜¹É•¥ÍÑÉä¹•¹•É…Ñ¥½¸è(€€€€€€€€€€€€€€€É…¥Í”I½½Ñ•‘QÉÕÑ¡ÉÉ½È ‰1PÕÍ•Ì„µ¥á•É•¥ÍÑÉä•¹•É…Ñ¥½¸ˆ¤((€€€ÁÉ½Á•ÉÑä(€€€‘•˜‘¥•ÍÐ¡Í•±˜¤€´øÍÑÈè(€€€€€€€É•ÑÕÉ¸}…¹½¹¥…±}‘¥•ÍÐ (€€€€€€€€€€€€‰É½½Ñ•µÉÕ¹Ñ¥µ”µÑÉÕÑ ˆ°(€€€€€€€€€€€I==Q}QIUQ!}M!5}%°(€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€‰É•¥ÍÑÉå}•¹•É…Ñ¥½¸ˆèÍ•±˜¹É•¥ÍÑÉä¹•¹•É…Ñ¥½¸°(€€€€€€€€€€€€€€€€‰™½É¬ˆè…Í‘¥Ð¡Í•±˜¹™½É¬¤°(€€€€€€€€€€€€€€€€‰‰±½­¡…Í ˆè…Í‘¥Ð¡Í•±˜¹‰±½­¡…Í ¤°(€€€€€€€€€€€€€€€€‰…±ÑÌˆèm…Í‘¥Ð¡¥Ñ•´¤™½È¥Ñ•´¥¸Í•±˜¹…±ÑÍt°(€€€€€€€€€€€€€€€€‰…‘µ¥ÍÍ¥½¹}•¹•É…Ñ¥½¸ˆèÍ•±˜¹…‘µ¥ÍÍ¥½¸¹•¹•É…Ñ¥½¸°(€€€€€€€€€€€ô°(€€€€€€€€¤((€€€‘•˜‰¥¹‘}…¹‘¥‘…Ñ” (€€€€€€€Í•±˜°(€€€€€€€€¨°(€€€€€€€…¹‘¥‘…Ñ•}¥èÍÑÈ°(€€€€€€€µ•ÍÍ…•}Í¡„ÈÔØèÍÑÈ°(€€€€€€€É•ÅÕ¥É•‘}ÁÉ½É…µ}¥‘ÌèM•ÅÕ•¹•mÍÑÉt°(€€€€€€€•áÁ•Ñ•‘}…±Ñ}‘¥•ÍÑÌèM•ÅÕ•¹•mÍÑÉt°(€€€€€€€ÕÉÉ•¹Ñ}É½½Ñ}Í±½Ðè¥¹Ð°(€€€€€€€ÕÉÉ•¹Ñ}‰±½­}¡•¥¡Ðè¥¹Ð°(€€€€€€€ÉÁ}É•Á½ÉÑÍ}‰±½­¡…Í¡}Ù…±¥è‰½½°°(€€€€¤€´ø…¹‘¥‘…Ñ•QÉÕÑ¡	¥¹‘¥¹œè(€€€€€€€}¹½¹}•µÁÑä¡…¹‘¥‘…Ñ•}¥°€‰…¹‘¥‘…Ñ•}¥ˆ¤(€€€€€€€}Í¡„ÈÔØ¡µ•ÍÍ…•}Í¡„ÈÔØ°€‰µ•ÍÍ…•}Í¡„ÈÔØˆ¤(€€€€€€€¥˜ÕÉÉ•¹Ñ}É½½Ñ}Í±½Ð€ðÍ•±˜¹™½É¬¹É½½Ñ}Í±½Ðè(€€€€€€€€€€€É…¥Í”I½½Ñ•‘QÉÕÑ¡ÉÉ½È ‰ÕÉÉ•¹ÐÉ½½ÐÉ•É•ÍÍ•‰•¡¥¹™½É¬½¹Ñ•áÐˆ¤(€€€€€€€Í•±˜¹É•¥ÍÑÉä¹…ÍÍ•ÉÑ}ÁÉ½É…µÌ (€€€€€€€€€€€É•ÅÕ¥É•‘}ÁÉ½É…µ}¥‘Ì°(€€€€€€€€€€€ÕÉÉ•¹Ñ}É½½Ñ}Í±½ÐõÕÉÉ•¹Ñ}É½½Ñ}Í±½Ð°(€€€€€€€€¤(€€€€€€€Í•±˜¹‰±½­¡…Í ¹…ÍÍ•ÉÑ}Ù…±¥ (€€€€€€€€€€€ÕÉÉ•¹Ñ}‰±½­}¡•¥¡ÐõÕÉÉ•¹Ñ}‰±½­}¡•¥¡Ð°(€€€€€€€€€€€É•¥ÍÑÉå}•¹•É…Ñ¥½¸õÍ•±˜¹É•¥ÍÑÉä¹•¹•É…Ñ¥½¸°(€€€€€€€€€€€ÉÁ}É•Á½ÉÑÍ}Ù…±¥õÉÁ}É•Á½ÉÑÍ}‰±½­¡…Í¡}Ù…±¥°(€€€€€€€€¤(€€€€€€€…ÑÕ…±}…±Ñ}‘¥•ÍÑÌ€ôÑÕÁ±”¡¥Ñ•´¹‘¥•ÍÐ™½È¥Ñ•´¥¸Í•±˜¹…±ÑÌ¤(€€€€€€€¥˜ÑÕÁ±”¡•áÁ•Ñ•‘}…±Ñ}‘¥•ÍÑÌ¤€„ô…ÑÕ…±}…±Ñ}‘¥•ÍÑÌè(€€€€€€€€€€€É…¥Í”I½½Ñ•‘QÉÕÑ¡ÉÉ½È ‰½µÁ¥±•µ•ÍÍ…”1PÍ•Ð½½É‘•È¡…¹•ˆ¤(€€€€€€€™½È…±Ð¥¸Í•±˜¹…±ÑÌè(€€€€€€€€€€€…±Ð¹…ÍÍ•ÉÑ}ÕÍ…‰±” (€€€€€€€€€€€€€€€ÕÉÉ•¹Ñ}É½½Ñ}Í±½ÐõÕÉÉ•¹Ñ}É½½Ñ}Í±½Ð°(€€€€€€€€€€€€€€€É•¥ÍÑÉå}•¹•É…Ñ¥½¸õÍ•±˜¹É•¥ÍÑÉä¹•¹•É…Ñ¥½¸°(€€€€€€€€€€€€¤(€€€€€€€Í•±˜¹…‘µ¥ÍÍ¥½¸¹…ÍÍ•ÉÑ}…‘µ¥ÑÑ•¡ÕÉÉ•¹Ñ}É½½Ñ}Í±½ÐõÕÉÉ•¹Ñ}É½½Ñ}Í±½Ð¤(€€€€€€€É•ÑÕÉ¸…¹‘¥‘…Ñ•QÉÕÑ¡	¥¹‘¥¹œ (€€€€€€€€€€€…¹‘¥‘…Ñ•}¥õ…¹‘¥‘…Ñ•}¥°(€€€€€€€€€€€µ•ÍÍ…•}Í¡„ÈÔØõµ•ÍÍ…•}Í¡„ÈÔØ°(€€€€€€€€€€€É•¥ÍÑÉå}•¹•É…Ñ¥½¸õÍ•±˜¹É•¥ÍÑÉä¹•¹•É…Ñ¥½¸°(€€€€€€€€€€€™½É­}½¹Ñ•áÑ}Í¡„ÈÔØõÍ•±˜¹™½É¬¹‘¥•ÍÐ°(€€€€€€€€€€€‰±½­¡…Í¡}±•…Í•}Í¡„ÈÔØõÍ•±˜¹‰±½­¡…Í ¹‘¥•ÍÐ°(€€€€€€€€€€€…±Ñ}Í¡„ÈÔÙÌõ…ÑÕ…±}…±Ñ}‘¥•ÍÑÌ°(€€€€€€€€€€€…‘µ¥ÍÍ¥½¹}•¹•É…Ñ¥½¸õÍ•±˜¹…‘µ¥ÍÍ¥½¸¹•¹•É…Ñ¥½¸°(€€€€€€€€€€€É½½Ñ•‘}ÑÉÕÑ¡}Í¡„ÈÔØõÍ•±˜¹‘¥•ÍÐ°(€€€€€€€€¤(()‘•˜‰Õ¥±‘}…‘µ¥ÍÍ¥½¸ (€€€€¨°(€€€µ¥¹Ðè5¥¹ÑM¹…ÁÍ¡½Ð°(€€€½É…±”è=É…±•M¹…ÁÍ¡½Ð°(€€€Á½½°èA½½±M¹…ÁÍ¡½Ð°(€€€Á½±¥äèIÕ¹Ñ¥µ•QÉÕÑ¡A½±¥ä°(€€€É•¥ÍÑÉäè•Á±½å•‘%‘•¹Ñ¥ÑåI•¥ÍÑÉä°(€€€ÕÉÉ•¹Ñ}É½½Ñ}Í±½Ðè¥¹Ð°(€€€±ÍÐè1MQM¹…ÁÍ¡½Ðð9½¹”€ô9½¹”°(¤€´øÍÍ•ÑY•¹Õ•‘µ¥ÍÍ¥½¸è(€€€µ¥¹Ñ}‘•¥Í¥½¸€ô•Ù…±Õ…Ñ•}µ¥¹Ð (€€€€€€€µ¥¹Ð°(€€€€€€€Á½±¥äõÁ½±¥ä°(€€€€€€€ÕÉÉ•¹Ñ}É½½Ñ}Í±½ÐõÕÉÉ•¹Ñ}É½½Ñ}Í±½Ð°(€€€€€€€•áÁ•Ñ•‘}É•¥ÍÑÉå}•¹•É…Ñ¥½¸õÉ•¥ÍÑÉä¹•¹•É…Ñ¥½¸°(€€€€€€€±ÍÐõ±ÍÐ°(€€€€¤(€€€Á½½±}‘•¥Í¥½¸€ô•Ù…±Õ…Ñ•}Á½½° (€€€€€€€Á½½°°(€€€€€€€½É…±”°(€€€€€€€Á½±¥äõÁ½±¥ä°(€€€€€€€É•¥ÍÑÉäõÉ•¥ÍÑÉä°(€€€€€€€ÕÉÉ•¹Ñ}É½½Ñ}Í±½ÐõÕÉÉ•¹Ñ}É½½Ñ}Í±½Ð°(€€€€¤(€€€•áÁ¥É•Í}…Ñ}Í±½Ð€ôµ¥¸¡¥¹Ð¹µ¥¹Ð¹•áÁ¥É•Í}…Ñ}Í±½Ð°Á½½°¹•áÁ¥É•Í}…Ñ}Í±½Ð¤(€€€•¹•É…Ñ¥½¸€ôÍÍ•ÑY•¹Õ•‘µ¥ÍÍ¥½¸¹½µÁÕÑ•}•¹•É…Ñ¥½¸ (€€€€€€€µ¥¹Ðõµ¥¹Ð°(€€€€€€€½É…±”õ½É…±”°(€€€€€€€Á½½°õÁ½½°°(€€€€€€€µ¥¹Ñ}‘•¥Í¥½¸õµ¥¹Ñ}‘•¥Í¥½¸°(€€€€€€€Á½½±}‘•¥Í¥½¸õÁ½½±}‘•¥Í¥½¸°(€€€€€€€•áÁ¥É•Í}…Ñ}Í±½Ðõ•áÁ¥É•Í}…Ñ}Í±½Ð°(€€€€€€€±ÍÐõ±ÍÐ°(€€€€¤(€€€É•ÑÕÉ¸ÍÍ•ÑY•¹Õ•‘µ¥ÍÍ¥½¸ (€€€€€€€µ¥¹Ðõµ¥¹Ð°(€€€€€€€½É…±”õ½É…±”°(€€€€€€€Á½½°õÁ½½°°(€€€€€€€µ¥¹Ñ}‘•¥Í¥½¸õµ¥¹Ñ}‘•¥Í¥½¸°(€€€€€€€Á½½±}‘•¥Í¥½¸õÁ½½±}‘•¥Í¥½¸°(€€€€€€€•¹•É…Ñ¥½¸õ•¹•É…Ñ¥½¸°(€€€€€€€•áÁ¥É•Í}…Ñ}Í±½Ðõ•áÁ¥É•Í}…Ñ}Í±½Ð°(€€€€€€€±ÍÐõ±ÍÐ°(€€€€¤(()‘•˜…¹½¹¥…±}ÍÑ…Ñ¥}ÁÉ½É…µÌ ¤€´øÑÕÁ±•mÍÑÈ°€¸¸¹tè(€€€€ˆˆ‰I•ÑÕÉ¸Ñ¡”ÍÑ…‰±”ÁÉ½É…´Í•ÐÝ¡½Í”¥‘•¹Ñ¥Ñ¥•Ì…É”½Ý¹•‰ä¡…¥¹}É•¥ÍÑÉä¸ˆˆˆ((€€€É•ÑÕÉ¸€ (€€€€€€€MeMQ5}AI=I5}IML°(€€€€€€€Q=-9}AI=I5}IML°(€€€€€€€Q=-9|ÈÀÈÉ}AI=I5}IML°(€€€€€€€MM=%Q}Q=-9}AI=I5}IML°(€€€€€€€=5AUQ}	UQ}AI=I5}IML°(€€€€€€€IMM}1==-UA}Q	1}AI=I5}IML°(€€€€¤(()}}…±±}|€ôl(€€€€‰‘µ¥ÍÍ¥½¹•¥Í¥½¸ˆ°(€€€€‰‘µ¥ÍÍ¥½¹MÑ…Ñ”ˆ°(€€€€‰‘‘É•ÍÍ1½½­ÕÁQ…‰±•MÑ…Ñ”ˆ°(€€€€‰ÍÍ•ÑY•¹Õ•‘µ¥ÍÍ¥½¸ˆ°(€€€€‰	±½­¡…Í¡1•…Í”ˆ°(€€€€‰…¹‘¥‘…Ñ•QÉÕÑ¡	¥¹‘¥¹œˆ°(€€€€‰•Á±½å•‘%‘•¹Ñ¥ÑåI•¥ÍÑÉäˆ°(€€€€‰½É­½¹Ñ•áÐˆ°(€€€€‰1MQM¹…ÁÍ¡½Ðˆ°(€€€€‰5¥¹ÑM¹…ÁÍ¡½Ðˆ°(€€€€‰=É…±•M¹…ÁÍ¡½Ðˆ°(€€€€‰A½½±M¹…ÁÍ¡½Ðˆ°(€€€€‰AÉ½É…µ•Á±½åµ•¹Ðˆ°(€€€€‰I==Q}QIUQ!}Y%9}M!5}%ˆ°(€€€€‰I==Q}QIUQ!}A=1%e}M!5}%ˆ°(€€€€‰I==Q}QIUQ!}M!5}%ˆ°(€€€€‰I½½Ñ•‘IÕ¹Ñ¥µ•QÉÕÑ ˆ°(€€€€‰I½½Ñ•‘QÉÕÑ¡ÉÉ½Èˆ°(€€€€‰IÕ¹Ñ¥µ•QÉÕÑ¡A½±¥äˆ°(€€€€‰‰Õ¥±‘}…‘µ¥ÍÍ¥½¸ˆ°(€€€€‰…¹½¹¥…±}ÍÑ…Ñ¥}ÁÉ½É…µÌˆ°(€€€€‰•Ù…±Õ…Ñ•}µ¥¹Ðˆ°(€€€€‰•Ù…±Õ…Ñ•}Á½½°ˆ°)t(