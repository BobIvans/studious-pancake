from __future__ import annotations

import pytest

from src.external_contracts.conformance import (
    ConformanceHttpRequest,
    run_read_only_conformance,
)
from src.external_contracts.models import (
    ConformanceProbe,
    ContractCapability,
    ContractStatus,
    CredentialMode,
    ExternalContract,
    HttpMethod,
    JsonPathAssertion,
    JsonSemanticType,
    JsonValueType,
)


def _jupiter_contract(probe: ConformanceProbe) -> ExternalContract:
    return ExternalContract(
        id="jupiter.pr086",
        provider="jupiter",
        status=ContractStatus.DISCOVERY_ONLY,
        capabilities=(ContractCapability.QUOTE,),
        official_source_url="https://developers.jup.ag/docs/api-reference/swap/build",
        source_ref="pr086-test",
        conformance_probe=probe,
    )


def _jito_contract(probe: ConformanceProbe) -> ExternalContract:
    return ExternalContract(
        id="jito.pr086",
        provider="jito",
        status=ContractStatus.DISABLED_UNVERIFIED,
        capabilities=(ContractCapability.READ_ONLY_RPC,),
        official_source_url="https://docs.jito.wtf/lowlatencytxnsend/",
        source_ref="pr086-test",
        conformance_probe=probe,
    )


def test_jupiter_build_model_rejects_legacy_transaction_assertion() -> None:
    with pytest.raises(ValueError, match="raw instruction fields"):
        ConformanceProbe(
            url=(
                "https://api.jup.ag/swap/v2/build?"
                "inputMint=So11111111111111111111111111111111111111112&"
                "outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&"
                "amount=1000&taker=11111111111111111111111111111111"
            ),
            credential_mode=CredentialMode.HEADER_API_KEY,
            required_env=("JUPITER_API_KEY",),
            credential_header_name="x-api-key",
            credential_header_env="JUPITER_API_KEY",
            required_json_paths=("transaction",),
        )


def test_jupiter_legacy_transaction_fixture_fails_forbidden_shape() -> None:
    probe = ConformanceProbe(
        url=(
            "https://api.jup.ag/swap/v2/build?"
            "inputMint=So11111111111111111111111111111111111111112&"
            "outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&"
            "amount=1000&taker=11111111111111111111111111111111"
        ),
        credential_mode=CredentialMode.HEADER_API_KEY,
        required_env=("JUPITER_API_KEY",),
        credential_header_name="x-api-key",
        credential_header_env="JUPITER_API_KEY",
        required_json_paths=(
            "setupInstructions",
            "swapInstruction.programId",
            "swapInstruction.accounts",
            "swapInstruction.data",
            "addressesByLookupTableAddress",
            "blockhashWithMetadata.blockhash",
        ),
        forbidden_json_paths=("transaction",),
    )

    def transport(_: ConformanceHttpRequest) -> tuple[int, bytes]:
        return 200, b'{"transaction":"legacy-base64"}'

    result = run_read_only_conformance(
        _jupiter_contract(probe),
        enable_online=True,
        environ={"JUPITER_API_KEY": "secret-jup"},
        transport=transport,
    )

    assert result.state == "failed-assertion"
    assert result.verified is False
    assert "json-forbidden:transaction:failed" in result.assertions
    assert "json-path:swapInstruction.programId:failed" in result.assertions


def test_jito_tip_accounts_must_be_non_empty_valid_pubkeys() -> None:
    probe = ConformanceProbe(
        url="https://mainnet.block-engine.jito.wtf/api/v1/getTipAccounts",
        method=HttpMethod.POST,
        credential_mode=CredentialMode.OPTIONAL_UUID,
        json_body={"jsonrpc": "2.0", "id": 1, "method": "getTipAccounts", "params": []},
        json_assertions=(
            JsonPathAssertion(
                path="result",
                value_type=JsonValueType.ARRAY,
                min_size=1,
                array_item_semantic_type=JsonSemanticType.PUBKEY,
            ),
        ),
    )

    def bad_transport(_: ConformanceHttpRequest) -> tuple[int, bytes]:
        return 200, b'{"jsonrpc":"2.0","result":["not-a-pubkey"],"id":1}'

    bad = run_read_only_conformance(
        _jito_contract(probe), enable_online=True, environ={}, transport=bad_transport
    )

    assert bad.state == "failed-assertion"
    assert "json-array-semantic:result:pubkey:failed" in bad.assertions

    def good_transport(_: ConformanceHttpRequest) -> tuple[int, bytes]:
        return (
            200,
            b'{"jsonrpc":"2.0","result":["11111111111111111111111111111111"],"id":1}',
        )

    good = run_read_only_conformance(
        _jito_contract(probe), enable_online=True, environ={}, transport=good_transport
    )

    assert good.verified is True
    assert "json-array-semantic:result:pubkey:ok" in good.assertions


def test_integer_string_and_enum_assertions_are_enforced() -> None:
    probe = ConformanceProbe(
        url=(
            "https://api.jup.ag/swap/v2/build?"
            "inputMint=So11111111111111111111111111111111111111112&"
            "outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&"
            "amount=1000&taker=11111111111111111111111111111111"
        ),
        json_assertions=(
            JsonPathAssertion(
                path="inAmount",
                value_type=JsonValueType.STRING,
                semantic_type=JsonSemanticType.INTEGER_STRING,
            ),
            JsonPathAssertion(
                path="swapMode",
                value_type=JsonValueType.STRING,
                enum_values=("ExactIn", "ExactOut"),
            ),
        ),
    )

    def bad_transport(_: ConformanceHttpRequest) -> tuple[int, bytes]:
        return 200, b'{"inAmount":"1.5","swapMode":"unsupported"}'

    result = run_read_only_conformance(
        _jupiter_contract(probe), enable_online=True, environ={}, transport=bad_transport
    )

    assert result.state == "failed-assertion"
    assert "json-semantic:inAmount:integer-string:failed" in result.assertions
    assert "json-enum:swapMode:failed" in result.assertions
