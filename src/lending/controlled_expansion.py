"""MPR-2615 controlled multi-lender expansion contracts.

This module is sender-free.  It does not discover accounts, sign, submit, or
promote a lender from mutable flags.  It turns exact lender/evidence identities
into deterministic admission and selection decisions while reusing the existing
runtime/router/compiler/simulation/capital/signer/ledger owners.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from importlib import resources
import json
import re
from typing import Any, Mapping, Sequence

EXPANSION_SCHEMA = "mpr2615.controlled-lender-expansion.v1"
FIRST_V1_PROFILE = "circular_arbitrage+marginfi+jupiter"
KAMINO_V1_PROFILE = "circular_arbitrage+kamino-klend+jupiter"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_WILDCARDS = frozenset({"*", "all", "all_markets", "all_reserves", "any"})


class ExpansionError(ValueError):
    """Raised when a lender capability or candidate fails closed."""


class LenderCapabilityStatus(StrEnum):
    UNSUPPORTED = "unsupported"
    RESEARCH = "research"
    IMPLEMENTED = "implemented"
    VERIFIED_OFFLINE = "verified_offline"
    SHADOW_QUALIFIED = "shadow_qualified"
    CANARY_ELIGIBLE = "canary_eligible"
    PRODUCTION_QUALIFIED = "production_qualified"
    REVOKED = "revoked"


_EXECUTABLE = frozenset({LenderCapabilityStatus.PRODUCTION_QUALIFIED})


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExpansionError(f"{field} must be non-empty text")
    normalized = value.strip()
    if normalized.lower() in _WILDCARDS:
        raise ExpansionError(f"{field} wildcard is forbidden")
    return normalized


def _int(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ExpansionError(f"{field} must be an integer >= {minimum}")
    return value


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ExpansionError(f"{field} must be a lowercase sha256 digest")
    return value


def _tuple_text(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ExpansionError(f"{field} must be a non-empty list")
    result = tuple(_text(item, field) for item in value)
    if len(result) != len(set(result)):
        raise ExpansionError(f"{field} must not contain duplicates")
    return result


@dataclass(frozen=True, slots=True)
class ExpansionEvidenceBinding:
    release_sha256: str
    config_sha256: str
    protocol_sha256: str
    deployment_generation: str
    evidence_sha256: str
    observed_slot: int
    expires_at_slot: int

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ExpansionEvidenceBinding":
        value = cls(
            release_sha256=_hash(raw.get("release_sha256"), "release_sha256"),
            config_sha256=_hash(raw.get("config_sha256"), "config_sha256"),
            protocol_sha256=_hash(raw.get("protocol_sha256"), "protocol_sha256"),
            deployment_generation=_text(
                raw.get("deployment_generation"), "deployment_generation"
            ),
            evidence_sha256=_hash(raw.get("evidence_sha256"), "evidence_sha256"),
            observed_slot=_int(raw.get("observed_slot"), "observed_slot", minimum=1),
            expires_at_slot=_int(
                raw.get("expires_at_slot"), "expires_at_slot", minimum=1
            ),
        )
        if value.expires_at_slot < value.observed_slot:
            raise ExpansionError("evidence expiry precedes observation")
        return value

    def current(self, *, current_slot: int) -> bool:
        slot = _int(current_slot, "current_slot")
        return self.observed_slot <= slot < self.expires_at_slot


@dataclass(frozen=True, slots=True)
class LenderCombinationIdentity:
    protocol: str
    cluster: str
    genesis_hash: str
    program_id: str
    market: str
    reserve: str
    mint: str
    token_program: str
    liquidity_supply: str
    oracle_accounts: tuple[str, ...]
    flash_borrow_family: str
    flash_repay_family: str
    generation: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "LenderCombinationIdentity":
        return cls(
            protocol=_text(raw.get("protocol"), "protocol"),
            cluster=_text(raw.get("cluster"), "cluster"),
            genesis_hash=_text(raw.get("genesis_hash"), "genesis_hash"),
            program_id=_text(raw.get("program_id"), "program_id"),
            market=_text(raw.get("market"), "market"),
            reserve=_text(raw.get("reserve"), "reserve"),
            mint=_text(raw.get("mint"), "mint"),
            token_program=_text(raw.get("token_program"), "token_program"),
            liquidity_supply=_text(raw.get("liquidity_supply"), "liquidity_supply"),
            oracle_accounts=_tuple_text(raw.get("oracle_accounts"), "oracle_accounts"),
            flash_borrow_family=_text(
                raw.get("flash_borrow_family"), "flash_borrow_family"
            ),
            flash_repay_family=_text(
                raw.get("flash_repay_family"), "flash_repay_family"
            ),
            generation=_text(raw.get("generation"), "generation"),
        )

    @property
    def digest(self) -> str:
        return sha256(
            json.dumps(
                {
                    "protocol": self.protocol,
                    "cluster": self.cluster,
                    "genesis_hash": self.genesis_hash,
                    "program_id": self.program_id,
                    "market": self.market,
                    "reserve": self.reserve,
                    "mint": self.mint,
                    "token_program": self.token_program,
                    "liquidity_supply": self.liquidity_supply,
                    "oracle_accounts": list(self.oracle_accounts),
                    "flash_borrow_family": self.flash_borrow_family,
                    "flash_repay_family": self.flash_repay_family,
                    "generation": self.generation,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class LenderCapability:
    capability_id: str
    profile: str
    status: LenderCapabilityStatus
    blockers: tuple[str, ...]
    combination_ids: tuple[str, ...]
    pool_scope: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "LenderCapability":
        try:
            status = LenderCapabilityStatus(str(raw.get("status")))
        except ValueError as exc:
            raise ExpansionError("unknown lender capability status") from exc
        blockers_raw = raw.get("blockers", [])
        combos_raw = raw.get("combination_ids", [])
        if not isinstance(blockers_raw, list) or any(
            not isinstance(item, str) or not item for item in blockers_raw
        ):
            raise ExpansionError("blockers must be a text list")
        if not isinstance(combos_raw, list) or any(
            not isinstance(item, str) or not item for item in combos_raw
        ):
            raise ExpansionError("combination_ids must be a text list")
        if any(item.lower() in _WILDCARDS for item in combos_raw):
            raise ExpansionError("wildcard combination ids are forbidden")
        return cls(
            capability_id=_text(raw.get("capability_id"), "capability_id"),
            profile=_text(raw.get("profile"), "profile"),
            status=status,
            blockers=tuple(dict.fromkeys(blockers_raw)),
            combination_ids=tuple(combos_raw),
            pool_scope=(
                _text(raw.get("pool_scope"), "pool_scope")
                if raw.get("pool_scope") is not None
                else None
            ),
        )

    @property
    def executable(self) -> bool:
        return (
            self.status in _EXECUTABLE
            and not self.blockers
            and bool(self.combination_ids)
        )


@dataclass(frozen=True, slots=True)
class ControlledLenderExpansionRegistry:
    first_v1_profile: str
    predecessor_2614: str
    capabilities: tuple[LenderCapability, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ControlledLenderExpansionRegistry":
        extension = raw.get("mpr2615")
        if not isinstance(extension, Mapping):
            raise ExpansionError("mpr2615 expansion metadata is missing")
        if extension.get("schema_version") != EXPANSION_SCHEMA:
            raise ExpansionError("unsupported MPR-2615 expansion schema")
        if extension.get("scope_status") != "NEW_PROPOSED_EXTENSION":
            raise ExpansionError("MPR-2615 must remain NEW_PROPOSED_EXTENSION")
        first = _text(extension.get("first_v1_profile"), "first_v1_profile")
        if first != FIRST_V1_PROFILE:
            raise ExpansionError("first v1 MarginFi/Jupiter profile was mutated")
        predecessor = _text(extension.get("predecessor_2614"), "predecessor_2614")
        capabilities_raw = extension.get("capabilities")
        if not isinstance(capabilities_raw, list) or not capabilities_raw:
            raise ExpansionError("expansion capabilities must be a non-empty list")
        capabilities = tuple(
            LenderCapability.from_mapping(item)
            for item in capabilities_raw
            if isinstance(item, Mapping)
        )
        if len(capabilities) != len(capabilities_raw):
            raise ExpansionError("every capability must be an object")
        ids = [item.capability_id for item in capabilities]
        if len(ids) != len(set(ids)):
            raise ExpansionError("duplicate capability id")
        return cls(first, predecessor, capabilities)

    @classmethod
    def packaged(cls) -> "ControlledLenderExpansionRegistry":
        resource = resources.files("src.resources").joinpath(
            "kamino_supported_combinations.json"
        )
        payload = json.loads(resource.read_text(encoding="utf-8"))
        return cls.from_mapping(payload)

    def require(self, capability_id: str) -> LenderCapability:
        for capability in self.capabilities:
            if capability.capability_id == capability_id:
                return capability
        raise ExpansionError(f"unknown lender capability: {capability_id}")

    def require_executable(self, capability_id: str) -> LenderCapability:
        capability = self.require(capability_id)
        if not capability.executable:
            raise ExpansionError(
                f"lender capability is not production-qualified: {capability_id}"
            )
        return capability


@dataclass(frozen=True, slots=True)
class LenderFeeObligation:
    principal_atomic: int
    repayment_atomic: int
    protocol_fee_atomic: int
    wallet_cost_atomic: int

    def __post_init__(self) -> None:
        principal = _int(self.principal_atomic, "principal_atomic", minimum=1)
        repayment = _int(self.repayment_atomic, "repayment_atomic", minimum=principal)
        protocol_fee = _int(self.protocol_fee_atomic, "protocol_fee_atomic")
        wallet_cost = _int(self.wallet_cost_atomic, "wallet_cost_atomic")
        if repayment - principal != protocol_fee:
            raise ExpansionError("repayment/protocol fee arithmetic mismatch")
        if wallet_cost < protocol_fee:
            raise ExpansionError("wallet cost cannot omit the lender protocol fee")


@dataclass(frozen=True, slots=True)
class ExpansionCandidateIdentity:
    candidate_id: str
    capability_id: str
    combination_id: str
    combination_digest: str
    message_sha256: str
    simulation_sha256: str

    def __post_init__(self) -> None:
        _text(self.candidate_id, "candidate_id")
        _text(self.capability_id, "capability_id")
        _text(self.combination_id, "combination_id")
        _hash(self.combination_digest, "combination_digest")
        _hash(self.message_sha256, "message_sha256")
        _hash(self.simulation_sha256, "simulation_sha256")

    @property
    def semantic_digest(self) -> str:
        return sha256(
            "|".join(
                (
                    self.candidate_id,
                    self.capability_id,
                    self.combination_id,
                    self.combination_digest,
                    self.message_sha256,
                    self.simulation_sha256,
                )
            ).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class QualifiedLenderCandidate:
    identity: ExpansionCandidateIdentity
    capability: LenderCapability
    gross_edge_atomic: int
    obligation: LenderFeeObligation
    repayment_proven: bool
    simulation_message_sha256: str
    effect_issued: bool = False

    def __post_init__(self) -> None:
        _int(self.gross_edge_atomic, "gross_edge_atomic")
        _hash(self.simulation_message_sha256, "simulation_message_sha256")
        if self.capability.capability_id != self.identity.capability_id:
            raise ExpansionError("candidate capability identity mismatch")
        if self.identity.combination_id not in self.capability.combination_ids:
            raise ExpansionError("candidate combination is not in capability scope")

    @property
    def net_edge_atomic(self) -> int:
        return self.gross_edge_atomic - self.obligation.wallet_cost_atomic

    @property
    def selectable(self) -> bool:
        return (
            self.capability.executable
            and self.repayment_proven is True
            and self.simulation_message_sha256 == self.identity.message_sha256
            and not self.effect_issued
        )


def select_best_qualified_lender(
    candidates: Sequence[QualifiedLenderCandidate],
) -> QualifiedLenderCandidate:
    selectable = [candidate for candidate in candidates if candidate.selectable]
    if not selectable:
        raise ExpansionError("no independently qualified lender candidate is selectable")
    return sorted(
        selectable,
        key=lambda item: (-item.net_edge_atomic, item.identity.semantic_digest),
    )[0]


def require_fresh_fallback_identity(
    previous: QualifiedLenderCandidate,
    replacement: QualifiedLenderCandidate,
) -> None:
    if previous.effect_issued:
        raise ExpansionError("cross-lender fallback is forbidden after effect issuance")
    if previous.identity.semantic_digest == replacement.identity.semantic_digest:
        raise ExpansionError("fallback must create a fresh candidate identity")
    if previous.identity.capability_id == replacement.identity.capability_id and (
        previous.identity.combination_id == replacement.identity.combination_id
    ):
        raise ExpansionError("fallback must not mutate the same semantic lender candidate")
