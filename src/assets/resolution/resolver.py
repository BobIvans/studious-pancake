"""Ticker is a query, never an identity. All bindings require current chain proof."""

from dataclasses import asdict, dataclass
from enum import StrEnum
import json
from pathlib import Path
import re
from typing import Protocol

from solders.pubkey import Pubkey

from src.asset_mint_registry_pr117 import (
    LEGACY_SPL_TOKEN_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
)
from .evidence import Evidence, EvidenceStore, digest, text


class BindingPolicy(StrEnum):
    HARD_BIND = "HARD_BIND"
    VERIFY_STARTUP = "VERIFY_STARTUP"
    RESOLVE_LIVE = "RESOLVE_LIVE"


class ResolutionState(StrEnum):
    UNRESOLVED = "UNRESOLVED"
    CANDIDATE = "CANDIDATE"
    AMBIGUOUS = "AMBIGUOUS"
    REJECTED = "REJECTED"
    IDENTIFIER_VERIFIED = "IDENTIFIER_VERIFIED"


def canonical_identifier(chain: str, identifier: str) -> str:
    text(identifier)
    if chain == "solana":
        return str(Pubkey.from_string(identifier))
    if chain == "sui":
        # Coin identity includes module/type; package-only and unverified generic
        # types are rejected. Case-sensitive Move identifiers are preserved.
        match = re.fullmatch(
            r"0x([0-9a-fA-F]{1,64})::([A-Za-z_][A-Za-z_0-9]*)::([A-Za-z_][A-Za-z_0-9]*)",
            identifier,
        )
        if not match:
            raise ValueError("full Move coin type required")
        return f"0x{int(match[1], 16):064x}::{match[2]}::{match[3]}"
    raise ValueError("unsupported identity chain; TON is research-only")


@dataclass(frozen=True)
class CandidateAsset:
    chain: str
    identifier: str
    symbol: str
    decimals: int
    program_or_package: str
    evidence: Evidence
    authoritative: bool
    economic_underlying: str = "unknown"
    representation_kind: str = "unknown"
    extensions: tuple[str, ...] = ()
    mint_authority: str | None = None
    freeze_authority: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "identifier", canonical_identifier(self.chain, self.identifier)
        )
        if type(self.decimals) is not int or not 0 <= self.decimals <= 18:
            raise ValueError("invalid decimals")
        text(self.symbol)
        text(self.program_or_package)
        if type(self.authoritative) is not bool:
            raise ValueError("authority must be explicit")


@dataclass(frozen=True)
class ChainAssetProof:
    chain: str
    identifier: str
    decimals: int
    program_or_package: str
    exists: bool
    evidence: Evidence
    extensions: tuple[str, ...] = ()
    mint_authority: str | None = None
    freeze_authority: str | None = None
    supply: int | None = None
    package_version: str | None = None


@dataclass(frozen=True)
class AssetIdentity:
    asset_id: str
    chain: str
    canonical_identifier: str
    symbol: str
    decimals: int
    program_or_package: str
    economic_underlying: str
    representation_kind: str
    resolver_generation: str
    evidence_refs: tuple[str, ...]
    identity_generation: str
    verification_state: ResolutionState = ResolutionState.IDENTIFIER_VERIFIED
    extensions: tuple[str, ...] = ()
    mint_authority: str | None = None
    freeze_authority: str | None = None
    historical_seed: str | None = None


@dataclass(frozen=True)
class AssetResolutionJob:
    chain: str
    query: str
    generation: str
    policy: BindingPolicy = BindingPolicy.RESOLVE_LIVE
    seed_identifier: str | None = None

    def __post_init__(self) -> None:
        text(self.query)
        text(self.generation)
        if self.policy != BindingPolicy.RESOLVE_LIVE and self.seed_identifier is None:
            raise ValueError("bootstrap policy requires a seed identifier")
        if self.seed_identifier is not None:
            object.__setattr__(
                self,
                "seed_identifier",
                canonical_identifier(self.chain, self.seed_identifier),
            )


@dataclass(frozen=True)
class AssetResolutionReceipt:
    job: AssetResolutionJob
    state: ResolutionState
    candidates: tuple[CandidateAsset, ...]
    identity: AssetIdentity | None
    reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]


class AssetResolver(Protocol):
    def discover(
        self, query: str, context: AssetResolutionJob
    ) -> tuple[CandidateAsset, ...]: ...
    def verify(
        self, candidate: CandidateAsset, chain_state: tuple[ChainAssetProof, ...]
    ) -> AssetResolutionReceipt: ...


