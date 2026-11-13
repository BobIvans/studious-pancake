"""R02-CAP-A: offline replay, dossier cross-check and financing-port wiring.

Replays the pinned offline SDK pack verifier, cross-checks module constants
against the pinned TokenReserve dossier JSON, binds the reader evidence into
the existing financing port (read-only, fail-closed), and guards the reader
against transport/signer imports. Zero network.
"""

from __future__ import annotations

from dataclasses import replace
import importlib.util
import json
from pathlib import Path

import pytest

from src.lending.financing import FinancingContractError, FinancingEvidence
from src.lending.agg03_financing_ports import JupiterLendFinancingPort
from src.lending.jupiter_lend import (
    JUPITER_LEND_FLASHLOAN_PROGRAM_ID,
    JUPITER_LEND_LIQUIDITY_IDL_BLOB,
    JUPITER_LEND_LIQUIDITY_IDL_NAME,
    JUPITER_LEND_LIQUIDITY_IDL_VERSION,
    JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
    JUPITER_LEND_LIQUIDITY_UPSTREAM_COMMIT,
    READER_DECODER_GENERATION,
    READER_EXECUTION_AUTHORITY,
    TOKEN_RESERVE_ACCOUNT_LEN,
    TOKEN_RESERVE_DISCRIMINATOR,
    JupiterLendReserveCapacityObservation,
)

from tests.test_r02_cap_a_reader import Fixture, REPO_ROOT, PINNED_DOSSIER

OFFLINE_ROOT = (
    REPO_ROOT / "docs/roadmap/r02-capacity-recovery-2026-10-08/offline"
)


def _fixture_observation() -> JupiterLendReserveCapacityObservation:
    return Fixture().observation


def test_pinned_offline_reference_integrity_passes() -> None:
    spec = importlib.util.spec_from_file_location(
        "r02_cap_a_verify_offline", OFFLINE_ROOT / "verify_offline.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.validate()
    assert result["status"] == "OFFLINE_REFERENCE_INTEGRITY_PASS"
    assert result["jupiter_bytes"] == 192
    assert result["live_readers_qualified"] == 0
    assert result["execution_authority"] == "NONE"
    assert result["network_requests"] == 0


def test_module_constants_match_pinned_dossier_json() -> None:
    layout = json.loads(PINNED_DOSSIER.read_text(encoding="utf-8"))
    assert layout["source_pin"] == (
        "jup-ag/jupiter-lend@" + JUPITER_LEND_LIQUIDITY_UPSTREAM_COMMIT
    )
    assert layout["source_blob"] == JUPITER_LEND_LIQUIDITY_IDL_BLOB
    assert layout["idl_name"] == JUPITER_LEND_LIQUIDITY_IDL_NAME
    assert layout["idl_version"] == JUPITER_LEND_LIQUIDITY_IDL_VERSION
    assert layout["owner_program_id"] == str(JUPITER_LEND_LIQUIDITY_PROGRAM_ID)
    assert bytes(layout["discriminator"]) == TOKEN_RESERVE_DISCRIMINATOR
    assert layout["account_size_bytes"] == TOKEN_RESERVE_ACCOUNT_LEN
    assert len(layout["fields"]) == 17
    assert layout["scope"] == "layout_only_not_capacity_proof"
    assert layout["execution_authority"] == "NONE"
    assert "exact PDA mint binding" in layout["requires_additional"]
    assert "SPL vault token account amount and token program owner" in (
        layout["requires_additional"]
    )


def test_financing_port_binds_reader_evidence_and_fails_closed() -> None:
    obs = _fixture_observation()
    evidence = FinancingEvidence(
        lender_id="jupiter-lend",
        program_id=str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID),
        deployment_generation=1,
        evidence_sha256=obs.evidence_digest,
        decoder_identity=obs.decoder_identity,
        decoder_generation=obs.decoder_generation,
    )
    port = JupiterLendFinancingPort(evidence)
    assert port.lender_id == "jupiter-lend"
    assert port.execution_conformance_verified is True
    # No snapshot exists offline (admission is typed BLOCKED), so prepare must
    # fail closed instead of fabricating one.
    with pytest.raises(FinancingContractError, match="JUPITER_LEND_SNAPSHOT_REQUIRED"):
        port.prepare(
            snapshot=object(),
            amount=1,
            destination_account="DeADBEEF00000000000000000000000000000000000000000000000000000000",
            repayment_source_account="DeADBEEF00000000000000000000000000000000000000000000000000000000",
            minimum_terminal_balance=1,
        )
    with pytest.raises(FinancingContractError, match="FINANCING_PROGRAM_MISMATCH"):
        JupiterLendFinancingPort(replace(evidence, program_id=str(obs.reserve_pda)))
    with pytest.raises(FinancingContractError, match="FINANCING_LENDER_MISMATCH"):
        JupiterLendFinancingPort(replace(evidence, lender_id="kamino"))


def test_reader_evidence_digest_binds_decoder_identity_and_bytes() -> None:
    obs = _fixture_observation()
    tampered = replace(obs, decoder_generation=READER_DECODER_GENERATION + 1)
    assert tampered.evidence_digest != obs.evidence_digest
    tampered = replace(obs, execution_authority="SOME")
    assert tampered.evidence_digest != obs.evidence_digest
    # Execution authority stays NONE on the real observation.
    assert obs.execution_authority == READER_EXECUTION_AUTHORITY


def test_reader_module_has_no_transport_or_signer_imports() -> None:
    source = (
        REPO_ROOT / "src/lending/jupiter_lend.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "import httpx",
        "import aiohttp",
        "import requests",
        "import urllib",
        "import socket",
        "import subprocess",
        "import websockets",
        "from solders.keypair",
        "Keypair",
    )
    for token in forbidden:
        assert token not in source, f"forbidden transport/signer token: {token}"


def test_offline_observation_replays_without_promotion() -> None:
    obs = _fixture_observation()
    record = obs.evidence_record()
    restored = json.loads(json.dumps(record))
    assert restored["evidence_sha256"] == obs.evidence_digest
    assert restored["status"] == "BLOCKED_LIVE_STATE"
    assert restored["observation"]["effective_capacity_base_units"] is None
    assert restored["observation"]["sign_enabled"] is False
    assert restored["observation"]["send_enabled"] is False
    assert restored["observation"]["execution_authority"] == "NONE"
    assert restored["observation"]["slot_provenance"] == "OFFLINE_FIXTURE_NOT_ROOTED"
    assert set(restored["observation"]["blockers"]) == {
        "MISSING_EFFECTIVE_FLASH_CAP",
        "LIVE_ROOTED_RPC_NOT_AUTHORIZED",
    }
