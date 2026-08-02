"""Rooted mint, oracle, pool and LST admission."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib import resources
import json

from src.config.chain_registry import (
    TOKEN_2022_PROGRAM_ADDRESS,
    TOKEN_PROGRAM_ADDRESS,
    validate_pubkey,
)

from .common import (
    AdmissionState,
    ROOTED_TRUTH_POLICY_SCHEMA_ID,
    RootedTruthError,
    digest,
    integer,
    sha256,
    text,
)
from .identity import DeployedIdentityRegistry


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
    withheld_amount: int
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
        if self.token_program_id not in {
            TOKEN_PROGRAM_ADDRESS,
            TOKEN_2022_PROGRAM_ADDRESS,
        }:
            raise RootedTruthError("mint owner is not a canonical token program")
        for name in (
            "decimals",
            "transfer_fee_bps",
            "withheld_amount",
            "account_length",
            "rent_lamports",
            "context_slot",
            "root_slot",
            "expires_at_slot",
        ):
            integer(getattr(self, name), name)
        if (
            self.decimals > 255
            or self.transfer_fee_bps > 10_000
            or self.root_slot > self.context_slot
        ):
            raise RootedTruthError("invalid mint bounds")
        for name in (
            "mint_authority",
            "freeze_authority",
            "permanent_delegate",
            "transfer_hook_program",
        ):
            value = getattr(self, name)
            if value:
                validate_pubkey(value, field=name)
        sha256(self.registry_generation, "registry_generation")
        sha256(self.evidence_sha256, "evidence_sha256")

    @property
    def digest(self) -> str:
        return digest(
            "mint-snapshot",
            "mpr-sys-01.mint-snapshot.v1",
            asdict(self),
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
        text(self.oracle_id, "oracle_id")
        for name in (
            "price_atomic",
            "confidence_bps",
            "divergence_bps",
            "observed_slot",
            "root_slot",
        ):
            integer(getattr(self, name), name)
        if self.root_slot > self.observed_slot or not self.source_ids:
            raise RootedTruthError("invalid oracle context")
        sha256(self.evidence_sha256, "evidence_sha256")


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
        text(self.pool_id, "pool_id")
        validate_pubkey(self.program_id, field="program_id")
        if not self.vault_owners:
            raise RootedTruthError("pool must declare vault owners")
        for owner in self.vault_owners:
            validate_pubkey(owner, field="vault_owner")
        for name in (
            "fee_bps",
            "context_slot",
            "root_slot",
            "expires_at_slot",
        ):
            integer(getattr(self, name), name)
        if self.fee_bps > 10_000 or self.root_slot > self.context_slot:
            raise RootedTruthError("invalid pool bounds")
        text(self.oracle_id, "oracle_id")
        sha256(self.registry_generation, "registry_generation")
        sha256(self.evidence_sha256, "evidence_sha256")

    @property
    def digest(self) -> str:
        return digest(
            "pool-snapshot",
            "mpr-sys-01.pool-snapshot.v1",
            asdict(self),
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
        for name in (
            "withdrawal_delay_slots",
            "validator_concentration_bps",
            "redemption_liquidity_atomic",
            "expires_at_slot",
        ):
            integer(getattr(self, name), name)
        sha256(self.evidence_sha256, "evidence_sha256")


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

    @classmethod
    def load_default(cls) -> "RuntimeTruthPolicy":
        payload = json.loads(
            resources.files("src.resources")
            .joinpath("rooted_runtime_truth_policy.json")
            .read_text()
        )
        if payload.pop("schema_id", None) != ROOTED_TRUTH_POLICY_SCHEMA_ID:
            raise RootedTruthError("unexpected rooted runtime policy schema")
        return cls(
            allow_token_2022=payload["allow_token_2022"],
            supported_token_2022_extensions=frozenset(
                payload["supported_token_2022_extensions"]
            ),
            maximum_transfer_fee_bps=payload["maximum_transfer_fee_bps"],
            allowed_transfer_hook_programs=frozenset(
                payload["allowed_transfer_hook_programs"]
            ),
            maximum_oracle_confidence_bps=payload[
                "maximum_oracle_confidence_bps"
            ],
            maximum_oracle_divergence_bps=payload[
                "maximum_oracle_divergence_bps"
            ],
            maximum_oracle_staleness_slots=payload[
                "maximum_oracle_staleness_slots"
            ],
            maximum_lst_withdrawal_delay_slots=payload[
                "maximum_lst_withdrawal_delay_slots"
            ],
            maximum_validator_concentration_bps=payload[
                "maximum_validator_concentration_bps"
            ],
            minimum_redemption_liquidity_atomic=payload[
                "minimum_redemption_liquidity_atomic"
            ],
            external_required_programs=tuple(
                payload["external_required_programs"]
            ),
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

    @property
    def admitted(self) -> bool:
        return self.mint_decision.admitted and self.pool_decision.admitted

    def assert_admitted(self, *, current_root_slot: int) -> None:
        if current_root_slot > self.expires_at_slot:
            raise RootedTruthError("admission evidence expired")
        if not self.admitted:
            raise RootedTruthError("admission is blocked")


def _decision(
    domain: str,
    reasons: list[str],
    payload: object,
) -> AdmissionDecision:
    state = AdmissionState.ADMITTED if not reasons else AdmissionState.BLOCKED
    return AdmissionDecision(
        state=state,
        reasons=tuple(reasons),
        digest=digest(domain, f"mpr-sys-01.{domain}.v1", payload),
    )


def evaluate_mint(
    snapshot: MintSnapshot,
    *,
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
    if snapshot.mint_authority:
        reasons.append("MINT_AUTHORITY_PRESENT")
    if snapshot.freeze_authority:
        reasons.append("FREEZE_AUTHORITY_PRESENT")
    if snapshot.permanent_delegate:
        reasons.append("PERMANENT_DELEGATE_PRESENT")
    if snapshot.withheld_amount:
        reasons.append("WITHHELD_FEE_PRESENT")
    if snapshot.transfer_fee_bps > policy.maximum_transfer_fee_bps:
        reasons.append("TRANSFER_FEE_EXCEEDS_POLICY")
    if snapshot.token_program_id == TOKEN_2022_PROGRAM_ADDRESS:
        if not policy.allow_token_2022:
            reasons.append("TOKEN_2022_DEFAULT_DENY")
        unsupported = set(snapshot.extensions) - set(
            policy.supported_token_2022_extensions
        )
        if unsupported:
            reasons.append("UNSUPPORTED_TOKEN_2022_EXTENSIONS")
        if (
            snapshot.transfer_hook_program
            and snapshot.transfer_hook_program
            not in policy.allowed_transfer_hook_programs
        ):
            reasons.append("TRANSFER_HOOK_NOT_ALLOWLISTED")
    if lst:
        if lst.mint != snapshot.mint or current_root_slot > lst.expires_at_slot:
            reasons.append("LST_EVIDENCE_INVALID")
        if not lst.redeemable or lst.protocol_paused:
            reasons.append("LST_REDEMPTION_UNAVAILABLE")
        if (
            lst.withdrawal_delay_slots
            > policy.maximum_lst_withdrawal_delay_slots
        ):
            reasons.append("LST_WITHDRAWAL_DELAY")
        if (
            lst.validator_concentration_bps
            > policy.maximum_validator_concentration_bps
        ):
            reasons.append("LST_CONCENTRATION")
        if (
            lst.redemption_liquidity_atomic
            < policy.minimum_redemption_liquidity_atomic
        ):
            reasons.append("LST_LIQUIDITY")
    return _decision(
        "mint-admission-decision",
        reasons,
        {
            "mint": snapshot.digest,
            "root": current_root_slot,
            "lst": None if lst is None else asdict(lst),
        },
    )


def evaluate_pool(
    snapshot: PoolSnapshot,
    oracle: OracleSnapshot,
    *,
    policy: RuntimeTruthPolicy,
    registry: DeployedIdentityRegistry,
    current_root_slot: int,
) -> AdmissionDecision:
    reasons: list[str] = []
    if snapshot.registry_generation != registry.generation:
        reasons.append("MIXED_REGISTRY_GENERATION")
    try:
        registry.program(snapshot.program_id).assert_usable(current_root_slot)
    except RootedTruthError:
        reasons.append("POOL_PROGRAM_NOT_ATTESTED")
    if snapshot.oracle_id != oracle.oracle_id:
        reasons.append("ORACLE_ID_MISMATCH")
    if current_root_slot > snapshot.expires_at_slot:
        reasons.append("POOL_EVIDENCE_EXPIRED")
    if (
        current_root_slot - oracle.observed_slot
        > policy.maximum_oracle_staleness_slots
    ):
        reasons.append("ORACLE_STALE")
    if oracle.confidence_bps > policy.maximum_oracle_confidence_bps:
        reasons.append("ORACLE_CONFIDENCE_UNACCEPTABLE")
    if oracle.divergence_bps > policy.maximum_oracle_divergence_bps:
        reasons.append("ORACLE_DIVERGENCE")
    return _decision(
        "pool-admission-decision",
        reasons,
        {
            "pool": snapshot.digest,
            "oracle": asdict(oracle),
            "root": current_root_slot,
        },
    )


def build_admission(
    *,
    mint: MintSnapshot,
    oracle: OracleSnapshot,
    pool: PoolSnapshot,
    policy: RuntimeTruthPolicy,
    registry: DeployedIdentityRegistry,
    current_root_slot: int,
    lst: LSTSnapshot | None = None,
) -> AssetVenueAdmission:
    mint_decision = evaluate_mint(
        mint,
        policy=policy,
        current_root_slot=current_root_slot,
        expected_registry_generation=registry.generation,
        lst=lst,
    )
    pool_decision = evaluate_pool(
        pool,
        oracle,
        policy=policy,
        registry=registry,
        current_root_slot=current_root_slot,
    )
    expires_at_slot = min(mint.expires_at_slot, pool.expires_at_slot)
    generation = digest(
        "asset-venue-admission",
        "mpr-sys-01.asset-venue-admission.v1",
        {
            "mint": mint.digest,
            "pool": pool.digest,
            "mint_decision": asdict(mint_decision),
            "pool_decision": asdict(pool_decision),
            "expires_at_slot": expires_at_slot,
        },
    )
    return AssetVenueAdmission(
        mint=mint,
        oracle=oracle,
        pool=pool,
        mint_decision=mint_decision,
        pool_decision=pool_decision,
        generation=generation,
        expires_at_slot=expires_at_slot,
        lst=lst,
    )