def resolve(
    job: AssetResolutionJob,
    candidates: tuple[CandidateAsset, ...],
    proofs: tuple[ChainAssetProof, ...],
    *,
    now: float,
    max_age: float = 60,
    store: EvidenceStore | None = None,
) -> AssetResolutionReceipt:
    reasons: list[str] = []
    historical_disagreement = False
    relevant = tuple(c for c in candidates if c.chain == job.chain)
    fresh = tuple(
        c
        for c in relevant
        if c.authoritative
        and c.evidence.fresh(now=now, max_age=max_age, generation=job.generation)
    )
    ids = {c.identifier for c in fresh}
    identity = None
    if not ids:
        state = ResolutionState.UNRESOLVED
        reasons.append("no_current_authoritative_candidate")
    elif len(ids) != 1:
        state = ResolutionState.AMBIGUOUS
        reasons.append("multiple_plausible_identifiers")
    else:
        candidate = fresh[0]
        state = ResolutionState.REJECTED
        metadata = {
            (
                c.decimals,
                c.program_or_package,
                c.extensions,
                c.mint_authority,
                c.freeze_authority,
            )
            for c in fresh
        }
        if len(metadata) != 1:
            reasons.append("registry_disagreement")
        if (
            job.seed_identifier is not None
            and candidate.identifier != job.seed_identifier
        ):
            historical_disagreement = True
        current = tuple(
            p
            for p in proofs
            if p.chain == job.chain
            and canonical_identifier(p.chain, p.identifier) == candidate.identifier
            and p.evidence.fresh(now=now, max_age=max_age, generation=job.generation)
        )
        if not current:
            reasons.append("missing_current_chain_evidence")
        for proof in current:
            if proof.evidence.slot_or_checkpoint is None or not proof.exists:
                reasons.append("chain_existence_or_position_missing")
            if (
                (proof.decimals, proof.program_or_package)
                != (candidate.decimals, candidate.program_or_package)
                or candidate.extensions
                and tuple(proof.extensions) != candidate.extensions
                or candidate.mint_authority is not None
                and proof.mint_authority != candidate.mint_authority
                or candidate.freeze_authority is not None
                and proof.freeze_authority != candidate.freeze_authority
            ):
                reasons.append("chain_registry_semantics_mismatch")
            if job.chain == "solana":
                if (
                    proof.program_or_package
                    not in (LEGACY_SPL_TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID)
                    or type(proof.supply) is not int
                    or proof.supply < 0
                ):
                    reasons.append("invalid_solana_program_or_supply")
                if (
                    proof.program_or_package == LEGACY_SPL_TOKEN_PROGRAM_ID
                    and proof.extensions
                ):
                    reasons.append("legacy_token_has_extensions")
            elif (
                proof.program_or_package
                != "::".join(candidate.identifier.split("::")[:2])
                or not proof.package_version
            ):
                reasons.append("missing_move_package_version")
        if (
            len(
                {
                    digest(
                        {
                            "decimals": p.decimals,
                            "program": p.program_or_package,
                            "extensions": p.extensions,
                            "mint_authority": p.mint_authority,
                            "freeze_authority": p.freeze_authority,
                            "supply": p.supply,
                            "package_version": p.package_version,
                            "position": p.evidence.slot_or_checkpoint,
                        }
                    )
                    for p in current
                }
            )
            > 1
        ):
            reasons.append("chain_provider_disagreement")
        if not reasons:
            refs = tuple(
                sorted(
                    {digest(asdict(c.evidence)) for c in fresh}
                    | {digest(asdict(p.evidence)) for p in current}
                )
            )
            stable = digest({"chain": job.chain, "identifier": candidate.identifier})
            version = digest(
                {"asset": stable, "generation": job.generation, "evidence": refs}
            )
            identity = AssetIdentity(
                stable,
                job.chain,
                candidate.identifier,
                candidate.symbol,
                candidate.decimals,
                candidate.program_or_package,
                candidate.economic_underlying,
                candidate.representation_kind,
                job.generation,
                refs,
                version,
                extensions=tuple(current[0].extensions),
                mint_authority=current[0].mint_authority,
                freeze_authority=current[0].freeze_authority,
                historical_seed=(
                    job.seed_identifier if historical_disagreement else None
                ),
            )
            state = ResolutionState.IDENTIFIER_VERIFIED
        if historical_disagreement:
            reasons.append("historical_seed_disagreement_preserved")
    receipt = AssetResolutionReceipt(
        job,
        state,
        relevant,
        identity,
        tuple(sorted(set(reasons))),
        tuple(
            sorted(
                {digest(asdict(c.evidence)) for c in relevant}
                | {digest(asdict(p.evidence)) for p in proofs}
            )
        ),
    )
    if store is not None:
        payload = asdict(receipt)
        store.append(
            Evidence(
                "asset-resolution",
                "resolver-v1",
                "resolver",
                job.generation,
                now,
                digest(payload),
                digest(asdict(job)),
            ),
            payload,
        )
    return receipt


def bootstrap_jobs(repo_root: Path, generation: str) -> tuple[AssetResolutionJob, ...]:
    """Reuse PR117 seeds, then Part A (including every RESOLVE_LIVE job)."""
    rows = json.loads(
        (repo_root / "src/resources/asset_mint_registry_pr117.json").read_text()
    )["assets"]
    jobs = {
        ("solana", row["mint"]): AssetResolutionJob(
            "solana",
            row["symbol"],
            generation,
            BindingPolicy.VERIFY_STARTUP,
            row["mint"],
        )
        for row in rows
    }
    document = (
        (
            repo_root
            / "docs/roadmap/dynamic-universe-master-2026-10-07/CODEX_START_HERE.md"
        )
        .read_text()
        .split("# PART B")[0]
    )
    chain = "solana"
    for line in document.splitlines():
        if line.startswith("## 2. Sui"):
            chain = "sui"
        if line.startswith("## 4."):
            break  # mandatory queue duplicates the chain tables
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 5 or cells[2] not in set(BindingPolicy):
            continue
        symbol, identifier, policy, _, _ = cells
        if identifier.startswith("No SPL"):
            continue  # native SOL has no token-edge mint; WSOL is distinct
        seed = None if policy == BindingPolicy.RESOLVE_LIVE else identifier
        job = AssetResolutionJob(chain, symbol, generation, BindingPolicy(policy), seed)
        jobs[(chain, seed or symbol)] = job
    return tuple(jobs[key] for key in sorted(jobs))
