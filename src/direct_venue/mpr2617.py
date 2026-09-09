"""MPR-2617 direct-venue capability and route qualification boundary.

This module is deliberately side-effect free. It does not perform RPC/HTTP calls,
compile transactions, sign, submit, mutate capital, or promote live execution.
It validates exact venue/pool evidence before existing canonical owners may consume
one direct-venue route leg.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Mapping, Sequence

MPR2617_SCHEMA = "mpr2617.direct-venue-capability.v1"
ORCA_WHIRLPOOLS_PROGRAM_ID = "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"
ORCA_REVIEWED_SOURCE_COMMIT = "408c945fef4c49ab70def4303377cfaf8f0f3c99"
ORCA_SOURCE_REPOSITORY = "https://github.com/orca-so/whirlpools"
ORCA_LICENSE_CLASS = "ORCA_LICENSE_POST_2025-02-26"

_B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class DirectVenueError(ValueError):
    """Malformed or semantically unsafe direct-venue evidence."""


class VenueFamily(StrEnum):
    JUPITER = "jupiter"
    ORCA_WHIRLPOOLS = "orca-whirlpools"
    RAYDIUM_CPMM = "raydium-cpmm"
    RAYDIUM_CLMM = "raydium-clmm"
    METEORA_DLMM = "meteora-dlmm"
    PHOENIX = "phoenix"
    OPENBOOK_V2 = "openbook-v2"


class CapabilityState(StrEnum):
    RESEARCH = "research"
    OFFLINE_VERIFIED = "offline-verified"
    SHADOW_QUALIFIED = "shadow-qualified"
    CANARY_ELIGIBLE = "canary-eligible"
    PRODUCTION_QUALIFIED = "production-qualified"
    BLOCKED = "blocked"
    REVOKED = "revoked"


class RouteMode(StrEnum):
    RESEARCH = "research"
    SHADOW = "shadow"
    CANARY = "canary"
    PRODUCTION = "production"


@dataclass(frozen=True, slots=True)
class TokenIdentity:
    mint: str
    token_program: str
    decimals: int
    transfer_fee_supported: bool = False
    unsupported_extensions_present: bool = False

    def __post_init__(self) -> None:
        _pubkey(self.mint, "mint")
        _pubkey(self.token_program, "token_program")
        if isinstance(self.decimals, bool) or not 0 <= self.decimals <= 18:
            raise DirectVenueError("decimals must be an integer in [0,18]")
        if not isinstance(self.transfer_fee_supported, bool):
            raise DirectVenueError("transfer_fee_supported must be bool")
        if not isinstance(self.unsupported_extensions_present, bool):
            raise DirectVenueError("unsupported_extensions_present must be bool")


@dataclass(frozen=True, slots=True)
class RootedAccountEvidence:
    address: str
    owner: str
    slot: int
    root_slot: int
    data_sha256: str
    generation: str

    def __post_init__(self) -> None:
        _pubkey(self.address, "account.address")
        _pubkey(self.owner, "account.owner")
        _positive_int(self.slot, "account.slot")
        _positive_int(self.root_slot, "account.root_slot")
        if self.slot > self.root_slot:
            raise DirectVenueError("account slot cannot be newer than admitted root")
        _sha256(self.data_sha256, "account.data_sha256")
        _text(self.generation, "account.generation")


@dataclass(frozen=True, slots=True)
class InstructionAccount:
    address: str
    writable: bool
    signer: bool
    role: str

    def __post_init__(self) -> None:
        _pubkey(self.address, "instruction account")
        _text(self.role, "instruction account role")
        if not isinstance(self.writable, bool) or not isinstance(self.signer, bool):
            raise DirectVenueError("instruction writable/signer flags must be bool")


@dataclass(frozen=True, slots=True)
class OrcaWhirlpoolProof:
    source_commit: str
    source_repository: str
    license_class: str
    program_id: str
    pool: RootedAccountEvidence
    token_a: TokenIdentity
    token_b: TokenIdentity
    vault_a: RootedAccountEvidence
    vault_b: RootedAccountEvidence
    tick_spacing: int
    fee_rate_ppm: int
    protocol_fee_rate_bps: int
    sqrt_price_x64: int
    liquidity: int
    tick_arrays: tuple[RootedAccountEvidence, ...]
    tick_array_start_indexes: tuple[int, ...]
    quote_math_version: str
    quote_vector_sha256: str
    local_quote_out: int
    reference_quote_out: int
    amount_in: int
    minimum_out: int
    instruction_data_sha256: str
    instruction_accounts: tuple[InstructionAccount, ...]
    expected_instruction_accounts_sha256: str
    provider_identity: str
    provider_budget_receipt_sha256: str
    evidence_generation: str
    license_review_approved: bool = False

    def __post_init__(self) -> None:
        _git_sha(self.source_commit, "source_commit")
        if self.source_repository != ORCA_SOURCE_REPOSITORY:
            raise DirectVenueError("unexpected Orca source repository")
        _text(self.license_class, "license_class")
        _pubkey(self.program_id, "program_id")
        if self.program_id != ORCA_WHIRLPOOLS_PROGRAM_ID:
            raise DirectVenueError("unexpected Orca Whirlpools program id")
        for name in ("tick_spacing", "fee_rate_ppm", "protocol_fee_rate_bps"):
            _positive_int(getattr(self, name), name, allow_zero=name != "tick_spacing")
        _positive_int(self.sqrt_price_x64, "sqrt_price_x64")
        _positive_int(self.liquidity, "liquidity")
        _positive_int(self.amount_in, "amount_in")
        _positive_int(self.local_quote_out, "local_quote_out")
        _positive_int(self.reference_quote_out, "reference_quote_out")
        _positive_int(self.minimum_out, "minimum_out")
        if self.minimum_out > self.reference_quote_out:
            raise DirectVenueError("minimum_out cannot exceed qualified reference output")
        if not self.tick_arrays:
            raise DirectVenueError("at least one rooted tick array is required")
        if len(self.tick_arrays) != len(self.tick_array_start_indexes):
            raise DirectVenueError("tick array/index cardinality mismatch")
        if len({item.address for item in self.tick_arrays}) != len(self.tick_arrays):
            raise DirectVenueError("tick array addresses must be unique")
        if not self.instruction_accounts:
            raise DirectVenueError("instruction account vector is required")
        _text(self.quote_math_version, "quote_math_version")
        _sha256(self.quote_vector_sha256, "quote_vector_sha256")
        _sha256(self.instruction_data_sha256, "instruction_data_sha256")
        _sha256(
            self.expected_instruction_accounts_sha256,
            "expected_instruction_accounts_sha256",
        )
        _text(self.provider_identity, "provider_identity")
        _sha256(self.provider_budget_receipt_sha256, "provider_budget_receipt_sha256")
        _text(self.evidence_generation, "evidence_generation")
        if not isinstance(self.license_review_approved, bool):
            raise DirectVenueError("license_review_approved must be bool")
        if self.token_a.mint == self.token_b.mint:
            raise DirectVenueError("pool token mints must differ")
        if self.vault_a.address == self.vault_b.address:
            raise DirectVenueError("pool vaults must differ")


@dataclass(frozen=True, slots=True)
class VenueCapability:
    capability_id: str
    venue: VenueFamily
    cluster: str
    genesis_sha256: str
    pool_or_market: str
    input_mint: str
    output_mint: str
    deployment_generation: str
    account_layout_version: str
    instruction_family: str
    quote_math_version: str
    evidence_sha256: str
    instruction_data_sha256: str
    instruction_accounts_sha256: str
    state: CapabilityState
    expires_at_unix: int
    revoked: bool = False
    schema: str = MPR2617_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != MPR2617_SCHEMA:
            raise DirectVenueError("unsupported capability schema")
        for name in (
            "capability_id",
            "cluster",
            "deployment_generation",
            "account_layout_version",
            "instruction_family",
            "quote_math_version",
        ):
            value = getattr(self, name)
            _text(value, name)
            if "*" in value.lower() or value.lower() in {"all", "any"}:
                raise DirectVenueError(f"wildcard capability field forbidden: {name}")
        _pubkey(self.pool_or_market, "pool_or_market")
        _pubkey(self.input_mint, "input_mint")
        _pubkey(self.output_mint, "output_mint")
        if self.input_mint == self.output_mint:
            raise DirectVenueError("route direction must use distinct mints")
        _sha256(self.genesis_sha256, "genesis_sha256")
        _sha256(self.evidence_sha256, "evidence_sha256")
        _sha256(self.instruction_data_sha256, "instruction_data_sha256")
        _sha256(self.instruction_accounts_sha256, "instruction_accounts_sha256")
        _positive_int(self.expires_at_unix, "expires_at_unix")
        if not isinstance(self.revoked, bool):
            raise DirectVenueError("revoked must be bool")

    @property
    def capability_hash(self) -> str:
        return _digest(self)


@dataclass(frozen=True, slots=True)
class DirectRouteLeg:
    venue: VenueFamily
    capability_hash: str
    pool_or_market: str
    input_mint: str
    output_mint: str
    amount_in: int
    guaranteed_min_out: int
    evidence_generation: str
    instruction_data_sha256: str
    instruction_accounts_sha256: str

    def __post_init__(self) -> None:
        _sha256(self.capability_hash, "capability_hash")
        _pubkey(self.pool_or_market, "pool_or_market")
        _pubkey(self.input_mint, "input_mint")
        _pubkey(self.output_mint, "output_mint")
        _positive_int(self.amount_in, "amount_in")
        _positive_int(self.guaranteed_min_out, "guaranteed_min_out")
        _text(self.evidence_generation, "evidence_generation")
        _sha256(self.instruction_data_sha256, "instruction_data_sha256")
        _sha256(self.instruction_accounts_sha256, "instruction_accounts_sha256")


@dataclass(frozen=True, slots=True)
class RouteQualification:
    accepted: bool
    mode: RouteMode
    blockers: tuple[str, ...]
    capability_hashes: tuple[str, ...]
    route_hash: str
    live_enabled: bool = False


class VenueCapabilityRegistry:
    """Exact non-wildcard capability registry. No network or execution methods."""

    def __init__(self, capabilities: Sequence[VenueCapability]) -> None:
        by_hash: dict[str, VenueCapability] = {}
        for capability in capabilities:
            digest = capability.capability_hash
            if digest in by_hash:
                raise DirectVenueError("duplicate capability hash")
            by_hash[digest] = capability
        self._by_hash = by_hash

    def get(self, capability_hash: str) -> VenueCapability:
        _sha256(capability_hash, "capability_hash")
        try:
            return self._by_hash[capability_hash]
        except KeyError as exc:
            raise DirectVenueError("unknown capability") from exc

    def require_for_mode(
        self, capability_hash: str, mode: RouteMode, *, now_unix: int
    ) -> VenueCapability:
        capability = self.get(capability_hash)
        if capability.revoked or capability.state is CapabilityState.REVOKED:
            raise DirectVenueError("capability revoked")
        if capability.state is CapabilityState.BLOCKED:
            raise DirectVenueError("capability blocked")
        if now_unix >= capability.expires_at_unix:
            raise DirectVenueError("capability expired")
        minimum = {
            RouteMode.RESEARCH: {
                CapabilityState.RESEARCH,
                CapabilityState.OFFLINE_VERIFIED,
                CapabilityState.SHADOW_QUALIFIED,
                CapabilityState.CANARY_ELIGIBLE,
                CapabilityState.PRODUCTION_QUALIFIED,
            },
            RouteMode.SHADOW: {
                CapabilityState.SHADOW_QUALIFIED,
                CapabilityState.CANARY_ELIGIBLE,
                CapabilityState.PRODUCTION_QUALIFIED,
            },
            RouteMode.CANARY: {
                CapabilityState.CANARY_ELIGIBLE,
                CapabilityState.PRODUCTION_QUALIFIED,
            },
            RouteMode.PRODUCTION: {CapabilityState.PRODUCTION_QUALIFIED},
        }[mode]
        if capability.state not in minimum:
            raise DirectVenueError(
                f"capability state {capability.state.value} insufficient for {mode.value}"
            )
        return capability


def qualify_orca_offline(proof: OrcaWhirlpoolProof) -> tuple[bool, tuple[str, ...]]:
    """Validate source/account/quote/instruction evidence without enabling execution."""
    blockers: list[str] = []
    if proof.source_commit != ORCA_REVIEWED_SOURCE_COMMIT:
        blockers.append("ORCA_SOURCE_COMMIT_NOT_REVIEWED_GENERATION")
    if proof.license_class != ORCA_LICENSE_CLASS:
        blockers.append("ORCA_LICENSE_CLASS_MISMATCH")
    if not proof.license_review_approved:
        blockers.append("ORCA_COMMERCIAL_LICENSE_REVIEW_REQUIRED")
    if proof.local_quote_out != proof.reference_quote_out:
        blockers.append("ORCA_LOCAL_REFERENCE_QUOTE_MISMATCH")
    if proof.minimum_out > min(proof.local_quote_out, proof.reference_quote_out):
        blockers.append("ORCA_MIN_OUT_EXCEEDS_QUALIFIED_OUTPUT")
    rooted = (proof.pool, proof.vault_a, proof.vault_b, *proof.tick_arrays)
    program_owned = proof.tick_arrays + (proof.pool,)
    if any(item.owner != proof.program_id for item in program_owned):
        blockers.append("ORCA_PROGRAM_ACCOUNT_OWNER_MISMATCH")
    if any(item.root_slot != proof.pool.root_slot for item in rooted):
        blockers.append("ORCA_ROOT_SLOT_MISMATCH")
    if any(item.generation != proof.evidence_generation for item in rooted):
        blockers.append("ORCA_ACCOUNT_GENERATION_MISMATCH")
    if (
        _instruction_accounts_digest(proof.instruction_accounts)
        != proof.expected_instruction_accounts_sha256
    ):
        blockers.append("ORCA_INSTRUCTION_ACCOUNT_VECTOR_MISMATCH")
    if any(
        account.signer and account.role not in {"token_authority"}
        for account in proof.instruction_accounts
    ):
        blockers.append("ORCA_UNEXPECTED_SIGNER")
    if (
        proof.token_a.unsupported_extensions_present
        or proof.token_b.unsupported_extensions_present
    ):
        blockers.append("ORCA_UNSUPPORTED_TOKEN_EXTENSION")
    return (not blockers, tuple(dict.fromkeys(blockers)))


def qualify_route(
    legs: Sequence[DirectRouteLeg],
    registry: VenueCapabilityRegistry,
    *,
    mode: RouteMode,
    now_unix: int,
    allowed_combinations: frozenset[tuple[VenueFamily, ...]],
) -> RouteQualification:
    """Check exact per-leg capabilities and conservation; never compiles or sends."""
    blockers: list[str] = []
    if not legs:
        blockers.append("ROUTE_EMPTY")
    venues = tuple(leg.venue for leg in legs)
    if venues not in allowed_combinations:
        blockers.append("ROUTE_COMBINATION_NOT_QUALIFIED")

    capability_hashes: list[str] = []
    for index, leg in enumerate(legs):
        try:
            capability = registry.require_for_mode(
                leg.capability_hash, mode, now_unix=now_unix
            )
        except DirectVenueError as exc:
            blockers.append(f"LEG_{index}_CAPABILITY:{exc}")
            continue
        capability_hashes.append(capability.capability_hash)
        if capability.venue is not leg.venue:
            blockers.append(f"LEG_{index}_VENUE_MISMATCH")
        if capability.pool_or_market != leg.pool_or_market:
            blockers.append(f"LEG_{index}_POOL_MISMATCH")
        if (
            capability.input_mint != leg.input_mint
            or capability.output_mint != leg.output_mint
        ):
            blockers.append(f"LEG_{index}_DIRECTION_MISMATCH")
        if capability.instruction_data_sha256 != leg.instruction_data_sha256:
            blockers.append(f"LEG_{index}_INSTRUCTION_DATA_MISMATCH")
        if capability.instruction_accounts_sha256 != leg.instruction_accounts_sha256:
            blockers.append(f"LEG_{index}_INSTRUCTION_ACCOUNTS_MISMATCH")
        if capability.deployment_generation != leg.evidence_generation:
            blockers.append(f"LEG_{index}_GENERATION_MISMATCH")

    for index, (left, right) in enumerate(zip(legs, legs[1:])):
        if left.output_mint != right.input_mint:
            blockers.append(f"LEG_{index}_ASSET_CONTINUITY_BROKEN")
        if right.amount_in > left.guaranteed_min_out:
            blockers.append(f"LEG_{index}_OUTPUT_DOES_NOT_BACK_NEXT_INPUT")

    unique = tuple(dict.fromkeys(blockers))
    route_hash = hashlib.sha256(
        _stable_json(
            {"mode": mode.value, "legs": [_jsonable(item) for item in legs]}
        ).encode()
    ).hexdigest()
    return RouteQualification(
        accepted=not unique,
        mode=mode,
        blockers=unique,
        capability_hashes=tuple(capability_hashes),
        route_hash=route_hash,
        live_enabled=False,
    )


def build_orca_capability(
    proof: OrcaWhirlpoolProof,
    *,
    input_is_a: bool,
    genesis_sha256: str,
    expires_at_unix: int,
) -> VenueCapability:
    """Materialize OFFLINE_VERIFIED only after strict offline proof passes."""
    ok, blockers = qualify_orca_offline(proof)
    if not ok:
        raise DirectVenueError(
            "orca offline qualification blocked: " + ",".join(blockers)
        )
    token_in = proof.token_a if input_is_a else proof.token_b
    token_out = proof.token_b if input_is_a else proof.token_a
    evidence_sha = hashlib.sha256(
        _stable_json(_jsonable(proof)).encode()
    ).hexdigest()
    return VenueCapability(
        capability_id=f"orca:{proof.pool.address}:{token_in.mint}->{token_out.mint}",
        venue=VenueFamily.ORCA_WHIRLPOOLS,
        cluster="mainnet-beta",
        genesis_sha256=genesis_sha256,
        pool_or_market=proof.pool.address,
        input_mint=token_in.mint,
        output_mint=token_out.mint,
        deployment_generation=f"{proof.program_id}@{proof.source_commit}",
        account_layout_version=proof.evidence_generation,
        instruction_family="whirlpool-swap-exact-in",
        quote_math_version=proof.quote_math_version,
        evidence_sha256=evidence_sha,
        instruction_data_sha256=proof.instruction_data_sha256,
        instruction_accounts_sha256=proof.expected_instruction_accounts_sha256,
        state=CapabilityState.OFFLINE_VERIFIED,
        expires_at_unix=expires_at_unix,
    )


def _instruction_accounts_digest(accounts: Sequence[InstructionAccount]) -> str:
    return hashlib.sha256(
        _stable_json([_jsonable(item) for item in accounts]).encode()
    ).hexdigest()


def _jsonable(value: object) -> object:
    if is_dataclass(value):
        return {
            item.name: _jsonable(getattr(value, item.name)) for item in fields(value)
        }
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _digest(value: object) -> str:
    return hashlib.sha256(_stable_json(_jsonable(value)).encode()).hexdigest()


def _stable_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def _text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise DirectVenueError(f"{field} is required")


def _pubkey(value: str, field: str) -> None:
    if not isinstance(value, str) or not _B58.fullmatch(value):
        raise DirectVenueError(f"{field} must be a Solana public key")


def _sha256(value: str, field: str) -> None:
    if (
        not isinstance(value, str)
        or not _SHA256.fullmatch(value.lower())
        or value == "0" * 64
    ):
        raise DirectVenueError(f"{field} must be a non-placeholder sha256")


def _git_sha(value: str, field: str) -> None:
    if (
        not isinstance(value, str)
        or not _GIT_SHA.fullmatch(value.lower())
        or value == "0" * 40
    ):
        raise DirectVenueError(f"{field} must be a non-placeholder git sha")


def _positive_int(value: int, field: str, *, allow_zero: bool = False) -> None:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        kind = "non-negative" if allow_zero else "positive"
        raise DirectVenueError(f"{field} must be {kind} integer")


__all__ = [
    "CapabilityState",
    "DirectRouteLeg",
    "DirectVenueError",
    "InstructionAccount",
    "MPR2617_SCHEMA",
    "ORCA_LICENSE_CLASS",
    "ORCA_REVIEWED_SOURCE_COMMIT",
    "ORCA_SOURCE_REPOSITORY",
    "ORCA_WHIRLPOOLS_PROGRAM_ID",
    "OrcaWhirlpoolProof",
    "RootedAccountEvidence",
    "RouteMode",
    "RouteQualification",
    "TokenIdentity",
    "VenueCapability",
    "VenueCapabilityRegistry",
    "VenueFamily",
    "build_orca_capability",
    "qualify_orca_offline",
    "qualify_route",
]
