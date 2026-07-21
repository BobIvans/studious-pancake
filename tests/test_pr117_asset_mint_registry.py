from __future__ import annotations

import json
from pathlib import Path

from src.asset_mint_registry_pr117 import (
    LEGACY_SPL_TOKEN_PROGRAM_ID,
    PR117_SCHEMA_VERSION,
    TOKEN_2022_PROGRAM_ID,
    evaluate_pr117_asset_mint_registry,
    main,
)

_SOL = "So11111111111111111111111111111111111111112"
_USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
_TOKEN_2022_MINT = "A" * 32
_SHA = "a" * 64
_TSLOT = 345_678_901


def test_pr117_default_registry_is_valid_but_not_execution_ready() -> None:
    result = evaluate_pr117_asset_mint_registry(repo_root=Path("."))

    assert result.registry_valid is True
    assert result.execution_ready is False
    assert result.tradable_mint_count == 0
    assert "PR117_REQUIRED_PAIR_NOT_EXECUTION_READY:sol-usdc-loop" in (
        result.execution_blockers
    )
    assert "PR117_NO_MINTS_CURRENTLY_EXECUTION_TRADABLE" in result.warnings


def test_pr117_cli_default_does_not_claim_execution_ready() -> None:
    assert main(["--repo-root", ".", "--json"]) == 0
    assert main(["--repo-root", ".", "--json", "--require-execution-ready"]) == 1


def test_pr117_rejects_address_and_decimals_only_tradable_asset(tmp_path: Path) -> None:
    registry = _registry_payload(
        [
            {
                "symbol": "UNSAFE",
                "mint": _SOL,
                "cluster": "mainnet-beta",
                "decimals": 9,
                "asset_class": "wrapped-native",
                "admission": "tradable",
                "extensions": [],
                "reviewed": True,
                "reviewer": "operator",
            }
        ]
    )
    universe = _universe_payload(_SOL, _SOL)
    _write_json(tmp_path / "registry.json", registry)
    _write_json(tmp_path / "universe.json", universe)

    result = evaluate_pr117_asset_mint_registry(
        repo_root=tmp_path,
        registry_path="registry.json",
        universe_path="universe.json",
    )

    assert result.registry_valid is False
    assert any(
        blocker.startswith("PR117_ASSET_ENTRY_INVALID")
        for blocker in result.blockers
    )


def test_pr117_allows_reviewed_legacy_spl_fixture(tmp_path: Path) -> None:
    registry = _registry_payload(
        [
            _reviewed_asset("SOL", _SOL, 9, "wrapped-native"),
            _reviewed_asset("USDC", _USDC, 6, "stablecoin"),
        ]
    )
    universe = _universe_payload(_SOL, _USDC)
    _write_json(tmp_path / "registry.json", registry)
    _write_json(tmp_path / "universe.json", universe)

    result = evaluate_pr117_asset_mint_registry(
        repo_root=tmp_path,
        registry_path="registry.json",
        universe_path="universe.json",
    )

    assert result.registry_valid is True
    assert result.execution_ready is True
    assert result.tradable_mint_count == 2
    assert result.execution_blockers == ()


def test_pr117_rejects_token2022_tradable_extension(tmp_path: Path) -> None:
    registry = _registry_payload(
        [
            _reviewed_asset(
                "T22",
                _TOKEN_2022_MINT,
                6,
                "stablecoin",
                token_program="token-2022",
                token_program_id=TOKEN_2022_PROGRAM_ID,
                extensions=["transfer_hook"],
            )
        ]
    )
    universe = _universe_payload(_TOKEN_2022_MINT, _TOKEN_2022_MINT)
    _write_json(tmp_path / "registry.json", registry)
    _write_json(tmp_path / "universe.json", universe)

    result = evaluate_pr117_asset_mint_registry(
        repo_root=tmp_path,
        registry_path="registry.json",
        universe_path="universe.json",
    )

    assert result.registry_valid is True
    assert result.execution_ready is False
    assert "PR117_TOKEN_2022_FAIL_CLOSED:T22" in result.execution_blockers
    assert (
        "PR117_TOKEN_2022_EXTENSION_NOT_SUPPORTED:T22:transfer_hook"
        in result.execution_blockers
    )


def test_pr117_rejects_lst_tradable_without_oracle_redemption(tmp_path: Path) -> None:
    registry = _registry_payload(
        [
            _reviewed_asset(
                "JitoSOL",
                "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
                9,
                "lst",
            )
        ]
    )
    mint = "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn"
    universe = _universe_payload(mint, mint)
    _write_json(tmp_path / "registry.json", registry)
    _write_json(tmp_path / "universe.json", universe)

    result = evaluate_pr117_asset_mint_registry(
        repo_root=tmp_path,
        registry_path="registry.json",
        universe_path="universe.json",
    )

    assert result.registry_valid is True
    assert result.execution_ready is False
    assert "PR117_ORACLE_EVIDENCE_MISSING:JitoSOL" in result.execution_blockers
    assert "PR117_REDEMPTION_EVIDENCE_MISSING:JitoSOL" in result.execution_blockers


def _registry_payload(assets: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": PR117_SCHEMA_VERSION,
        "policy": {
            "all_token_2022_fail_closed": True,
            "first_vertical": "legacy-spl-only",
            "execution_claimed": False,
        },
        "token_2022_extension_matrix": {
            "extensions": [
                {"name": name, "disposition": "forbidden"}
                for name in (
                    "transfer_fee_config",
                    "transfer_fee_amount",
                    "transfer_hook",
                    "permanent_delegate",
                    "default_account_state",
                    "non_transferable",
                    "memo_transfer",
                    "cpi_guard",
                    "interest_bearing",
                    "confidential_transfer",
                    "confidential_transfer_fee",
                )
            ]
        },
        "assets": assets,
    }


def _reviewed_asset(
    symbol: str,
    mint: str,
    decimals: int,
    asset_class: str,
    *,
    token_program: str = "legacy-spl-token",
    token_program_id: str = LEGACY_SPL_TOKEN_PROGRAM_ID,
    extensions: list[str] | None = None,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "mint": mint,
        "cluster": "mainnet-beta",
        "token_program": token_program,
        "token_program_id": token_program_id,
        "decimals": decimals,
        "asset_class": asset_class,
        "admission": "tradable",
        "provenance": "reviewed test fixture",
        "rpc_evidence": _evidence(),
        "authority_evidence": _evidence(),
        "extensions": [] if extensions is None else extensions,
        "oracle_evidence": None,
        "redemption_evidence": None,
        "reviewed": True,
        "reviewer": "operator",
    }


def _evidence() -> dict[str, object]:
    return {
        "status": "reviewed",
        "slot": _TSLOT,
        "sha256": _SHA,
        "source": "fixture",
        "reviewer": "operator",
    }


def _universe_payload(base_mint: str, intermediate_mint: str) -> dict[str, object]:
    return {
        "schema_version": "test.discovery-universe.v1",
        "pairs": [
            {
                "pair_id": "test-pair",
                "base_mint": base_mint,
                "intermediate_mint": intermediate_mint,
                "required": True,
            }
        ],
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
