from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .models import LendingProtocol, RawAccount, ReasonCode


class ContractError(ValueError):
    def __init__(self, reason: ReasonCode, msg: str):
        self.reason = reason
        super().__init__(msg)


@dataclass(frozen=True, slots=True)
class AccountTypeContract:
    name: str
    discriminator_hex: str
    min_size: int
    max_size: int | None
    expected_owner: str

    @property
    def discriminator(self) -> bytes:
        return bytes.fromhex(self.discriminator_hex)


@dataclass(frozen=True, slots=True)
class DeploymentContract:
    deployment_id: str
    protocol: LendingProtocol
    cluster: str
    enabled: bool
    disabled_reason: str | None
    program_id: str
    program_executable: bool
    version: str
    source_url: str
    source_ref: str
    license: str
    metadata_sha256: str
    account_types: dict[str, AccountTypeContract]
    discovery_filters: tuple[dict, ...]

    @property
    def risk_config_hash(self) -> str:
        payload = json.dumps(to_json(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def require_enabled(self) -> None:
        if not self.enabled:
            raise ContractError(
                ReasonCode.DISABLED_UNVERIFIED_CONTRACT,
                self.disabled_reason or "deployment disabled",
            )

    def validate_program_account(self, account: RawAccount) -> None:
        if account.pubkey != self.program_id:
            raise ContractError(ReasonCode.INVALID_PROGRAM_ID, "program id mismatch")
        if account.executable is not self.program_executable:
            raise ContractError(ReasonCode.INVALID_EXECUTABLE, "program executable mismatch")

    def validate_typed_account(self, typ: str, account: RawAccount) -> None:
        contract = self.account_types[typ]
        if account.owner != contract.expected_owner:
            raise ContractError(ReasonCode.INVALID_OWNER, "owner mismatch")
        if len(account.data) < contract.min_size:
            raise ContractError(ReasonCode.INVALID_ACCOUNT_SIZE, "account size mismatch")
        if contract.max_size is not None and len(account.data) > contract.max_size:
            raise ContractError(ReasonCode.INVALID_ACCOUNT_SIZE, "account size mismatch")
        if not account.data.startswith(contract.discriminator):
            raise ContractError(ReasonCode.INVALID_DISCRIMINATOR, "discriminator mismatch")


def to_json(deployment: DeploymentContract) -> dict:
    return {
        "deployment_id": deployment.deployment_id,
        "protocol": deployment.protocol.value,
        "cluster": deployment.cluster,
        "enabled": deployment.enabled,
        "disabled_reason": deployment.disabled_reason,
        "program_id": deployment.program_id,
        "program_executable": deployment.program_executable,
        "version": deployment.version,
        "source_url": deployment.source_url,
        "source_ref": deployment.source_ref,
        "license": deployment.license,
        "metadata_sha256": deployment.metadata_sha256,
        "account_types": {k: vars(v) for k, v in deployment.account_types.items()},
        "discovery_filters": deployment.discovery_filters,
    }


def load_contracts(path: str | Path = "docs/contracts/lending_indexer_manifest.json") -> tuple[DeploymentContract, ...]:
    raw = json.loads(Path(path).read_text())
    out = []
    for item in raw["deployments"]:
        account_types = {k: AccountTypeContract(**v) for k, v in item["account_types"].items()}
        kwargs = {k: v for k, v in item.items() if k not in {"protocol", "account_types", "discovery_filters"}}
        out.append(
            DeploymentContract(
                protocol=LendingProtocol(item["protocol"]),
                account_types=account_types,
                discovery_filters=tuple(item.get("discovery_filters", ())),
                **kwargs,
            )
        )
    return tuple(out)
