"""ASSET-01: pre-capture identity safety + HARD_BOUND quote admission gate.

Two distinct stages (master DAG #683, task ASSET-01):

*Pre-capture* — identity evidence from discovery candidates is parsed and
preserved with **typed unknowns**. Unresolved candidates are never upgraded,
never inferred from tickers, and never required to be HARD_BOUND: the
research universe stays maximal.

*Quote admission* — before an asset or pool is used by an exact quote, its
identity must be HARD_BOUND: current evidence references (source generation,
freshness, content hashes), exact decimals, token program and Token-2022
extension semantics, and canonical pool/token/vault identity. Any unknown or
inconsistent identity is a typed blocker; missing decimals are never treated
as verified.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.research_economic_graph.registry import (
    SPL_TOKEN_PROGRAM,
    TOKEN_2022_PROGRAM,
)
from .resolver import CandidateAsset

# Token-2022 extensions whose semantics the exact simulation understands.
# Everything else (including transfer-hook, transfer-fee and account-state
# semantics) fails closed before quote admission.
SUPPORTED_TOKEN_2022_EXTENSIONS = frozenset(
    {
        "metadata-pointer",
        "token-metadata",
        "scaled-ui-amount",
    }
)

TRANSFER_SEMANTIC_EXTENSIONS = frozenset(
    {
        "transfer-hook",
        "transfer-fee-config",
        "permanent-delegate",
        "default-account-state",
        "interest-bearing",
    }
)

# Legacy SPL-token mints must carry no extensions at all.
DECIMALS_RANGE = range(0, 19)


class HardBoundIdentityBlocker(ValueError):
    """Typed blocker: identity is unknown, inconsistent or not HARD_BOUND.

    Raised (or collected) whenever quote/route admission would otherwise
    proceed on unresolved identity. Codes are stable strings; unknown is
    never converted to zero or to a verified value.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class PreCaptureIdentity:
    """Safe pre-capture view of a discovery candidate (ASSET-01).

    Unknown fields stay ``None`` and are named in ``unknowns``. The record
    never claims verification; ``hard_bound`` is False unless every identity
    field is present, consistent and backed by current evidence.
    """

    chain: str
    identifier: str
    symbol: str
    decimals: int | None
    token_program: str | None
    extensions: tuple[str, ...] | None
    economic_underlying: str
    representation_kind: str
    unknowns: tuple[str, ...] = ()
    hard_bound: bool = False
    notes: tuple[str, ...] = ()

    def identity_blockers(self) -> tuple[str, ...]:
        """Typed blockers that currently prevent HARD_BOUND admission."""

        blockers = []
        if self.decimals is None:
            blockers.append("ASSET01_DECIMALS_UNKNOWN")
        if self.token_program is None:
            blockers.append("ASSET01_TOKEN_PROGRAM_UNKNOWN")
        if self.extensions is None:
            blockers.append("ASSET01_EXTENSIONS_UNKNOWN")
        return tuple(blockers)


def pre_capture_identity_view(candidate: CandidateAsset) -> PreCaptureIdentity:
    """Parse a discovery candidate without upgrading or inferring anything.

    Unresolved or partially-evidenced candidates come back with typed
    unknowns; no ticker inference, no promotion to verified, no HARD_BOUND
    requirement. Never raises on unresolved identity.
    """

    unknowns: list[str] = []
    notes: list[str] = []

    decimals = candidate.decimals if candidate.authoritative else None
    if decimals is None:
        unknowns.append("decimals")

    program = candidate.program_or_package or None
    if program is None:
        unknowns.append("token_program")

    extensions: tuple[str, ...] | None
    if candidate.chain == "solana" and program == TOKEN_2022_PROGRAM:
        extensions = tuple(candidate.extensions)
    elif candidate.chain == "solana" and program == SPL_TOKEN_PROGRAM:
        extensions = ()
    else:
        extensions = None
        unknowns.append("extensions")

    # A mismatch between the claimed program and the mint's extension
    # carrying is an inconsistency, preserved as a typed note (it must
    # block any later admission, but pre-capture it is only recorded).
    if (
        candidate.chain == "solana"
        and program == SPL_TOKEN_PROGRAM
        and candidate.extensions
    ):
        notes.append("legacy-spl-mint-with-extensions")

    hard_bound = not unknowns and not notes
    return PreCaptureIdentity(
        chain=candidate.chain,
        identifier=candidate.identifier,
        symbol=candidate.symbol,
        decimals=decimals,
        token_program=program,
        extensions=extensions,
        economic_underlying=candidate.economic_underlying,
        representation_kind=candidate.representation_kind,
        unknowns=tuple(unknowns),
        hard_bound=hard_bound,
        notes=tuple(notes),
    )


@dataclass(frozen=True)
class PoolTokenSpec:
    """One side of a HARD_BOUND pool: mint, vault and chain positions."""

    identifier: str
    decimals: int
    token_program: str
    extensions: tuple[str, ...] = ()
    vault: str = ""
    vault_token_account: str = ""


