from __future__ import annotations

from pathlib import Path

from src.external_contracts.conformance import ConformanceResult
from src.external_contracts.models import (
    ConformanceProbe,
    ContractCapability,
    ContractStatus,
    ExternalContract,
    ExternalContractRegistryModel,
    HttpMethod,
)
from src.external_contracts.production_evidence_pr153 import (
    ExternalConformanceEvidenceRunner,
    ProgramAttestationEvidence,
)
from src.external_contracts.registry import ExternalContractRegistry

MARGINFI = "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
SHA_A = "a" * 64
GIT_A = "b" * 40


def _registry(tmp_path: Path) -> ExternalContractRegistry:
    model = ExternalContractRegistryModel(
        contracts=(
            ExternalContract(
                id="jupiter.swap-v2-build",
                provider="jupiter",
                status=ContractStatus.DISCOVERY_ONLY,
                capabilities=(ContractCapability.QUOTE,),
                official_source_url="https://developers.jup.ag/docs/api-reference/swap/build",
                source_ref="reviewed",
                cluster="mainnet-beta",
                conformance_probe=ConformanceProbe(
                    url=(
                        "https://api.jup.ag/swap/v2/build?"
                        "inputMint=So11111111111111111111111111111111111111112&"
                        "outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&"
                        "amount=1000&slippageBps=50&"
                        "taker=11111111111111111111111111111111"
                    ),
                    method=HttpMethod.GET,
                ),
            ),
            ExternalContract(
                id="jito.low-latency-json-rpc",
                provider="jito",
                status=ContractStatus.DISABLED_UNVERIFIED,
                capabilities=(ContractCapability.READ_ONLY_RPC,),
                official_source_url="https://docs.jito.wtf/lowlatencytxnsend/",
                source_ref="reviewed",
                cluster="mainnet-beta",
                conformance_probe=ConformanceProbe(
                    url="https://mainnet.block-engine.jito.wtf/api/v1/getTipAccounts",
                    method=HttpMethod.POST,
                    json_body={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getTipAccounts",
                        "params": [],
                    },
                ),
            ),
            ExternalContract(
                id="marginfi.v2-mainnet-source-identity",
                provider="marginfi",
                status=ContractStatus.DISABLED_UNVERIFIED,
                capabilities=(ContractCapability.PROTOCOL_SOURCE,),
                official_source_url="https://docs.marginfi.com/rust-sdk",
                source_ref="reviewed",
                deployment_program_id=MARGINFI,
                cluster="mainnet-beta",
            ),
        )
    )
    return ExternalContractRegistry(model, tmp_path)


def _verified_probe(contract: ExternalContract, **_: object) -> ConformanceResult:
    return ConformanceResult(
        contract_id=contract.id,
        state="verified",
        verified=True,
        status_code=200,
        assertions=("status-code:ok",),
        request_method="GET",
        request_url="https://example.invalid/read-only",
        response_sha256=SHA_A,
    )


def _failed_probe(contract: ExternalContract, **_: object) -> ConformanceResult:
    return ConformanceResult(
        contract_id=contract.id,
        state="failed-request",
        verified=False,
        status_code=None,
        assertions=(),
        error="network: secret detail must not be copied",
    )


def _marginfi_attestation(**overrides: object) -> ProgramAttestationEvidence:
    values: dict[str, object] = {
        "contract_id": "marginfi.v2-mainnet-source-identity",
        "program_id": MARGINFI,
        "cluster": "mainnet-beta",
        "loader_owner": "BPFLoaderUpgradeab1e11111111111111111111111",
        "executable": True,
        "programdata_address": "programdata-address",
        "upgrade_authority": "reviewed-authority",
        "upgrade_authority_reviewed": True,
        "deployed_binary_sha256": SHA_A,
        "reproduced_binary_sha256": SHA_A,
        "source_commit": GIT_A,
        "rooted_slot": 100,
        "observed_at_ns": 1_000,
        "expires_at_ns": 3_000,
    }
    values.update(overrides)
    return ProgramAttestationEvidence(**values)  # type: ignore[arg-type]


