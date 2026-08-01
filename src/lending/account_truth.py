"""Fail-closed local token, ALT and route decoding contracts for PR-005."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable

TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
NATIVE_SOL = "11111111111111111111111111111111"
WSOL_MINT = "So11111111111111111111111111111111111111112"
ALT_PROGRAM = "AddressLookupTab1e1111111111111111111111111"
U64_MAX = 2**64 - 1


class AccountTruthError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TokenMintEvidence:
    mint: str
    owner: str
    decimals: int
    executable: bool
    extensions: tuple[str, ...] = ()
    freeze_authority: str | None = None
    close_authority: str | None = None


def validate_mint(
    value: TokenMintEvidence, *, allowed_extensions: Iterable[str] = ()
) -> None:
    _pubkey(value.mint)
    if value.mint == NATIVE_SOL:
        raise AccountTruthError("native SOL sentinel is not a token mint")
    if value.owner not in {TOKEN_PROGRAM, TOKEN_2022_PROGRAM}:
        raise AccountTruthError("wrong token program")
    if value.executable:
        raise AccountTruthError("mint account must not be executable")
    if type(value.decimals) is not int or not 0 <= value.decimals <= 255:
        raise AccountTruthError("invalid decimals")
    extensions = set(value.extensions)
    if value.owner == TOKEN_PROGRAM and extensions:
        raise AccountTruthError("legacy SPL mint cannot carry Token-2022 extensions")
    unsupported = extensions.difference(allowed_extensions)
    if unsupported:
        raise AccountTruthError(
            f"unsupported Token-2022 extensions: {sorted(unsupported)}"
        )


def validate_route_amount(value: object) -> int:
    if type(value) is not int or not 0 < value <= U64_MAX:
        raise AccountTruthError("amount must be a positive u64 integer")
    return value


@dataclass(frozen=True, slots=True)
class AltEvidence:
    owner: str
    authority: str | None
    deactivation_slot: int
    addresses: tuple[str, ...]
    slot: int
    rooted_slot: int

    def validate(self, indexes: Iterable[int], *, allowed_authority: str | None) -> str:
        if self.owner != ALT_PROGRAM or self.authority != allowed_authority:
            raise AccountTruthError("ALT owner/authority policy mismatch")
        if self.deactivation_slot <= self.rooted_slot or self.slot > self.rooted_slot:
            raise AccountTruthError("ALT is inactive or unrooted")
        for address in self.addresses:
            _pubkey(address)
        for index in indexes:
            if type(index) is not int or not 0 <= index < len(self.addresses):
                raise AccountTruthError("ALT index out of bounds")
        return sha256(b"\0".join(x.encode() for x in self.addresses)).hexdigest()


def _pubkey(value: str) -> None:
    # Strict alphabet/length validation without accepting user-controlled delimiters.
    alphabet = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
    if (
        not isinstance(value, str)
        or not 32 <= len(value) <= 44
        or set(value) - alphabet
    ):
        raise AccountTruthError("malformed pubkey")