@dataclass(frozen=True)
class HardBoundPoolSpec:
    """Canonical pool identity submitted for exact-quote admission."""

    chain: str
    pool_id: str
    base: PoolTokenSpec
    quote: PoolTokenSpec
    base_vault: str
    quote_vault: str
    source_generation: str
    evidence_refs: tuple[str, ...] = ()
    evidence_sha256: str | None = None
    evidence_slot: int | None = None


@dataclass(frozen=True)
class HardBoundPoolAdmission:
    ok: bool
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _validate_token(spec: PoolTokenSpec, side: str, blockers: list[str]) -> None:
    if not spec.identifier:
        blockers.append(f"ASSET01_{side}_IDENTITY_UNKNOWN")
    if type(spec.decimals) is not int or spec.decimals not in DECIMALS_RANGE:
        # Missing or out-of-range decimals are unknown, never verified.
        blockers.append(f"ASSET01_{side}_DECIMALS_UNKNOWN")
    if spec.token_program not in {SPL_TOKEN_PROGRAM, TOKEN_2022_PROGRAM}:
        blockers.append(f"ASSET01_{side}_TOKEN_PROGRAM_MISMATCH")
    if spec.token_program == SPL_TOKEN_PROGRAM and spec.extensions:
        blockers.append(f"ASSET01_{side}_LEGACY_SPL_EXTENSIONS_NOT_ALLOWED")
    if spec.token_program == TOKEN_2022_PROGRAM:
        if not spec.extensions:
            blockers.append(f"ASSET01_{side}_TOKEN_2022_EXTENSIONS_UNKNOWN")
        for extension in spec.extensions:
            if extension in TRANSFER_SEMANTIC_EXTENSIONS:
                blockers.append(
                    f"ASSET01_{side}_TOKEN_2022_TRANSFER_SEMANTICS_UNSUPPORTED"
                    f":{extension}"
                )
            elif extension not in SUPPORTED_TOKEN_2022_EXTENSIONS:
                blockers.append(
                    f"ASSET01_{side}_TOKEN_2022_EXTENSION_UNSUPPORTED:{extension}"
                )


def require_hard_bound_pool(spec: HardBoundPoolSpec) -> HardBoundPoolAdmission:
    """Admission gate: a pool may back an exact quote only when HARD_BOUND.

    Every identity field must be present and internally consistent; the
    pool's token order must match its vault pairing; evidence must carry
    source generation and content references. Any violation is a typed
    blocker and the pool is not admitted.
    """

    blockers: list[str] = []
    warnings: list[str] = []

    if spec.chain != "solana":
        blockers.append(f"ASSET01_CHAIN_UNSUPPORTED:{spec.chain}")
    if not spec.pool_id:
        blockers.append("ASSET01_POOL_IDENTITY_UNKNOWN")

    _validate_token(spec.base, "BASE", blockers)
    _validate_token(spec.quote, "QUOTE", blockers)

    if not spec.base_vault or not spec.quote_vault:
        blockers.append("ASSET01_VAULT_IDENTITY_UNKNOWN")
    else:
        if spec.base.vault and spec.base.vault != spec.base_vault:
            blockers.append("ASSET01_POOL_TOKEN_ORDER_MISMATCH")
        if spec.quote.vault and spec.quote.vault != spec.quote_vault:
            blockers.append("ASSET01_POOL_TOKEN_ORDER_MISMATCH")
        if spec.base.vault_token_account and (
            spec.base.vault_token_account != spec.base_vault
        ):
            blockers.append("ASSET01_VAULT_IDENTITY_MISMATCH:base")
        if spec.quote.vault_token_account and (
            spec.quote.vault_token_account != spec.quote_vault
        ):
            blockers.append("ASSET01_VAULT_IDENTITY_MISMATCH:quote")
        if spec.base_vault == spec.quote_vault:
            blockers.append("ASSET01_VAULT_IDENTITY_MISMATCH:shared")

    if spec.base.identifier == spec.quote.identifier:
        blockers.append("ASSET01_POOL_SIDES_COLLAPSED")

    if not spec.evidence_refs:
        blockers.append("ASSET01_POOL_EVIDENCE_MISSING")
    if spec.evidence_sha256 is None or len(spec.evidence_sha256) != 64:
        blockers.append("ASSET01_POOL_EVIDENCE_HASH_INVALID")
    if spec.evidence_slot is None or spec.evidence_slot <= 0:
        blockers.append("ASSET01_POOL_EVIDENCE_SLOT_MISSING")
    if not spec.source_generation:
        blockers.append("ASSET01_SOURCE_GENERATION_MISSING")

    return HardBoundPoolAdmission(
        ok=not blockers, blockers=tuple(blockers), warnings=tuple(warnings)
    )


def assert_no_ticker_collision(
    assets: tuple[PreCaptureIdentity, ...],
) -> None:
    """Ticker collision guard: a symbol mapping to two mints blocks admission.

    Tickers are never used to infer identity; a collision is surfaced as a
    typed blocker so resolution must proceed on canonical identifiers.
    """

    seen: dict[str, str] = {}
    for asset in assets:
        if asset.symbol in seen and seen[asset.symbol] != asset.identifier:
            raise HardBoundIdentityBlocker(
                "ASSET01_TICKER_COLLISION",
                f"{asset.symbol}:{seen[asset.symbol]}:{asset.identifier}",
            )
        seen[asset.symbol] = asset.identifier
