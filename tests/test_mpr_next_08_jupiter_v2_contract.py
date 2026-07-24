from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.verify_mpr_next_08_jupiter_v2_contract import (
    JupiterV2ContractEvidence,
    verify_mpr_next_08_jupiter_v2_contract,
)

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _product_contract(paths: list[str] | None = None) -> dict[str, object]:
    return {
        "schema_version": "pr195.product-contract.v1",
        "endpoints": {
            "jupiter": {
                "origin": "https://api.jup.ag",
                "paths": paths or ["/price/v3", "/swap/v2/build"],
            }
        },
    }


def _external_contracts(path: str = "/swap/v2/build") -> dict[str, object]:
    return {
        "providers": {
            "jupiter_router": {
                "status": "active",
                "base_url": "https://api.jup.ag",
                "instruction_endpoint": {"method": "GET", "path": path},
                "sole_active_entry_point": (
                    "src.providers.jupiter.router.JupiterRouterAdapter"
                ),
            }
        }
    }


def _production_surface() -> dict[str, object]:
    return {
        "schema_version": "pr194.production-surface.v1",
        "forbidden": {
            "module_files": [
                "src/legacy_arb_bot.py",
                "src/execution/live_control.py",
                "src/execution/shadow.py",
            ],
            "package_prefixes": ["src/ingest/", "src/execution/senders/"],
        },
    }


def _quarantine() -> dict[str, object]:
    return {
        "schema_version": "mpr-next-08.jupiter-endpoint-quarantine.v1",
        "active_contract": {
            "adapter": "src.providers.jupiter.router.JupiterRouterAdapter",
            "method": "GET",
            "origin": "https://api.jup.ag",
            "path": "/swap/v2/build",
        },
        "forbidden_endpoint_markers": [
            "/swap/v1",
            "/swap/v2/quote",
            "/swap/v2/swap",
            "/swap/v2/swap-instructions",
        ],
        "quarantined_paths": [
            {"boundary": "module_file", "path": "src/legacy_arb_bot.py"},
            {"boundary": "module_file", "path": "src/execution/live_control.py"},
            {"boundary": "module_file", "path": "src/execution/shadow.py"},
            {"boundary": "package_prefix", "path": "src/ingest/"},
            {"boundary": "package_prefix", "path": "src/execution/senders/"},
        ],
    }


def _write_fixture_repo(
    root: Path,
    *,
    product_paths: list[str] | None = None,
    docs_path: str = "/swap/v2/build",
    active_source: str = "ACTIVE_ENDPOINT = '/swap/v2/build'\n",
    verify_repo_runs_gate: bool = True,
) -> None:
    contract_payload = json.dumps(_product_contract(product_paths), sort_keys=True)
    _write(root / "config/product_contract_pr195.json", contract_payload)
    _write(root / "src/resources/product_contract_pr195.json", contract_payload)
    _write(
        root / "docs/external_contracts.yaml",
        yaml.safe_dump(_external_contracts(docs_path), sort_keys=True),
    )
    _write(
        root / "src/providers/jupiter/router.py",
        (
            'JUPITER_ROUTER_ENDPOINT = "/swap/v2/build"\n\n'
            "async def build(session):\n"
            "    return session.get(JUPITER_ROUTER_ENDPOINT)\n"
        ),
    )
    _write(root / "src/active_runtime.py", active_source)
    _write(root / "src/legacy_arb_bot.py", "URL = '/swap/v1/quote'\n")
    _write(root / "src/execution/live_control.py", "LIVE = False\n")
    _write(root / "src/execution/shadow.py", "SHADOW = True\n")
    _write(root / "src/ingest/jupiter_api_client.py", "URL = '/swap/v2/quote'\n")
    _write(root / "src/execution/senders/disabled.py", "SEND = False\n")
    _write(
        root / "src/resources/production_surface_manifest.json",
        json.dumps(_production_surface(), sort_keys=True),
    )
    _write(
        root / "config/jupiter_endpoint_quarantine.json",
        json.dumps(_quarantine(), sort_keys=True),
    )
    verify_repo = (
        "python scripts/verify_mpr_next_08_jupiter_v2_contract.py --json\n"
        if verify_repo_runs_gate
        else "python scripts/verify_repo.py\n"
    )
    _write(root / "scripts/verify_repo.py", verify_repo)


def test_mpr_next_08_accepts_current_checkout() -> None:
    evidence = verify_mpr_next_08_jupiter_v2_contract(ROOT)

    assert isinstance(evidence, JupiterV2ContractEvidence)
    assert evidence.accepted is True
    assert evidence.blockers == ()
    assert evidence.docs_endpoint == "/swap/v2/build"
    assert evidence.router_endpoint == "/swap/v2/build"
    assert "src/ingest/" in evidence.quarantined_paths


def test_mpr_next_08_allows_legacy_endpoints_only_inside_quarantine(
    tmp_path: Path,
) -> None:
    _write_fixture_repo(tmp_path)

    evidence = verify_mpr_next_08_jupiter_v2_contract(tmp_path)

    assert evidence.accepted is True
    assert evidence.blockers == ()


def test_mpr_next_08_rejects_active_legacy_endpoint(tmp_path: Path) -> None:
    _write_fixture_repo(tmp_path, active_source="URL = '/swap/v1/quote'\n")

    evidence = verify_mpr_next_08_jupiter_v2_contract(tmp_path)

    assert evidence.accepted is False
    assert any(
        blocker.startswith("FORBIDDEN_ACTIVE_JUPITER_ENDPOINT:src/active_runtime.py")
        for blocker in evidence.blockers
    )


def test_mpr_next_08_rejects_product_contract_path_drift(tmp_path: Path) -> None:
    _write_fixture_repo(tmp_path, product_paths=["/swap/v1/quote"])

    evidence = verify_mpr_next_08_jupiter_v2_contract(tmp_path)

    assert evidence.accepted is False
    assert "PRODUCT_CONTRACT_JUPITER_PATH_SET_MISMATCH" in evidence.blockers


def test_mpr_next_08_rejects_docs_endpoint_drift(tmp_path: Path) -> None:
    _write_fixture_repo(tmp_path, docs_path="/swap/v2/quote")

    evidence = verify_mpr_next_08_jupiter_v2_contract(tmp_path)

    assert evidence.accepted is False
    assert "EXTERNAL_CONTRACTS_JUPITER_PATH_MISMATCH" in evidence.blockers


def test_mpr_next_08_rejects_missing_verify_repo_wiring(tmp_path: Path) -> None:
    _write_fixture_repo(tmp_path, verify_repo_runs_gate=False)

    evidence = verify_mpr_next_08_jupiter_v2_contract(tmp_path)

    assert evidence.accepted is False
    assert "VERIFY_REPO_DOES_NOT_RUN_MPR_NEXT_08" in evidence.blockers
