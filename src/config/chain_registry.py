"""Canonical Solana address registry used by the supported runtime.

The built-in entries in ``src/resources/chain_registry.json`` are limited to
stable platform programs/mints. External protocol deployments such as MarginFi
must be supplied by typed configuration until PR-027 pins their provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX = {character: index for index, character in enumerate(BASE58_ALPHABET)}

SYSTEM_PROGRAM_ADDRESS = "11111111111111111111111111111111"
TOKEN_PROGRAM_ADDRESS = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ADDRESS = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ASSOCIATED_TOKEN_PROGRAM_ADDRESS = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
COMPUTE_BUDGET_PROGRAM_ADDRESS = "ComputeBudget111111111111111111111111111111"
NATIVE_SOL_MINT_ADDRESS = "So11111111111111111111111111111111111111112"
BPF_UPGRADEABLE_LOADER_ADDRESS = "BPFLoaderUpgradeab1e11111111111111111111111"


class ChainRegistryError(ValueError):
    """Raised when a registry entry is malformed or internally inconsistent."""


def decode_base58(value: str) -> bytes:
    """Decode base58 without pulling configuration validation into SDK imports."""
    if not isinstance(value, str) or not value:
        raise ChainRegistryError("Solana address must be a non-empty string")
    number = 0
    for character in value:
        try:
            digit = _BASE58_INDEX[character]
        except KeyError as exc:
            raise ChainRegistryError(
                f"Solana address contains a non-base58 character: {character!r}"
            ) from exc
        number = number * 58 + digit
    decoded = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    leading_zeroes = len(value) - len(value.lstrip("1"))
    return b"\x00" * leading_zeroes + decoded


def validate_pubkey(value: str, *, field: str = "address") -> str:
    decoded = decode_base58(value)
    if len(decoded) != 32:
        raise ChainRegistryError(
            f"{field} must decode to exactly 32 bytes, got {len(decoded)}"
        )
    return value


def validate_genesis_hash(value: str, *, field: str = "genesis_hash") -> str:
    decoded = decode_base58(value)
    if not 16 <= len(decoded) <= 64:
        raise ChainRegistryError(
            f"{field} must be a plausible base58 cluster identity, got {len(decoded)} bytes"
        )
    return value


@dataclass(frozen=True, slots=True)
class ChainEntry:
    id: str
    kind: str
    address: str
    clusters: tuple[str, ...]
    owner: str | None
    source: str
    immutable: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ChainEntry":
        required = {"id", "kind", "address", "clusters", "source", "immutable"}
        missing = required.difference(value)
        if missing:
            raise ChainRegistryError(f"registry entry missing keys: {sorted(missing)}")
        unknown = set(value).difference(required | {"owner"})
        if unknown:
            raise ChainRegistryError(
                f"registry entry has unknown keys: {sorted(unknown)}"
            )
        address = validate_pubkey(str(value["address"]), field=f"{value['id']}.address")
        owner_raw = value.get("owner")
        owner = (
            None
            if owner_raw in (None, "")
            else validate_pubkey(str(owner_raw), field=f"{value['id']}.owner")
        )
        clusters = tuple(str(item) for item in value["clusters"])
        if not clusters:
            raise ChainRegistryError(f"{value['id']}.clusters cannot be empty")
        return cls(
            id=str(value["id"]),
            kind=str(value["kind"]),
            address=address,
            clusters=clusters,
            owner=owner,
            source=str(value["source"]),
            immutable=bool(value["immutable"]),
        )


@dataclass(frozen=True, slots=True)
class DynamicChainEntry:
    id: str
    kind: str
    config_path: str
    clusters: tuple[str, ...]
    owner: str | None
    source: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DynamicChainEntry":
        required = {"id", "kind", "config_path", "clusters", "source"}
        missing = required.difference(value)
        if missing:
            raise ChainRegistryError(
                f"dynamic registry entry missing keys: {sorted(missing)}"
            )
        unknown = set(value).difference(required | {"owner"})
        if unknown:
            raise ChainRegistryError(
                f"dynamic registry entry has unknown keys: {sorted(unknown)}"
            )
        owner_raw = value.get("owner")
        owner = (
            None
            if owner_raw in (None, "")
            else validate_pubkey(str(owner_raw), field=f"{value['id']}.owner")
        )
        return cls(
            id=str(value["id"]),
            kind=str(value["kind"]),
            config_path=str(value["config_path"]),
            clusters=tuple(str(item) for item in value["clusters"]),
            owner=owner,
            source=str(value["source"]),
        )


@dataclass(frozen=True, slots=True)
class ChainRegistry:
    schema_version: str
    canonical_genesis_hashes: Mapping[str, str]
    entries: tuple[ChainEntry, ...]
    dynamic_entries: tuple[DynamicChainEntry, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ChainRegistry":
        expected = {
            "schema_version",
            "canonical_genesis_hashes",
            "entries",
            "dynamic_entries",
        }
        unknown = set(payload).difference(expected)
        missing = expected.difference(payload)
        if missing or unknown:
            raise ChainRegistryError(
                f"registry root mismatch; missing={sorted(missing)} unknown={sorted(unknown)}"
            )
        entries = tuple(ChainEntry.from_mapping(item) for item in payload["entries"])
        dynamic = tuple(
            DynamicChainEntry.from_mapping(item) for item in payload["dynamic_entries"]
        )
        ids = [entry.id for entry in entries] + [entry.id for entry in dynamic]
        if len(ids) != len(set(ids)):
            raise ChainRegistryError("registry entry IDs must be unique")
        addresses = [entry.address for entry in entries]
        if len(addresses) != len(set(addresses)):
            raise ChainRegistryError("canonical registry addresses must be unique")
        genesis_hashes = {
            str(cluster): validate_genesis_hash(str(value), field=f"genesis.{cluster}")
            for cluster, value in payload["canonical_genesis_hashes"].items()
        }
        return cls(
            schema_version=str(payload["schema_version"]),
            canonical_genesis_hashes=genesis_hashes,
            entries=entries,
            dynamic_entries=dynamic,
        )

    @classmethod
    def load_default(cls) -> "ChainRegistry":
        resource = resources.files("src.resources").joinpath("chain_registry.json")
        payload = json.loads(resource.read_text(encoding="utf-8"))
        return cls.from_mapping(payload)

    @classmethod
    def load(cls, path: str | Path) -> "ChainRegistry":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_mapping(payload)

    def entry(self, entry_id: str) -> ChainEntry:
        for entry in self.entries:
            if entry.id == entry_id:
                return entry
        raise ChainRegistryError(f"unknown canonical registry entry: {entry_id}")

    def by_address(self, address: str) -> ChainEntry | None:
        return next((entry for entry in self.entries if entry.address == address), None)

    def validate_cluster(self, cluster: str, genesis_hash: str | None) -> None:
        expected = self.canonical_genesis_hashes.get(cluster)
        if expected is None:
            if genesis_hash:
                validate_genesis_hash(genesis_hash, field="cluster.genesis_hash")
            return
        if genesis_hash != expected:
            raise ChainRegistryError(
                f"cluster genesis mismatch for {cluster}: expected {expected}, got {genesis_hash}"
            )

    def validate_allowlisted_programs(
        self,
        addresses: Iterable[str],
        *,
        cluster: str,
        additional_addresses: Iterable[str] = (),
    ) -> None:
        additional = {
            validate_pubkey(item, field="allowlist.program")
            for item in additional_addresses
        }
        canonical = {
            entry.address
            for entry in self.entries
            if entry.kind == "program" and cluster in entry.clusters
        }
        for address in addresses:
            validate_pubkey(address, field="allowlist.program")
            if address not in canonical and address not in additional:
                raise ChainRegistryError(
                    f"program {address} is not registered for cluster {cluster}"
                )