def test_pr153_complete_bundle_is_review_ready_but_never_auto_promotes(
    tmp_path: Path,
) -> None:
    bundle = ExternalConformanceEvidenceRunner(
        _registry(tmp_path),
        probe_runner=_verified_probe,
        clock_ns=lambda: 2_000,
    ).run(
        contract_ids=(
            "jupiter.swap-v2-build",
            "jito.low-latency-json-rpc",
        ),
        required_program_contract_ids=(
            "marginfi.v2-mainnet-source-identity",
        ),
        program_attestations=(_marginfi_attestation(),),
        enable_online=True,
    )

    assert bundle.review_ready is True
    assert bundle.blockers == ()
    assert bundle.registry_mutated is False
    assert bundle.automatic_promotion_allowed is False
    assert len(bundle.bundle_sha256) == 64


def test_pr153_failed_probe_is_a_blocker_and_redacts_error_detail(
    tmp_path: Path,
) -> None:
    bundle = ExternalConformanceEvidenceRunner(
        _registry(tmp_path),
        probe_runner=_failed_probe,
        clock_ns=lambda: 2_000,
    ).run(contract_ids=("jupiter.swap-v2-build",), enable_online=True)

    assert bundle.review_ready is False
    assert "PR153_PROBE_NOT_VERIFIED:jupiter.swap-v2-build" in bundle.blockers
    assert bundle.probe_records[0].error_category == "network"
    assert "secret detail" not in repr(bundle.to_json())


def test_pr153_program_binary_hash_mismatch_blocks(tmp_path: Path) -> None:
    bundle = ExternalConformanceEvidenceRunner(
        _registry(tmp_path),
        probe_runner=_verified_probe,
        clock_ns=lambda: 2_000,
    ).run(
        contract_ids=("jupiter.swap-v2-build",),
        required_program_contract_ids=(
            "marginfi.v2-mainnet-source-identity",
        ),
        program_attestations=(
            _marginfi_attestation(reproduced_binary_sha256="c" * 64),
        ),
        enable_online=True,
    )

    assert any("REPRODUCED_BINARY_HASH_MISMATCH" in item for item in bundle.blockers)


def test_pr153_registry_program_identity_mismatch_blocks(tmp_path: Path) -> None:
    bundle = ExternalConformanceEvidenceRunner(
        _registry(tmp_path),
        probe_runner=_verified_probe,
        clock_ns=lambda: 2_000,
    ).run(
        contract_ids=("jupiter.swap-v2-build",),
        program_attestations=(
            _marginfi_attestation(program_id="11111111111111111111111111111111"),
        ),
        enable_online=True,
    )

    assert any("PROGRAM_ID_MISMATCH" in item for item in bundle.blockers)


def test_pr153_missing_required_program_attestation_blocks(tmp_path: Path) -> None:
    bundle = ExternalConformanceEvidenceRunner(
        _registry(tmp_path),
        probe_runner=_verified_probe,
        clock_ns=lambda: 2_000,
    ).run(
        contract_ids=("jupiter.swap-v2-build",),
        required_program_contract_ids=(
            "marginfi.v2-mainnet-source-identity",
        ),
        enable_online=True,
    )

    assert (
        "PR153_PROGRAM_ATTESTATION_MISSING:marginfi.v2-mainnet-source-identity"
        in bundle.blockers
    )


def test_pr153_bundle_hash_is_deterministic(tmp_path: Path) -> None:
    runner = ExternalConformanceEvidenceRunner(
        _registry(tmp_path),
        probe_runner=_verified_probe,
        clock_ns=lambda: 2_000,
    )
    kwargs = {
        "contract_ids": ("jupiter.swap-v2-build",),
        "enable_online": True,
    }
    assert runner.run(**kwargs).bundle_sha256 == runner.run(**kwargs).bundle_sha256
