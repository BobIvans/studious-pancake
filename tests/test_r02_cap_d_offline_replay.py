"""R02-CAP-D: offline replay, pin cross-checks and financing-port wiring.

Replays the pinned offline SDK pack verifier, cross-checks reader constants
against the pinned PR-028/PR-055/p0 resources, proves the financing ports are
consumed read-only with no MarginFi port prescribed, and guards the reader
against transport/signer imports. Zero network, zero signing.
"""

from __future__ import annotations

from dataclasses import replace
import importlib.util
import json
from pathlib import Path

import pytest

from src.lending.agg03_financing_ports import JupiterLendFinancingPort
from src.lending.financing import FinancingContractError, FinancingEvidence
from src.lending.jupiter_lend import JUPITER_LEND_FLASHLOAN_PROGRAM_ID
from src.providers.marginfi.bank_discovery import (
    BLOCKER_FINANCING_PORT_NOT_PRESCRIBED,
    BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED,
    BLOCKER_MISSING_EFFECTIVE_FLASH_CAP,
    BLOCKER_OPERATOR_ACCOUNT_INPUT_REQUIRED,
    LIQUIDITY_VAULT_AUTHORITY_SEED,
    READER_DECODER_GENERATION,
    READER_EXECUTION_AUTHORITY,
    READER_WALLETLESS_MODE,
    admit_bank_financing_snapshot,
    load_bank_reader_pins,
    load_p0_discovery_facts,
)

from tests.test_r02_cap_d_reader import MAIN_GROUP, PROGRAM_ID, REPO_ROOT, Fixture

OFFLINE_ROOT = REPO_ROOT / "docs/roadmap/r02-capacity-recovery-2026-10-08/offline"
P0_FACTS = OFFLINE_ROOT / "p0_public_discovery_facts.json"
PR028_PIN = REPO_ROOT / "src/resources/marginfi_pr028.json"
PR055_PIN = REPO_ROOT / "src/resources/marginfi_pr055.json"


def test_pinned_offline_reference_integrity_passes() -> None:
    spec = importlib.util.spec_from_file_location(
        "r02_cap_d_verify_offline", OFFLINE_ROOT / "verify_offline.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.validate()
    assert result["status"] == "OFFLINE_REFERENCE_INTEGRITY_PASS"
    assert result["live_readers_qualified"] == 0
    assert result["execution_authority"] == "NONE"
    assert result["network_requests"] == 0


def test_p0_discovery_facts_match_offline_pack() -> None:
    raw = json.loads(P0_FACTS.read_text(encoding="utf-8"))
    facts = load_p0_facts_validated()
    assert facts.source_pin == raw["source_pin"]
    assert facts.source_git_version == raw["source_git_version"]
    assert facts.package == raw["package"]
    assert facts.protocol_idl == raw["protocol_idl"]
    assert facts.status_without_public_wallet == raw["status_without_public_wallet"]
    assert facts.walletless_mode == raw["walletless_mode"]
    assert facts.bank_only_reads_allowed == raw["bank_only_reads_allowed"]
    assert facts.public_wallet_address_optional == raw["public_wallet_address_optional"]
    assert (
        facts.public_marginfi_account_optional
        == raw["public_marginfi_account_optional"]
    )
    assert facts.execution_authority == raw["execution_authority"]
    assert facts.raw["account_init_required_if_missing"] is True
    # Wallet-free mandate: forbidden methods stay forbidden in the reader.
    assert "createMarginfiAccountTx" in raw["forbidden"]
    assert "sendTransaction" in raw["forbidden"]
    assert "signTransaction" in raw["forbidden"]


def load_p0_facts_validated():
    return load_bank_reader_pins().facts


def test_bank_pin_cross_checks_pr028_pr055() -> None:
    pr028 = json.loads(PR028_PIN.read_text(encoding="utf-8"))
    pr055 = json.loads(PR055_PIN.read_text(encoding="utf-8"))
    pins = load_bank_reader_pins()
    assert pr028["program_id"] == PROGRAM_ID == pins.program_id
    assert pr055["program_id"] == PROGRAM_ID
    assert pr055["main_group"] == MAIN_GROUP == pins.main_group
    assert pr055["source"]["layout_manifest"] == "src/resources/marginfi_pr028.json"
    bank_layout = pr028["account_layouts"]["bank"]
    assert bank_layout["struct_size"] == 1856
    assert bank_layout["offsets"]["protocol_origination_fee"] == 472
    assert bank_layout["offsets"]["borrow_limit"] == 768
    assert bank_layout["offsets"]["flags"] == 832
    assert pr028["constants"]["liquidity_vault_authority_seed"] == (
        LIQUIDITY_VAULT_AUTHORITY_SEED.decode()
    )
    assert pr028["constants"]["i80f48_fractional_bits"] == 48
    assert pr028["flags"]["bank_is_token_2022"] == 128
    assert pr028["conformance"]["supported_oracle_setups"] == [3, 4]
    assert pr028["conformance"]["supported_asset_tags"] == [0, 1]
    assert pr028["conformance"]["execution_mode"] == "shadow-only"
    assert pr055["source"]["source_commit"] == (
        "d33e649e415c354cc2a1e3c49131725552d69ba0"
    )
    promotion = pr055["promotion"]
    assert promotion["execution_conformance_verified"] is False
    assert promotion["live_allowed"] is False
    assert promotion["maximum_capability"].startswith("blocked")


def test_financing_ports_remain_read_only_and_marginfi_absent() -> None:
    # agg03_financing_ports is imported read-only (never edited by CAP-D); the
    # registered lenders stay Jupiter Lend and Slumlord only.
    obs = Fixture().observation
    marginfi_evidence = FinancingEvidence(
        lender_id="marginfi",
        program_id=PROGRAM_ID,
        deployment_generation=1,
        evidence_sha256=obs.evidence_digest,
        decoder_identity=obs.decoder_identity,
        decoder_generation=obs.decoder_generation,
    )
    assert marginfi_evidence.lender_id == "marginfi"
    # No port consumes the marginfi evidence identity this wave: the Jupiter
    # port rejects it at construction.
    assert JupiterLendFinancingPort.lender_id == "jupiter-lend"
    with pytest.raises(FinancingContractError, match="FINANCING_LENDER_MISMATCH"):
        JupiterLendFinancingPort(marginfi_evidence)
    # The registered ports still fail closed without a real qualified
    # snapshot, which CAP-D never fabricates.
    jupiter_evidence = FinancingEvidence(
        lender_id="jupiter-lend",
        program_id=str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID),
        deployment_generation=1,
        evidence_sha256=obs.evidence_digest,
        decoder_identity=obs.decoder_identity,
        decoder_generation=obs.decoder_generation,
    )
    port = JupiterLendFinancingPort(jupiter_evidence)
    with pytest.raises(FinancingContractError, match="JUPITER_LEND_SNAPSHOT_REQUIRED"):
        port.prepare(
            snapshot=object(),
            amount=1,
            destination_account=(
                "DeADBEEF00000000000000000000000000000000000000000000000000000000"
            ),
            repayment_source_account=(
                "DeADBEEF00000000000000000000000000000000000000000000000000000000"
            ),
            minimum_terminal_balance=1,
        )
    admission = admit_bank_financing_snapshot(
        observation=obs,
        asset_id="synthetic:offline-fixture-asset",
        state_fingerprint=("c" * 64),
    )
    assert admission.snapshot is None
    assert BLOCKER_FINANCING_PORT_NOT_PRESCRIBED in admission.blockers
    assert BLOCKER_MISSING_EFFECTIVE_FLASH_CAP in admission.blockers


