"""Load and verify the canonical external contract registry."""

from __future__ import annotations

import hashlib
from importlib import resources
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.external_contracts.models import (
    ContractStatus,
    ExternalContract,
    ExternalContractRegistryModel,
)


class ExternalContractError(ValueError):
    """Raised when registry provenance or a pinned artifact is invalid."""


class ExternalContractRegistry:
    def __init__(
        self, model: ExternalContractRegistryModel, artifact_root: Path
    ) -> None:
        self.model = model
        self.artifact_root = artifact_root.resolve()
        self._by_id = {contract.id: contract for contract in model.contracts}

    @classmethod
    def load_default(cls) -> "ExternalContractRegistry":
        root = Path(str(resources.files("src.resources"))).resolve()
        return cls.load(root / "external_contracts.json", artifact_root=root)

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        artifact_root: str | Path | None = None,
        verify_artifacts: bool = True,
    ) -> "ExternalContractRegistry":
        registry_path = Path(path).resolve()
        root = Path(artifact_root).resolve() if artifact_root else registry_path.parent
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            model = ExternalContractRegistryModel.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise ExternalContractError(
                f"invalid external contract registry: {exc}"
            ) from exc
        registry = cls(model, root)
        if verify_artifacts:
            registry.verify_artifacts()
        return registry

    @property
    def contracts(self) -> tuple[ExternalContract, ...]:
        return self.model.contracts

    def get(self, contract_id: str) -> ExternalContract:
        try:
            return self._by_id[contract_id]
        except KeyError as exc:
            raise ExternalContractError(
                f"unknown external contract: {contract_id}"
            ) from exc

    def provider(self, provider: str) -> tuple[ExternalContract, ...]:
        return tuple(item for item in self.contracts if item.provider == provider)

    def active(self) -> tuple[ExternalContract, ...]:
        return tuple(
            item for item in self.contracts if item.status is ContractStatus.ACTIVE
        )

    def execution_allowed(self) -> tuple[ExternalContract, ...]:
        return tuple(item for item in self.contracts if item.execution_allowed)

    def resolve_artifact(self, relative_path: str) -> Path:
        candidate = (self.artifact_root / relative_path).resolve()
        try:
            candidate.relative_to(self.artifact_root)
        except ValueError as exc:
            raise ExternalContractError(
                f"artifact escapes canonical resource root: {relative_path}"
            ) from exc
        return candidate

    def verify_artifacts(self) -> None:
        errors: list[str] = []
        for contract in self.contracts:
            for pin in contract.artifacts:
                path = self.resolve_artifact(pin.path)
                if not path.is_file():
                    if pin.required:
                        errors.append(
                            f"{contract.id}: missing required artifact {pin.path}"
                        )
                    continue
                observed = hashlib.sha256(path.read_bytes()).hexdigest()
                if observed != pin.sha256:
                    errors.append(
                        f"{contract.id}: sha256 drift for {pin.path}: "
                        f"expected {pin.sha256}, observed {observed}"
                    )
        if errors:
            raise ExternalContractError("; ".join(errors))

    def status_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.model.schema_version,
            "verified": True,
            "execution_allowed": bool(self.execution_allowed()),
            "execution_contracts": [item.id for item in self.execution_allowed()],
            "active_contracts": [item.id for item in self.active()],
            "contracts": [self._contract_status(item) for item in self.contracts],
        }

    @staticmethod
    def _contract_status(item: ExternalContract) -> dict[str, Any]:
        probe = item.conformance_probe
        return {
            "id": item.id,
            "provider": item.provider,
            "status": item.status.value,
            "capabilities": [capability.value for capability in item.capabilities],
            "source_ref": item.source_ref,
            "artifacts": len(item.artifacts),
            "promotion_state": item.promotion_state.value,
            "execution_allowed": item.execution_allowed,
            "evidence": item.evidence.model_dump(),
            "credential_mode": probe.credential_mode.value if probe else None,
            "required_env": list(probe.required_env) if probe else [],
            "optional_env": list(probe.optional_env) if probe else [],
        }
