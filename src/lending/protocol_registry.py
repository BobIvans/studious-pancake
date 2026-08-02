"""PR-005 genesis-bound protocol evidence registry.

The registry is an offline admission authority, not a network client.  Missing
deployed evidence is represented by a blocker rather than guessed values.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping

from solders.pubkey import Pubkey


class ProtocolRegistryError(ValueError):
    pass


REQUIRED = frozenset(
    {
        "program_id",
        "loader_type",
        "programdata_account",
        "upgrade_authority",
        "idl_layout_version",
        "source_commit_build_hash",
        "identities",
        "mints",
        "token_program",
        "validity_generation",
        "expires_at_slot",
        "provenance",
        "human_review",
        "artifacts",
        "status",
        "blockers",
    }
)


@dataclass(frozen=True, slots=True)
class ProtocolQualification:
    name: str
    status: str
    blockers: tuple[str, ...]
    evidence_digest: str

    @property
    def executable(self) -> bool:
        return self.status == "supported" and not self.blockers


class GenesisBoundProtocolRegistry:
    def __init__(self, payload: Mapping[str, Any], *, root: Path) -> None:
        self._payload = payload
        self._root = root.resolve()
        if payload.get("schema_version") != "pr005.protocol-account-registry.v1":
            raise ProtocolRegistryError("unsupported registry schema")
        self.cluster = _text(payload.get("cluster"), "cluster")
        self.genesis_hash = _text(payload.get("genesis_hash"), "genesis_hash")
        identities = payload.get("platform_identities")
        required_identities = {
            "system_program",
            "spl_token_program",
            "token_2022_program",
            "wrapped_sol_mint",
            "address_lookup_table_program",
        }
        if not isinstance(identities, dict) or set(identities) != required_identities:
            raise ProtocolRegistryError("incomplete platform identity registry")
        self.platform_identities = {
            key: _pubkey(value, key) for key, value in identities.items()
        }
        protocols = payload.get("protocols")
        if not isinstance(protocols, dict) or not protocols:
            raise ProtocolRegistryError("protocol registry must not be empty")
        self.protocols = protocols

    @classmethod
    def packaged(cls) -> "GenesisBoundProtocolRegistry":
        path = (
            Path(__file__).parents[1]
            / "resources"
            / "contracts"
            / "protocol"
            / "protocol_account_registry.json"
        )
        return cls(json.loads(path.read_text(encoding="utf-8")), root=path.parent)

    def qualify(
        self, name: str, *, genesis_hash: str, current_slot: int
    ) -> ProtocolQualification:
        if genesis_hash != self.genesis_hash:
            raise ProtocolRegistryError("wrong cluster/genesis")
        raw = self.protocols.get(name)
        if not isinstance(raw, dict):
            raise ProtocolRegistryError("unknown protocol")
        missing = REQUIRED.difference(raw)
        if missing:
            raise ProtocolRegistryError(f"missing registry fields: {sorted(missing)}")
        blockers = list(_text_tuple(raw["blockers"], "blockers"))
        status = raw["status"]
        if status not in {"supported", "blocked", "fixture_only_blocked"}:
            raise ProtocolRegistryError("invalid capability status")
        if type(current_slot) is not int or current_slot < 0:
            raise ProtocolRegistryError("current_slot must be a non-negative integer")
        expiry = raw["expires_at_slot"]
        if type(expiry) is not int or expiry < current_slot:
            blockers.append("EVIDENCE_EXPIRED")
        artifacts = raw["artifacts"]
        if not isinstance(artifacts, list):
            raise ProtocolRegistryError("artifacts must be a list")
        material = []
        for item in artifacts:
            if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
                raise ProtocolRegistryError("malformed artifact descriptor")
            relative = _text(item["path"], "artifact path")
            path = (self._root / relative).resolve()
            if self._root not in path.parents or not path.is_file():
                blockers.append("MISSING_MATERIALIZED_ARTIFACT")
                continue
            actual = sha256(path.read_bytes()).hexdigest()
            if actual != item["sha256"]:
                blockers.append("ARTIFACT_DIGEST_MISMATCH")
            material.append((relative, actual))
        if status == "supported" and not material:
            blockers.append("JSON_DECLARATION_WITHOUT_MATERIALIZED_EVIDENCE")
        mandatory = (
            "program_id",
            "programdata_account",
            "idl_layout_version",
            "source_commit_build_hash",
        )
        if any(not raw[field] for field in mandatory):
            blockers.append("DEPLOYED_IDENTITY_EVIDENCE_MISSING")
        if status == "supported":
            blockers.extend(_supported_entry_blockers(raw))
        if type(raw["human_review"]) is not bool or raw["human_review"] is not True:
            blockers.append("HUMAN_REVIEW_MISSING")
        digest = sha256(
            json.dumps(
                {"entry": raw, "material": material},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        unique = tuple(sorted(set(blockers)))
        if status == "supported" and unique:
            status = "blocked"
        return ProtocolQualification(name, status, unique, digest)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProtocolRegistryError(f"{field} must be non-empty text")
    return value


def _text_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(x, str) or not x for x in value
    ):
        raise ProtocolRegistryError(f"{field} must be a text list")
    return tuple(value)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _pubkey(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ProtocolRegistryError(f"{field} must be a canonical base58 public key")
    try:
        Pubkey.from_string(value)
    except ValueError as exc:
        raise ProtocolRegistryError(
            f"{field} must be a canonical base58 public key"
        ) from exc
    return value


def _supported_entry_blockers(raw: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate every production-relevant field, never mere truthiness."""

    blockers: list[str] = []
    for field in ("program_id", "programdata_account"):
        try:
            _pubkey(raw.get(field), field)
        except ProtocolRegistryError:
            blockers.append(f"INVALID_{field.upper()}")
    if raw.get("loader_type") not in {
        "BPFLoaderUpgradeab1e11111111111111111111111",
        "BPFLoader2111111111111111111111111111111111",
    }:
        blockers.append("INVALID_LOADER_TYPE")
    authority = raw.get("upgrade_authority")
    if authority is not None:
        try:
            _pubkey(authority, "upgrade_authority")
        except ProtocolRegistryError:
            blockers.append("INVALID_UPGRADE_AUTHORITY")
    for field in ("idl_layout_version", "validity_generation", "provenance"):
        if not isinstance(raw.get(field), str) or not raw[field].strip():
            blockers.append(f"INVALID_{field.upper()}")
    if not isinstance(
        raw.get("source_commit_build_hash"), str
    ) or not _SHA256_RE.fullmatch(raw["source_commit_build_hash"]):
        blockers.append("INVALID_SOURCE_COMMIT_BUILD_HASH")
    if not isinstance(raw.get("identities"), dict) or not raw["identities"]:
        blockers.append("INVALID_PROTOCOL_IDENTITIES")
    if not isinstance(raw.get("mints"), list) or not raw["mints"]:
        blockers.append("INVALID_MINTS")
    else:
        for mint in raw["mints"]:
            try:
                _pubkey(mint, "mint")
            except ProtocolRegistryError:
                blockers.append("INVALID_MINTS")
                break
    try:
        _pubkey(raw.get("token_program"), "token_program")
    except ProtocolRegistryError:
        blockers.append("INVALID_TOKEN_PROGRAM")
    return tuple(blockers)
