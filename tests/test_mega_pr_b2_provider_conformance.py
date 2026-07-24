from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src.providers.conformance.mega_b2 import *

H = "a" * 64
H2 = "b" * 64
NOW = 1_800_000_000


def pin(provider=ProviderName.JUPITER, endpoint=CURRENT_JUPITER_BUILD_PATH):
    return ExternalContractPin(
        provider,
        "https://docs.example/provider",
        NOW - 10,
        endpoint,
        "GET" if provider == ProviderName.JUPITER else "POST",
        "protected_secret",
        "mainnet-beta",
        H,
        H2,
        1_000_000,
        3600,
        "shared_quota",
    )


def port():
    return make_runtime_port("jupiter_v2_build", "producer", "consumer", "store")


def jupiter_payload():
    return {
        "inputMint": "So11111111111111111111111111111111111111112",
        "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "amount": "1000000",
        "taker": "11111111111111111111111111111111",
        "slippageBps": 50,
        "maxAccounts": 64,
        "wrapAndUnwrapSol": False,
        "forJitoBundle": False,
    }


def bundle(**kw):
    contract_pin = kw.pop("pin", pin())
    protected = kw.pop("protected_workflow", True)
    credentialed = kw.pop("credentialed_probe", True)
    return evidence_bundle_from_probe(
        contract_pin,
        {
            "request": {
                "apiKey": "secret",
                "url": "https://api.jup.ag/swap/v2/build",
            },
            "response": {"ok": True},
        },
        (port(),),
        protected_workflow=protected,
        credentialed_probe=credentialed,
        captured_unix_seconds=NOW,
        now_unix_seconds=NOW,
        **kw,
    )


def test_admits_fresh_probe_and_keeps_live_sender_signer_disabled():
    admission = evaluate_admission(bundle())
    assert admission.decision == AdmissionDecision.ADMITTED
    assert not admission.live_enabled
    assert not admission.sender_enabled
    assert not admission.signer_enabled


def test_documentation_only_blocks():
    reasons = evaluate_admission(
        bundle(protected_workflow=False, credentialed_probe=False)
    ).reason_codes
    assert "PROBE_NOT_PROTECTED_WORKFLOW" in reasons
    assert "PROBE_NOT_CREDENTIALED" in reasons


def test_missing_probe_and_runtime_port_block():
    evidence = bundle()
    assert "PROTECTED_PROBE_MISSING" in evaluate_admission(
        type(evidence)(**{**evidence.__dict__, "probe": None})
    ).reason_codes
    assert "NO_ACTIVE_RUNTIME_PORT" in evaluate_admission(
        type(evidence)(**{**evidence.__dict__, "runtime_ports": ()})
    ).reason_codes


def test_expiry_drift_credential_program_and_quorum_revoke():
    evidence = bundle()
    cases = (
        ("now_unix_seconds", NOW + 4000, "EVIDENCE_EXPIRED"),
        ("contract_drift_detected", True, "CONTRACT_DRIFT_DETECTED"),
        ("credential_failure", True, "CREDENTIAL_FAILURE"),
        ("program_identity_changed", True, "PROGRAM_IDENTITY_CHANGED"),
        ("rpc_quorum_disagreed", True, "RPC_QUORUM_DISAGREED"),
    )
    for field_name, value, reason in cases:
        changed = type(evidence)(**{**evidence.__dict__, field_name: value})
        assert reason in evaluate_admission(changed).reason_codes


def test_jupiter_adapter_uses_get_v2_build_query_contract_and_legacy_blocks():
    spec = JupiterV2BuildAdapter.build_request(jupiter_payload(), "key")
    assert spec.url.endswith("/swap/v2/build")
    assert spec.method == "GET"
    assert spec.query_params is not None
    assert spec.query_params["amount"] == "1000000"
    assert spec.query_params["slippageBps"] == "50"
    assert spec.query_params["wrapAndUnwrapSol"] == "false"
    assert spec.headers["x-api-key"] == "key"
    assert spec.purpose == "jupiter_final_build"
    assert legacy_jupiter_path_detected("/swap/v1/quote")
    legacy = evaluate_admission(bundle(pin=pin(endpoint="/swap/v1/quote")))
    assert "JUPITER_LEGACY_ENDPOINT_PINNED" in legacy.reason_codes


def test_jupiter_build_contract_rejects_legacy_payload_and_post_pin():
    with pytest.raises(ProviderConformanceError, match="REQUIRED_PARAMETER_MISSING"):
        JupiterV2BuildAdapter.build_request({"quoteResponse": {"routePlan": []}})
    post_pin = ExternalContractPin(
        ProviderName.JUPITER,
        "https://docs.example/provider",
        NOW - 10,
        CURRENT_JUPITER_BUILD_PATH,
        "POST",
        "protected_secret",
        "mainnet-beta",
        H,
        H2,
        1_000_000,
        3600,
        "shared_quota",
    )
    assert "JUPITER_BUILD_METHOD_NOT_GET" in evaluate_admission(
        bundle(pin=post_pin)
    ).reason_codes


