from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.external_contracts.models import ArtifactPin, ContractStatus
from src.external_contracts.registry import ExternalContractRegistry


def test_default_registry_verifies_required_artifacts() -> None:
    registry = ExternalContractRegistry.load_default()
    assert registry.model.schema_version == "pr027.external-contracts.v1"
    assert tuple(contract.id for contract in registry.active()) == (
        "jupiter.swap-v2-build",
    )
    assert registry.get("okx.solana-swap-instruction-v6").status is ContractStatus.DISCOVERY_ONLY
    assert registry.get("openocean.solana-v4-quote").status is ContractStatus.DISCOVERY_ONLY
    assert registry.get("odos.solana-api").status is ContractStatus.DISCOVERY_ONLY
    marginfi = registry.get("marginfi.project-zero-mainnet")
    assert marginfi.deployment_program_id == "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
    assert len(marginfi.artifacts) >= 2


def test_placeholder_hash_is_rejected() -> None:
    with pytest.raises(ValidationError, match="all-zero"):
        ArtifactPin.model_validate({
            "path": "contracts/provider/fixture.json",
            "sha256": "0" * 64,
            "kind": "schema",
            "fetched_at": "2026-07-20T11:55:00Z",
            "required": True,
        })


def test_parent_path_is_rejected() -> None:
    with pytest.raises(ValidationError, match="normalized relative path"):
        ArtifactPin.model_validate({
            "path": "../fixture.json",
            "sha256": "a" * 64,
            "kind": "schema",
            "fetched_at": "2026-07-20T11:55:00Z",
            "required": True,
        })
