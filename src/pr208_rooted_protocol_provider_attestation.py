"""PR-208 rooted protocol and provider attestation gate.

This module is intentionally offline and sender-free. It does not fetch Solana RPC,
construct transactions, sign payloads or enable live trading. Its purpose is to
reject the Pass-6 PR-208 anti-pattern: caller supplied booleans/paths pretending
to be protocol conformance.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Mapping

SCHEMA_VERSION = "pr208.rooted-protocol-provider-attestation.v1"
TOKEN_2022_PROGRAM_ID = "TokenzQdY73Y67cyxEWKrvMpkFea8GZ4SXifknFxQ"
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
WSOL_MINT = "So11111111111111111111111111111111111111112"
ALLOWED_COMMITMENTS = frozenset({"confirmed", "finalized"})
TRIVIAL_SHA256 = frozenset({"0" * 64, "f" * 64})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _is_sha256(value: str) -> bool:
    return bool(SHA256_RE.fullmatch(value)) and value not in TRIVIAL_SHA256


def _path_is_normalized(path: str) -> bool:
    parsed = PurePosixPath(path)
    return (
        path == parsed.as_posix()
        and not parsed.is_absolute()
        and path not in {"", "."}
        and ".." not in parsed.parts
    )


def _unique(values: tuple[str, ...]) -> bool:
    return len(set(values)) == len(values)


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class MaterializedEvidenceRef:
    path: str
    sha256: str
    size_bytes: int
    media_type: str
    producer_id: str
    created_at_slot: int
    retained_until_slot: int
    materialized: bool = True
    attestation_sha256: str = ""

    def blockers(self, prefix: str) -> list[str]:
        blockers: list[str] = []
        if not _path_is_normalized(self.path):
            blockers.append(f"{prefix}_PATH_NOT_NORMALIZED")
        if not _is_sha256(self.sha256):
            blockers.append(f"{prefix}_SHA256_INVALID")
        if self.attestation_sha256 and not _is_sha256(self.attestation_sha256):
            blockers.append(f"{prefix}_ATTESTATION_SHA256_INVALID")
        if self.size_bytes <= 0:
            blockers.append(f"{prefix}_SIZE_NOT_POSITIVE")
        if not self.media_type:
            blockers.append(f"{prefix}_MEDIA_TYPE_MISSING")
        if not self.producer_id:
            blockers.append(f"{prefix}_PRODUCER_MISSING")
        if self.created_at_slot < 0:
            blockers.append(f"{prefix}_CREATED_SLOT_INVALID")
        if self.retained_until_slot < self.created_at_slot:
            blockers.append(f"{prefix}_RETENTION_BEFORE_CREATION")
        if self.materialized is not True:
            blockers.append(f"{prefix}_NOT_MATERIALIZED")
        return blockers

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "producer_id": self.producer_id,
            "created_at_slot": self.created_at_slot,
            "retained_until_slot": self.retained_until_slot,
            "materialized": self.materialized,
            "attestation_sha256": self.attestation_sha256,
        }


@dataclass(frozen=True)
class RootedAccountEvidence:
    address: str
    kind: str
    owner_program: str
    slot: int
    min_context_slot: int
    genesis_hash: str
    commitment: str
    raw_bytes_sha256: str
    evidence: MaterializedEvidenceRef
    executable: bool = False
    extensions: tuple[str, ...] = ()

    def blockers(self, prefix: str) -> list[str]:
        blockers = self.evidence.blockers(f"{prefix}_EVIDENCE")
        if not self.address:
            blockers.append(f"{prefix}_ADDRESS_MISSING")
        if self.kind not in {"program", "mint", "token_account", "ata", "protocol_account"}:
            blockers.append(f"{prefix}_KIND_INVALID")
        if not self.owner_program:
            blockers.append(f"{prefix}_OWNER_PROGRAM_MISSING")
        if self.slot < self.min_context_slot:
            blockers.append(f"{prefix}_SLOT_BEFORE_MIN_CONTEXT")
        if not _is_sha256(self.genesis_hash):
            blockers.append(f"{prefix}_GENESIS_HASH_INVALID")
        if self.commitment not in ALLOWED_COMMITMENTS:
            blockers.append(f"{prefix}_COMMITMENT_INVALID")
        if self.raw_bytes_sha256 != self.evidence.sha256:
            blockers.append(f"{prefix}_RAW_BYTES_HASH_NOT_RECOMPUTED")
        if self.kind == "program" and not self.executable:
            blockers.append(f"{prefix}_PROGRAM_NOT_EXECUTABLE")
        return blockers

    def to_dict(self) -> dict[str, object]:
        return {
            "address": self.address,
            "kind": self.kind,
            "owner_program": self.owner_program,
            "slot": self.slot,
            "min_context_slot": self.min_context_slot,
            "genesis_hash": self.genesis_hash,
            "commitment": self.commitment,
            "raw_bytes_sha256": self.raw_bytes_sha256,
            "evidence": self.evidence.to_dict(),
            "executable": self.executable,
            "extensions": list(self.extensions),
        }


@dataclass(frozen=True)
class ProviderResponseEvidence:
    provider_id: str
    endpoint_id: str
    credential_scope: str
    response_kind: str
    request_sha256: str
    response_sha256: str
    tls_peer_fingerprint_sha256: str
    observed_slot: int
    min_context_slot: int
    genesis_hash: str
    commitment: str
    request_evidence: MaterializedEvidenceRef
    response_evidence: MaterializedEvidenceRef
    bound_addresses: tuple[str, ...]

    def blockers(self, prefix: str) -> list[str]:
        blockers = self.request_evidence.blockers(f"{prefix}_REQUEST")
        blockers.extend(self.response_evidence.blockers(f"{prefix}_RESPONSE"))
        if not self.provider_id:
            blockers.append(f"{prefix}_PROVIDER_ID_MISSING")
        if not self.endpoint_id:
            blockers.append(f"{prefix}_ENDPOINT_ID_MISSING")
        if not self.credential_scope:
            blockers.append(f"{prefix}_CREDENTIAL_SCOPE_MISSING")
        if self.response_kind not in {"getAccountInfo", "getMultipleAccounts", "getProgramAccounts"}:
            blockers.append(f"{prefix}_RESPONSE_KIND_INVALID")
        for field_name, value in {
            "REQUEST_SHA256": self.request_sha256,
            "RESPONSE_SHA256": self.response_sha256,
            "TLS_PEER_FINGERPRINT": self.tls_peer_fingerprint_sha256,
            "GENESIS_HASH": self.genesis_hash,
        }.items():
            if not _is_sha256(value):
                blockers.append(f"{prefix}_{field_name}_INVALID")
        if self.request_sha256 != self.request_evidence.sha256:
            blockers.append(f"{prefix}_REQUEST_HASH_NOT_MATERIALIZED")
        if self.response_sha256 != self.response_evidence.sha256:
            blockers.append(f"{prefix}_RESPONSE_HASH_NOT_MATERIALIZED")
        if self.observed_slot < self.min_context_slot:
            blockers.append(f"{prefix}_OBSERVED_SLOT_BEFORE_MIN_CONTEXT")
        if self.commitment not in ALLOWED_COMMITMENTS:
            blockers.append(f"{prefix}_COMMITMENT_INVALID")
        if not self.bound_addresses or not _unique(self.bound_addresses):
            blockers.append(f"{prefix}_BOUND_ADDRESSES_INVALID")
        return blockers

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "endpoint_id": self.endpoint_id,
            "credential_scope": self.credential_scope,
            "response_kind": self.response_kind,
            "request_sha256": self.request_sha256,
            "response_sha256": self.response_sha256,
            "tls_peer_fingerprint_sha256": self.tls_peer_fingerprint_sha256,
            "observed_slot": self.observed_slot,
            "min_context_slot": self.min_context_slot,
            "genesis_hash": self.genesis_hash,
            "commitment": self.commitment,
            "request_evidence": self.request_evidence.to_dict(),
            "response_evidence": self.response_evidence.to_dict(),
            "bound_addresses": list(self.bound_addresses),
        }


@dataclass(frozen=True)
class ExecutionAssetSet:
    plan_sha256: str
    required_addresses: tuple[str, ...]
    required_programs: tuple[str, ...]
    required_mints: tuple[str, ...]
    token_2022_mints: tuple[str, ...]
    ata_accounts: tuple[str, ...]
    wsol_mint: str = WSOL_MINT

    def blockers(self) -> list[str]:
        blockers: list[str] = []
        if not _is_sha256(self.plan_sha256):
            blockers.append("PR208_PLAN_SHA256_INVALID")
        for name, values in {
            "REQUIRED_ADDRESSES": self.required_addresses,
            "REQUIRED_PROGRAMS": self.required_programs,
            "REQUIRED_MINTS": self.required_mints,
            "TOKEN_2022_MINTS": self.token_2022_mints,
            "ATA_ACCOUNTS": self.ata_accounts,
        }.items():
            if not values or not _unique(values):
                blockers.append(f"PR208_{name}_EMPTY_OR_DUPLICATE")
        if self.wsol_mint != WSOL_MINT:
            blockers.append("PR208_WSOL_MINT_IDENTITY_DRIFT")
        return blockers

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_sha256": self.plan_sha256,
            "required_addresses": list(self.required_addresses),
            "required_programs": list(self.required_programs),
            "required_mints": list(self.required_mints),
            "token_2022_mints": list(self.token_2022_mints),
            "ata_accounts": list(self.ata_accounts),
            "wsol_mint": self.wsol_mint,
        }


@dataclass(frozen=True)
class PR208ProtocolProviderEvidence:
    chain_genesis_hash: str
    commitment: str
    min_context_slot: int
    execution_assets: ExecutionAssetSet
    rooted_accounts: tuple[RootedAccountEvidence, ...]
    provider_responses: tuple[ProviderResponseEvidence, ...]
    exported_complete_claim_helper: bool = False
    caller_supplied_claims_present: bool = False
    live_capability_enabled: bool = False
    sender_capability_enabled: bool = False
    signer_capability_enabled: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "chain_genesis_hash": self.chain_genesis_hash,
            "commitment": self.commitment,
            "min_context_slot": self.min_context_slot,
            "execution_assets": self.execution_assets.to_dict(),
            "rooted_accounts": [item.to_dict() for item in self.rooted_accounts],
            "provider_responses": [item.to_dict() for item in self.provider_responses],
            "exported_complete_claim_helper": self.exported_complete_claim_helper,
            "caller_supplied_claims_present": self.caller_supplied_claims_present,
            "live_capability_enabled": self.live_capability_enabled,
            "sender_capability_enabled": self.sender_capability_enabled,
            "signer_capability_enabled": self.signer_capability_enabled,
        }


@dataclass(frozen=True)
class PR208ProtocolProviderReport:
    schema_version: str
    passed: bool
    evidence_hash: str
    blockers: tuple[str, ...]
    rooted_account_count: int
    provider_response_count: int
    live_capability_allowed: bool = False
    sender_capability_allowed: bool = False
    signer_capability_allowed: bool = False


def evaluate_pr208_protocol_provider(
    evidence: PR208ProtocolProviderEvidence,
) -> PR208ProtocolProviderReport:
    blockers: list[str] = []
    if not _is_sha256(evidence.chain_genesis_hash):
        blockers.append("PR208_CHAIN_GENESIS_HASH_INVALID")
    if evidence.commitment not in ALLOWED_COMMITMENTS:
        blockers.append("PR208_COMMITMENT_INVALID")
    if evidence.min_context_slot < 0:
        blockers.append("PR208_MIN_CONTEXT_SLOT_INVALID")
    if evidence.exported_complete_claim_helper:
        blockers.append("PR208_COMPLETE_CLAIM_HELPER_EXPORTED")
    if evidence.caller_supplied_claims_present:
        blockers.append("PR208_CALLER_SUPPLIED_CLAIMS_PRESENT")
    if evidence.live_capability_enabled:
        blockers.append("PR208_LIVE_CAPABILITY_ENABLED")
    if evidence.sender_capability_enabled:
        blockers.append("PR208_SENDER_CAPABILITY_ENABLED")
    if evidence.signer_capability_enabled:
        blockers.append("PR208_SIGNER_CAPABILITY_ENABLED")

    blockers.extend(evidence.execution_assets.blockers())

    rooted_by_address: dict[str, RootedAccountEvidence] = {}
    for index, account in enumerate(evidence.rooted_accounts):
        blockers.extend(account.blockers(f"PR208_ROOTED_ACCOUNT_{index}"))
        if account.address in rooted_by_address:
            blockers.append(f"PR208_DUPLICATE_ROOTED_ACCOUNT:{account.address}")
        rooted_by_address[account.address] = account
        if account.genesis_hash != evidence.chain_genesis_hash:
            blockers.append(f"PR208_ROOTED_ACCOUNT_GENESIS_DRIFT:{account.address}")
        if account.commitment != evidence.commitment:
            blockers.append(f"PR208_ROOTED_ACCOUNT_COMMITMENT_DRIFT:{account.address}")
        if account.min_context_slot != evidence.min_context_slot:
            blockers.append(f"PR208_ROOTED_ACCOUNT_CONTEXT_DRIFT:{account.address}")

    required_addresses = set(evidence.execution_assets.required_addresses)
    required_programs = set(evidence.execution_assets.required_programs)
    required_mints = set(evidence.execution_assets.required_mints)
    required_atas = set(evidence.execution_assets.ata_accounts)
    all_required = required_addresses | required_programs | required_mints | required_atas | {evidence.execution_assets.wsol_mint}
    missing = sorted(address for address in all_required if address not in rooted_by_address)
    for address in missing:
        blockers.append(f"PR208_EXECUTION_ASSET_NOT_ROOTED:{address}")

    for program_id in sorted(required_programs):
        rooted = rooted_by_address.get(program_id)
        if rooted and (rooted.kind != "program" or not rooted.executable):
            blockers.append(f"PR208_PROGRAM_NOT_ROOTED_EXECUTABLE:{program_id}")
    for mint in sorted(evidence.execution_assets.token_2022_mints):
        rooted = rooted_by_address.get(mint)
        if rooted and (rooted.owner_program != TOKEN_2022_PROGRAM_ID or not rooted.extensions):
            blockers.append(f"PR208_TOKEN2022_EXTENSIONS_NOT_MATERIALIZED:{mint}")
    wsol = rooted_by_address.get(evidence.execution_assets.wsol_mint)
    if wsol and wsol.owner_program != SPL_TOKEN_PROGRAM_ID:
        blockers.append("PR208_WSOL_OWNER_PROGRAM_DRIFT")

    provider_bound: set[str] = set()
    provider_ids: set[str] = set()
    for index, response in enumerate(evidence.provider_responses):
        blockers.extend(response.blockers(f"PR208_PROVIDER_RESPONSE_{index}"))
        provider_ids.add(response.provider_id)
        provider_bound.update(response.bound_addresses)
        if response.genesis_hash != evidence.chain_genesis_hash:
            blockers.append(f"PR208_PROVIDER_GENESIS_DRIFT:{response.provider_id}")
        if response.commitment != evidence.commitment:
            blockers.append(f"PR208_PROVIDER_COMMITMENT_DRIFT:{response.provider_id}")
        if response.min_context_slot != evidence.min_context_slot:
            blockers.append(f"PR208_PROVIDER_CONTEXT_DRIFT:{response.provider_id}")
    if not provider_ids:
        blockers.append("PR208_PROVIDER_EVIDENCE_MISSING")
    for address in sorted(all_required - provider_bound):
        blockers.append(f"PR208_ASSET_NOT_BOUND_TO_PROVIDER_RESPONSE:{address}")

    unique_blockers = tuple(sorted(dict.fromkeys(blockers)))
    evidence_hash = _stable_hash(evidence.to_dict())
    return PR208ProtocolProviderReport(
        schema_version=SCHEMA_VERSION,
        passed=not unique_blockers,
        evidence_hash=evidence_hash,
        blockers=unique_blockers,
        rooted_account_count=len(evidence.rooted_accounts),
        provider_response_count=len(evidence.provider_responses),
    )