def test_reader_module_has_no_transport_or_signer_imports() -> None:
    source = (REPO_ROOT / "src/providers/marginfi/bank_discovery.py").read_text(
        encoding="utf-8"
    )
    # Transport/signer/sender import surface must stay empty; typed negative
    # evidence may reference forbidden API names in prose, so the scan targets
    # real import and keypair usage only.
    forbidden = (
        "import httpx",
        "import aiohttp",
        "import requests",
        "import urllib",
        "import socket",
        "import subprocess",
        "import websockets",
        "from solders.keypair",
        "Keypair(",
        "send_transaction(",
        "sendTransaction(",
        "create_marginfi_account(",
        "createMarginfiAccountTx(",
        'find_program_address(\n    [b"marginfi_account"',
    )
    for token in forbidden:
        assert token not in source, f"forbidden transport/signer token: {token}"
    import_lines = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    assert all(
        not any(
            module in line
            for module in (
                "httpx",
                "aiohttp",
                "requests",
                "urllib",
                "socket",
                "websockets",
                "keypair",
            )
        )
        for line in import_lines
    )


def test_offline_replay_without_promotion() -> None:
    obs = Fixture().observation
    record = obs.evidence_record()
    restored = json.loads(json.dumps(record))
    assert restored["evidence_sha256"] == obs.evidence_digest
    assert restored["status"] == "BLOCKED_LIVE_STATE"
    assert restored["observation"]["effective_capacity_base_units"] is None
    assert restored["observation"]["sign_enabled"] is False
    assert restored["observation"]["send_enabled"] is False
    assert restored["observation"]["account_creation_attempted"] is False
    assert restored["observation"]["execution_authority"] == "NONE"
    assert restored["observation"]["slot_provenance"] == "OFFLINE_FIXTURE_NOT_ROOTED"
    assert restored["observation"]["walletless_mode"] == READER_WALLETLESS_MODE
    assert set(restored["observation"]["blockers"]) == {
        BLOCKER_MISSING_EFFECTIVE_FLASH_CAP,
        BLOCKER_LIVE_ROOTED_RPC_NOT_AUTHORIZED,
    }
    tampered = replace(obs, decoder_generation=READER_DECODER_GENERATION + 1)
    assert tampered.evidence_digest != obs.evidence_digest
    assert obs.execution_authority == READER_EXECUTION_AUTHORITY == "NONE"
    # Account eligibility stays a separate, operator-input-gated verdict.
    eligibility = Fixture().pins
    assert eligibility.facts.status_without_public_wallet == (
        "P0_EXISTING_ACCOUNT_UNKNOWN_READ_BANKS_ONLY"
    )
    assert (
        BLOCKER_OPERATOR_ACCOUNT_INPUT_REQUIRED
        not in restored["observation"]["blockers"]
    )
