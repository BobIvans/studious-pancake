from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.verify_mpr_next_08_jupiter_v2_contract import (
    JupiterV2ContractEvidence,
    verify_mpr_next_08_jupiter_v2_contract,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATHS = (
    "src/mpr_close_03_verifiers.py",
    "src/provider_protocol_conformance_mpr_next_03.py",
    "src/providers/conformance/mega_b2.py",
    "src/providers/protocol_conformance.py",
    "src/resources/production_debt_pr149.json",
)


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
        "policy_reference_paths": [
            {"path": path, "reason": "offline negative contract reference"}
            for path in POLICY_PATHS
        ],
        "quarantined_paths": [
            {"boundary": "module_file", "path": "src/legacy_arb_bot.py"},
            {"boundary": "module_file", "path": "src/execution/live_control.py"},
            {"boundary": "module_file", "path": "src/execution/shadow.py"},
            {"boundary": "package_prefix", "path": "src/ingest/"},
            {"boundary": "package_prefix", "path": "src/execution/senders/"},
        ],
    }


def _mega_b2_source(method: str = "GET") -> str:
    return (
        'CURRENT_JUPITER_BUILD_PATH = "/swap/v2/build"\n'
        "JUPITER_BUILD_REQUIRED_PARAMETERS = ('inputMint', 'outputMint', 'amount', 'taker')\n"
        "JUPITER_BUILD_METHOD_NOT_GET = 'blocked'\n"
        "LEGACY_JUPITER_PATHS = ('/swap/v1/quote', '/swap/v2/quote')\n\n"
        "class HttpRequestSpec:\n"
        "    def __init__(self, *args):\n"
        "        self.args = args\n\n"
        "class JupiterV2BuildAdapter:\n"
        "    @staticmethod\n"
        "    def build_request():\n"
        f"        return HttpRequestSpec('{method}', '/swap/v2/build')\n"
    )


def _write_fixture_repo(
    root: Path,
    *,
    product_paths: list[str] | None = None,
    docs_path: str = "/swap/v2/build",
    active_source: str = "ACTIVE_ENDPOINT = '/swap/v2/build'\n",
    verify_repo_runs_gate: bool = True,
    mega_b2_method: str = "GET",
    policy_network_token: str | None = None,
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
        root / "src/mpr_close_03_verifiers.py",
        "LEGACY = '/swap/v1/quote'\n" + (policy_network_token or ""),
    )
    _write(
        root / "src/provider_protocol_conformance_mpr_next_03.py",
        "FORBIDDEN = ('/swap/v1/quote',)\n",
    )
    _write(
        root / "src/providers/conformance/mega_b2.py",
        _mega_b2_source(mega_b2_method),
    )
    _write(
        root / "src/providers/protocol_conformance.py",
        "STALE = ('/swap/v2/swap-instructions',)\n",
    )
    _write(
        root / "src/resources/production_debt_pr149.json",
        json.dumps({"observed": "/swap/v2/quote"}),
    )
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
    assert evidence.mega_b2_method == "GET"
    assert "src/ingest/" in evidence.quarantined_paths
    assert "src/providers/protocol_conformance.py" in evidence.policy_reference_paths


def test_mpr_next_08_allows_deprecated_markers_only_in_declared_boundaries(
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


def test_mpr_next_08_rejects_policy_reference_with_direct_network(
    tmp_path: Path,
) -> None:
    _write_fixture_repo(tmp_path, policy_network_token="import requests\n")

    evidence = verify_mpr_next_08_jupiter_v2_contract(tmp_path)

    assert evidence.accepted is False
    assert any(
        blocker.startswith(
            "POLICY_REFERENCE_DIRECT_NETWORK:src/mpr_close_03_verifiers.py"
        )
        for blocker in evidence.blockers
    )


def test_mpr_next_08_rejects_mega_b2_post_contract(tmp_path: Path) -> None:
    _write_fixture_repo(tmp_path, mega_b2_method="POST")

    evidence = verify_mpr_next_08_jupiter_v2_contract(tmp_path)

    assert evidence.accepted is False
    assert "MEGA_B2_JUPITER_METHOD_MISMATCH" in evidence.blockers


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
