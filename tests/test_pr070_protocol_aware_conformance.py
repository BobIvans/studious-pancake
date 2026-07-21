from __future__ import annotations

import re

import pytest

from src.external_contracts.cli import _conformance_exit_code, _conformance_verified
from src.external_contracts.conformance import (
    ConformanceHttpRequest,
    run_read_only_conformance,
)
from src.external_contracts.models import (
    ConformanceProbe,
    ContractCapability,
    ContractEvidence,
    ContractStatus,
    CredentialMode,
    ExternalContract,
    HttpMethod,
    JsonPathAssertion,
    JsonValueType,
    PromotionState,
)


OKX_ENV = {
    "OKX_API_KEY": "okx-key",
    "OKX_SECRET_KEY": "okx-secret",
    "OKX_API_PASSPHRASE": "okx-passphrase",
}


def _contract(probe: ConformanceProbe) -> ExternalContract:
    return ExternalContract(
        id="okx.test",
        provider="okx",
        status=ContractStatus.DISCOVERY_ONLY,
        capabilities=(ContractCapability.QUOTE,),
        official_source_url=(
            "https://web3.okx.com/onchainos/dev-docs/trade/"
            "dex-solana-swap-instruction"
        ),
        source_ref="test",
        promotion_state=PromotionState.CREDENTIALED_CONFORMANCE_PENDING,
        evidence=ContractEvidence(local_artifact_integrity=True),
        conformance_probe=probe,
    )


def test_jupiter_build_probe_requires_taker() -> None:
    with pytest.raises(ValueError, match="requires taker"):
        ConformanceProbe(
            url=(
                "https://api.jup.ag/swap/v2/build?"
                "inputMint=So11111111111111111111111111111111111111112&"
                "outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&"
                "amount=1000"
            ),
            credential_mode=CredentialMode.HEADER_API_KEY,
            required_env=("JUPITER_API_KEY",),
            credential_header_name="x-api-key",
            credential_header_env="JUPITER_API_KEY",
        )


def test_jito_get_tip_accounts_requires_json_rpc_post() -> None:
    with pytest.raises(ValueError, match="must use POST"):
        ConformanceProbe(
            url="https://mainnet.block-engine.jito.wtf/api/v1/getTipAccounts",
            method=HttpMethod.GET,
            credential_mode=CredentialMode.OPTIONAL_UUID,
        )

    probe = ConformanceProbe(
        url="https://mainnet.block-engine.jito.wtf/api/v1/getTipAccounts",
        method=HttpMethod.POST,
        credential_mode=CredentialMode.OPTIONAL_UUID,
        json_body={"jsonrpc": "2.0", "id": 1, "method": "getTipAccounts", "params": []},
        json_assertions=(
            JsonPathAssertion(
                path="result", value_type=JsonValueType.ARRAY, min_size=1
            ),
        ),
    )
    assert probe.method is HttpMethod.POST


def test_okx_signed_probe_uses_iso_utc_timestamp() -> None:
    captured: list[ConformanceHttpRequest] = []
    probe = ConformanceProbe(
        url=(
            "https://web3.okx.com/api/v6/dex/aggregator/"
            "swap-instruction?chainIndex=501"
        ),
        method=HttpMethod.GET,
        credential_mode=CredentialMode.OKX_SIGNED,
        required_env=("OKX_API_KEY", "OKX_SECRET_KEY", "OKX_API_PASSPHRASE"),
        business_code_path="code",
        business_code_equals="0",
    )

    def transport(request: ConformanceHttpRequest) -> tuple[int, bytes]:
        captured.append(request)
        return 200, b'{"code":"0","data":[]}'

    result = run_read_only_conformance(
        _contract(probe), enable_online=True, environ=OKX_ENV, transport=transport
    )

    assert result.verified is True
    timestamp = captured[0].headers["OK-ACCESS-TIMESTAMP"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", timestamp)
    assert captured[0].headers["OK-ACCESS-SIGN"]
    assert "okx-secret" not in (result.to_dict().get("error") or "")


def test_business_code_failure_is_failed_assertion() -> None:
    probe = ConformanceProbe(
        url=(
            "https://web3.okx.com/api/v6/dex/aggregator/"
            "swap-instruction?chainIndex=501"
        ),
        method=HttpMethod.GET,
        credential_mode=CredentialMode.OKX_SIGNED,
        required_env=("OKX_API_KEY", "OKX_SECRET_KEY", "OKX_API_PASSPHRASE"),
        business_code_path="code",
        business_code_equals="0",
    )

    def transport(_: ConformanceHttpRequest) -> tuple[int, bytes]:
        return 200, b'{"code":"51000","data":[]}'

    result = run_read_only_conformance(
        _contract(probe), enable_online=True, environ=OKX_ENV, transport=transport
    )

    assert result.state == "failed-assertion"
    assert result.verified is False
    assert _conformance_exit_code([result.to_dict()]) == 2


def test_aggregate_verified_requires_every_requested_contract() -> None:
    assert _conformance_verified(
        [
            {"state": "verified", "verified": True},
            {"state": "skipped-missing-env", "verified": False},
        ]
    ) is False
    assert _conformance_verified([{"state": "verified", "verified": True}]) is True
    assert (
        _conformance_exit_code(
            [{"state": "skipped-missing-env", "verified": False}]
        )
        == 0
    )


def test_jito_probe_sends_json_rpc_post_and_checks_result_array() -> None:
    jito_contract = ExternalContract(
        id="jito.test",
        provider="jito",
        status=ContractStatus.DISABLED_UNVERIFIED,
        capabilities=(ContractCapability.READ_ONLY_RPC,),
        official_source_url="https://docs.jito.wtf/lowlatencytxnsend/",
        source_ref="test",
        conformance_probe=ConformanceProbe(
            url="https://mainnet.block-engine.jito.wtf/api/v1/getTipAccounts",
            method=HttpMethod.POST,
            credential_mode=CredentialMode.OPTIONAL_UUID,
            optional_env=("JITO_UUID",),
            json_body={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTipAccounts",
                "params": [],
            },
            json_assertions=(
                JsonPathAssertion(
                    path="result", value_type=JsonValueType.ARRAY, min_size=1
                ),
            ),
        ),
    )

    def transport(request: ConformanceHttpRequest) -> tuple[int, bytes]:
        assert request.method == "POST"
        assert request.body == (
            b'{"jsonrpc":"2.0","id":1,"method":"getTipAccounts","params":[]}'
        )
        assert request.headers["content-type"] == "application/json"
        return (
            200,
            b'{"jsonrpc":"2.0","result":["11111111111111111111111111111111"],"id":1}',
        )

    result = run_read_only_conformance(
        jito_contract, enable_online=True, environ={}, transport=transport
    )

    assert result.verified is True
    assert result.request_method == "POST"
