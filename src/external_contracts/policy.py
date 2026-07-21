"""Evidence-bound admission policy for external runtime contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.external_contracts.models import (
    ContractCapability,
    ContractStatus,
    ExternalContract,
    PromotionState,
)


@dataclass(frozen=True, slots=True)
class ContractExecutionAdmission:
    contract_id: str | None
    allowed: bool
    reason: str
    required_env: tuple[str, ...]
    missing_env: tuple[str, ...]


def required_credential_env(contract: ExternalContract | None) -> tuple[str, ...]:
    if contract is None or contract.conformance_probe is None:
        return ()
    probe = contract.conformance_probe
    if probe.required_env:
        return probe.required_env
    if probe.credential_env:
        return (probe.credential_env,)
    return ()


def missing_credential_env(
    contract: ExternalContract | None,
    environ: Mapping[str, str] | None,
) -> tuple[str, ...]:
    required = required_credential_env(contract)
    if not required:
        return ()
    active_env = {} if environ is None else environ
    return tuple(name for name in required if not active_env.get(name))


def evaluate_contract_execution_admission(
    contract: ExternalContract | None,
    *,
    environ: Mapping[str, str] | None = None,
) -> ContractExecutionAdmission:
    required = required_credential_env(contract)
    missing = missing_credential_env(contract, environ)
    if contract is None:
        return ContractExecutionAdmission(
            None,
            False,
            "contract-missing",
            required,
            missing,
        )
    if contract.status is not ContractStatus.ACTIVE:
        return ContractExecutionAdmission(
            contract.id,
            False,
            f"contract-not-active:{contract.status.value}",
            required,
            missing,
        )
    if ContractCapability.COMPOSABLE_INSTRUCTIONS not in contract.capabilities:
        return ContractExecutionAdmission(
            contract.id,
            False,
            "contract-not-composable",
            required,
            missing,
        )
    if not contract.execution_allowed:
        return ContractExecutionAdmission(
            contract.id,
            False,
            f"execution-evidence-blocked:{contract.promotion_state.value}",
            required,
            missing,
        )
    if contract.promotion_state is not PromotionState.EXECUTION_ALLOWED:
        return ContractExecutionAdmission(
            contract.id,
            False,
            f"promotion-state-blocked:{contract.promotion_state.value}",
            required,
            missing,
        )
    if missing:
        return ContractExecutionAdmission(
            contract.id,
            False,
            "disabled_missing_credentials:" + ",".join(missing),
            required,
            missing,
        )
    return ContractExecutionAdmission(
        contract.id,
        True,
        "execution-evidence-and-credentials-verified",
        required,
        (),
    )
