from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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
        "POST",
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


def bundle(**kw):
    p = kw.pop("pin", pin())
    protected = kw.pop("protected_workflow", True)
    cred = kw.pop("credentialed_probe", True)
    return evidence_bundle_from_probe(
        p,
        {
            "request": {"apiKey": "secret", "url": "https://api.jup.ag/swap/v2/build"},
            "response": {"ok": True},
        },
        (port(),),
        protected_workflow=protected,
        credentialed_probe=cred,
        captured_unix_seconds=NOW,
        now_unix_seconds=NOW,
        **kw,
    )


def test_admits_fresh_probe_and_keeps_live_sender_signer_disabled():
    a = evaluate_admission(bundle())
    assert a.decision == AdmissionDecision.ADMITTED
    assert not a.live_enabled and not a.sender_enabled and not a.signer_enabled


def test_documentation_only_blocks():
    r = evaluate_admission(
        bundle(protected_workflow=False, credentialed_probe=False)
    ).reason_codes
    assert "PROBE_NOT_PROTECTED_WORKFLOW" in r
    assert "PROBE_NOT_CREDENTIALED" in r


def test_missing_probe_and_runtime_port_block():
    b = bundle()
    assert "PROTECTED_PROBE_MISSING" in evaluate_admission(
        type(b)(**{**b.__dict__, "probe": None})
    ).reason_codes
    assert "NO_ACTIVE_RUNTIME_PORT" in evaluate_admission(
        type(b)(**{**b.__dict__, "runtime_ports": ()})
    ).reason_codes


def test_expiry_drift_credential_program_and_quorum_revoke():
    b = bundle()
    assert "EVIDENCE_EXPIRED" in evaluate_admission(
        type(b)(**{**b.__dict__, "now_unix_seconds": NOW + 4000})
    ).reason_codes
    assert "CONTRACT_DRIFT_DETECTED" in evaluate_admission(
        type(b)(**{**b.__dict__, "contract_drift_detected": True})
    ).reason_codes
    assert "CREDENTIAL_FAILURE" in evaluate_admission(
        type(b)(**{**b.__dict__, "credential_failure": True})
    ).reason_codes
    assert "PROGRAM_IDENTITY_CHANGED" in evaluate_admission(
        type(b)(**{**b.__dict__, "program_identity_changed": True})
    ).reason_codes
    assert "RPC_QUORUM_DISAGREED" in evaluate_admission(
        type(b)(**{**b.__dict__, "rpc_quorum_disagreed": True})
    ).reason_codes


def test_jupiter_adapter_uses_v2_build_and_legacy_blocks():
    spec = JupiterV2BuildAdapter.build_request({"quoteResponse": {"routePlan": []}}, "key")
    assert spec.url.endswith("/swap/v2/build")
    assert spec.purpose == "jupiter_final_build"
    assert legacy_jupiter_path_detected("/swap/v1/quote")
    assert "JUPITER_LEGACY_ENDPOINT_PINNED" in evaluate_admission(
        bundle(pin=pin(endpoint="/swap/v1/quote"))
    ).reason_codes


def test_jupiter_rejects_legacy_swap_transaction_response():
    class T:
        def request(self, spec):
            return HttpResponseEvidence(200, {}, {"swapTransaction": "abc"}, 1, 10)

    with pytest.raises(ProviderConformanceError):
        JupiterV2BuildAdapter(T()).build({"quoteResponse": {}})


def test_solana_rpc_context_and_method_limits():
    req = SolanaRpcEvidenceService.rpc_request(
        "https://rpc", "isBlockhashValid", ["h", {"minContextSlot": 5}]
    )
    assert req.json_body["method"] == "isBlockhashValid"
    assert SolanaRpcEvidenceService.validate_context({"result": {"context": {"slot": 9}}}, 5) == 9
    with pytest.raises(ProviderConformanceError):
        SolanaRpcEvidenceService.rpc_request("x", "sendTransaction", [])
    with pytest.raises(ProviderConformanceError):
        SolanaRpcEvidenceService.validate_context({"result": {"context": {"slot": 4}}}, 5)


def test_jito_is_readonly_only():
    req = JitoReadOnlyAdapter.get_tip_accounts_request("https://jito")
    assert req.json_body["method"] == "getTipAccounts"
    JitoReadOnlyAdapter.reject_submission_method("getTipAccounts")
    with pytest.raises(ProviderConformanceError):
        JitoReadOnlyAdapter.reject_submission_method("sendBundle")


def test_program_observation_and_marginfi_hash_required():
    obs = {
        "program_id": "p",
        "programdata_address": "pd",
        "executable": True,
        "owner": "loader",
        "slot": 1,
    }
    assert len(ProgramEvidenceProducer.validate_program_observation(obs)) == 64
    p = pin(ProviderName.MARGINFI, "marginfi-program")
    assert "DEPLOYED_PROGRAM_OBSERVATION_MISSING" in evaluate_admission(bundle(pin=p)).reason_codes
    assert "DEPLOYED_PROGRAM_OBSERVATION_MISSING" not in evaluate_admission(
        bundle(pin=p, observed_program_hash=H)
    ).reason_codes


def test_solana_rpc_quorum_required():
    p = pin(ProviderName.SOLANA_RPC, "https://rpc")
    assert "RPC_QUORUM_HASH_MISSING" in evaluate_admission(bundle(pin=p)).reason_codes
    assert "RPC_QUORUM_HASH_MISSING" not in evaluate_admission(
        bundle(pin=p, rpc_quorum_hash=H)
    ).reason_codes


def test_redacted_fixture_removes_secret_values(tmp_path):
    path = tmp_path / "f.json"
    h = write_redacted_fixture(
        path,
        ProviderName.JUPITER,
        {
            "Authorization": "Bearer abcdefghijklmnopqrstuvwxyz",
            "url": "https://x/?api_key=secret123",
        },
    )
    text = path.read_text()
    assert len(h) == 64
    assert "secret123" not in text
    assert "Bearer" not in text
    assert "<redacted>" in text


def test_controller_requires_admitted_active_port():
    c = ProviderAdmissionController([bundle()])
    assert c.require_runtime_port(ProviderName.JUPITER, "jupiter_v2_build").consumer == "consumer"
    with pytest.raises(ProviderConformanceError):
        c.require_runtime_port(ProviderName.JUPITER, "missing")


def test_probe_plans_cover_provider_set_and_no_submission_or_legacy():
    plans = protected_probe_plans()
    providers = {p["provider"] for p in plans}
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
    b = bundle()
    f = tmp_path / "bundle.json"
    f.write_text(
        json.dumps(
            {
                "schema_version": b.schema_version,
                "contract_pin": b.contract_pin.__dict__,
                "probe": b.probe.__dict__,
                "runtime_ports": [p.__dict__ for p in b.runtime_ports],
                "now_unix_seconds": b.now_unix_seconds,
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
            str(f),
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