def test_jupiter_rejects_legacy_swap_transaction_response():
    class Transport:
        def request(self, spec):
            return HttpResponseEvidence(200, {}, {"swapTransaction": "abc"}, 1, 10)

    with pytest.raises(ProviderConformanceError):
        JupiterV2BuildAdapter(Transport()).build(jupiter_payload())


def test_solana_rpc_context_and_method_limits():
    request = SolanaRpcEvidenceService.rpc_request(
        "https://rpc",
        "isBlockhashValid",
        ["h", {"minContextSlot": 5}],
    )
    assert request.json_body["method"] == "isBlockhashValid"
    assert (
        SolanaRpcEvidenceService.validate_context(
            {"result": {"context": {"slot": 9}}},
            5,
        )
        == 9
    )
    with pytest.raises(ProviderConformanceError):
        SolanaRpcEvidenceService.rpc_request("x", "sendTransaction", [])
    with pytest.raises(ProviderConformanceError):
        SolanaRpcEvidenceService.validate_context(
            {"result": {"context": {"slot": 4}}},
            5,
        )


def test_jito_is_readonly_only():
    request = JitoReadOnlyAdapter.get_tip_accounts_request("https://jito")
    assert request.json_body["method"] == "getTipAccounts"
    JitoReadOnlyAdapter.reject_submission_method("getTipAccounts")
    with pytest.raises(ProviderConformanceError):
        JitoReadOnlyAdapter.reject_submission_method("sendBundle")


def test_program_observation_and_marginfi_hash_required():
    observation = {
        "program_id": "p",
        "programdata_address": "pd",
        "executable": True,
        "owner": "loader",
        "slot": 1,
    }
    assert len(ProgramEvidenceProducer.validate_program_observation(observation)) == 64
    contract_pin = pin(ProviderName.MARGINFI, "marginfi-program")
    assert "DEPLOYED_PROGRAM_OBSERVATION_MISSING" in evaluate_admission(
        bundle(pin=contract_pin)
    ).reason_codes
    assert "DEPLOYED_PROGRAM_OBSERVATION_MISSING" not in evaluate_admission(
        bundle(pin=contract_pin, observed_program_hash=H)
    ).reason_codes


def test_solana_rpc_quorum_required():
    contract_pin = pin(ProviderName.SOLANA_RPC, "https://rpc")
    assert "RPC_QUORUM_HASH_MISSING" in evaluate_admission(
        bundle(pin=contract_pin)
    ).reason_codes
    assert "RPC_QUORUM_HASH_MISSING" not in evaluate_admission(
        bundle(pin=contract_pin, rpc_quorum_hash=H)
    ).reason_codes


def test_redacted_fixture_removes_secret_values(tmp_path):
    path = tmp_path / "f.json"
    digest = write_redacted_fixture(
        path,
        ProviderName.JUPITER,
        {
            "Authorization": "Bearer abcdefghijklmnopqrstuvwxyz",
            "url": "https://x/?api_key=secret123",
        },
    )
    text = path.read_text()
    assert len(digest) == 64
    assert "secret123" not in text
    assert "Bearer" not in text
    assert "<redacted>" in text


def test_controller_requires_admitted_active_port():
    controller = ProviderAdmissionController([bundle()])
    assert (
        controller.require_runtime_port(
            ProviderName.JUPITER,
            "jupiter_v2_build",
        ).consumer
        == "consumer"
    )
    with pytest.raises(ProviderConformanceError):
        controller.require_runtime_port(ProviderName.JUPITER, "missing")


def test_probe_plans_cover_provider_set_and_no_submission_or_legacy():
    plans = protected_probe_plans()
    providers = {plan["provider"] for plan in plans}
    assert {
        ProviderName.JUPITER,
        ProviderName.SOLANA_RPC,
        ProviderName.JITO_READONLY,
        ProviderName.MARGINFI,
    } <= providers
    rendered = json.dumps(canonical(plans), sort_keys=True)
    assert "sendBundle" not in rendered
    assert "sendTransaction" not in rendered
    assert "/swap/v1" not in rendered
    jupiter_plan = next(
        plan for plan in plans if plan["provider"] == ProviderName.JUPITER
    )
    assert jupiter_plan["request"]["method"] == "GET"
    assert jupiter_plan["request"]["json_body"]["inputMint"]
    assert "quoteResponse" not in jupiter_plan["request"]["json_body"]


def test_cli_plan_and_replay(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(root)}
    plan = subprocess.run(
        [sys.executable, "-m", "src.providers.conformance.mega_b2", "plan"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "jupiter_build" in plan.stdout
    evidence = bundle()
    fixture = tmp_path / "bundle.json"
    fixture.write_text(
        json.dumps(
            {
                "schema_version": evidence.schema_version,
                "contract_pin": evidence.contract_pin.__dict__,
                "probe": evidence.probe.__dict__,
                "runtime_ports": [port.__dict__ for port in evidence.runtime_ports],
                "now_unix_seconds": evidence.now_unix_seconds,
            },
            default=str,
        )
    )
    replay = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.providers.conformance.mega_b2",
            "replay",
            "--bundle",
            str(fixture),
            "--port",
            "jupiter_v2_build",
        ],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert '"decision": "admitted"' in replay.stdout
