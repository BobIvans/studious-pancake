"""MEGA-PR B2 provider evidence and adapter ports.

No network, signing, sender, or live trading side effects live here. Protected
workflows inject bounded transports and write redacted fixtures; runtime code
consumes only admitted evidence bundles.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import StrEnum
from hashlib import sha256
import argparse
import json
from pathlib import Path
import re
from typing import Any, Mapping, Protocol

SCHEMA_VERSION = "mega-pr-b2.external-evidence.v1"
ADMISSION_SCHEMA_VERSION = "mega-pr-b2.provider-admission.v1"
CURRENT_JUPITER_BUILD_PATH = "/swap/v2/build"
LEGACY_JUPITER_PATHS = ("/swap/v1/quote", "/swap/v1/swap", "/swap/v1/swap-instructions", "/swap/v2/quote", "/swap/v2/swap", "/swap/v2/swap-instructions")
SECRET_KEY_RE = re.compile(r"api[-_]?key|authorization|auth|bearer|token|secret|private[-_]?key", re.I)
SECRET_VALUE_RE = re.compile(r"(?i)(bearer\s+[a-z0-9._~+/=-]+|api[-_]?key=[^&\s]+)")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")

class ProviderName(StrEnum):
    JUPITER = "jupiter"; SOLANA_RPC = "solana_rpc"; JITO_READONLY = "jito_readonly"; MARGINFI = "marginfi"; KAMINO = "kamino"; HELIUS = "helius"
class AdmissionDecision(StrEnum):
    ADMITTED = "admitted"; BLOCKED = "blocked"
class ProviderConformanceError(ValueError): pass

@dataclass(frozen=True)
class RuntimeEvidencePort:
    port_name: str; producer: str; consumer: str; durable_store: str; replay_command: str; active_in_runtime: bool = True
@dataclass(frozen=True)
class ExternalContractPin:
    provider: ProviderName | str; official_source_url: str; reviewed_unix_seconds: int; endpoint_or_program: str; method: str; auth_mode: str; cluster: str; request_schema_hash: str; response_schema_hash: str; max_response_bytes: int; freshness_ttl_seconds: int; rate_limit_contract: str
@dataclass(frozen=True)
class ProtectedProbeEvidence:
    provider: ProviderName | str; probe_id: str; captured_unix_seconds: int; protected_workflow: bool; credentialed_probe: bool; request_hash: str; response_hash: str; redacted_fixture_hash: str; raw_secret_material_present: bool = False; raw_url_with_query_secret_present: bool = False; raw_provider_error_present: bool = False
@dataclass(frozen=True)
class ExternalEvidenceBundle:
    schema_version: str; contract_pin: ExternalContractPin; probe: ProtectedProbeEvidence | None; runtime_ports: tuple[RuntimeEvidencePort, ...]; observed_program_hash: str | None = None; rpc_quorum_hash: str | None = None; contract_drift_detected: bool = False; credential_failure: bool = False; program_identity_changed: bool = False; rpc_quorum_disagreed: bool = False; now_unix_seconds: int = 0
@dataclass(frozen=True)
class ProviderAdmission:
    schema_version: str; provider: ProviderName | str; decision: AdmissionDecision; reason_codes: tuple[str, ...]; evidence_hash: str; expires_unix_seconds: int | None; runtime_ports: tuple[RuntimeEvidencePort, ...]; sender_enabled: bool = False; signer_enabled: bool = False; live_enabled: bool = False
@dataclass(frozen=True)
class HttpRequestSpec:
    method: str; url: str; headers: Mapping[str, str]; json_body: Mapping[str, Any] | None; timeout_seconds: float; max_response_bytes: int; purpose: str
@dataclass(frozen=True)
class HttpResponseEvidence:
    status_code: int; headers: Mapping[str, str]; body_json: Mapping[str, Any] | list[Any]; elapsed_ms: int; response_bytes: int
class BoundedTransport(Protocol):
    def request(self, spec: HttpRequestSpec) -> HttpResponseEvidence: ...

def canonical(value: Any) -> Any:
    if isinstance(value, StrEnum): return value.value
    if is_dataclass(value): return canonical(asdict(value))
    if isinstance(value, Mapping): return {str(k): canonical(v) for k, v in sorted(value.items(), key=lambda x: str(x[0]))}
    if isinstance(value, (list, tuple)): return [canonical(v) for v in value]
    return value

def sha256_json(value: Any) -> str:
    return sha256(json.dumps(canonical(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
def is_hash(value: str | None) -> bool: return bool(value and HASH_RE.fullmatch(value))
def legacy_jupiter_path_detected(text: str) -> bool: return any(path in text.lower() for path in LEGACY_JUPITER_PATHS)
def redact_for_fixture(value: Any) -> Any:
    if isinstance(value, Mapping): return {str(k): ("<redacted>" if SECRET_KEY_RE.search(str(k)) else redact_for_fixture(v)) for k, v in value.items()}
    if isinstance(value, list): return [redact_for_fixture(v) for v in value]
    if isinstance(value, tuple): return [redact_for_fixture(v) for v in value]
    if isinstance(value, str): return SECRET_VALUE_RE.sub("<redacted>", value)
    return value

def write_redacted_fixture(path: str | Path, provider: ProviderName | str, payload: Mapping[str, Any]) -> str:
    redacted = redact_for_fixture(payload)
    if SECRET_VALUE_RE.search(json.dumps(redacted, sort_keys=True)): raise ProviderConformanceError("SECRET_MATERIAL_REMAINS")
    fixture = {"schema_version": SCHEMA_VERSION, "provider": str(provider), "payload_hash": sha256_json(redacted), "payload": redacted}
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(fixture, sort_keys=True, indent=2) + "\n")
    return sha256_json(fixture)

def make_runtime_port(port_name: str, producer: str, consumer: str, store: str) -> RuntimeEvidencePort:
    return RuntimeEvidencePort(port_name, producer, consumer, store, f"python -m src.providers.conformance.mega_b2 replay --port {port_name}")

def evaluate_admission(bundle: ExternalEvidenceBundle) -> ProviderAdmission:
    r: list[str] = []; p = bundle.contract_pin
    if bundle.schema_version != SCHEMA_VERSION: r.append("SCHEMA_VERSION_MISMATCH")
    if not p.official_source_url.startswith("https://"): r.append("OFFICIAL_SOURCE_NOT_HTTPS")
    if not is_hash(p.request_schema_hash): r.append("REQUEST_SCHEMA_HASH_MISSING")
    if not is_hash(p.response_schema_hash): r.append("RESPONSE_SCHEMA_HASH_MISSING")
    if p.max_response_bytes <= 0 or p.max_response_bytes > 10_000_000: r.append("MAX_RESPONSE_BYTES_INVALID")
    if p.provider == ProviderName.JUPITER and p.endpoint_or_program != CURRENT_JUPITER_BUILD_PATH: r.append("JUPITER_ACTIVE_ENDPOINT_NOT_SWAP_V2_BUILD")
    if p.provider == ProviderName.JUPITER and legacy_jupiter_path_detected(p.endpoint_or_program): r.append("JUPITER_LEGACY_ENDPOINT_PINNED")
    if bundle.probe is None: r.append("PROTECTED_PROBE_MISSING")
    else:
        if not bundle.probe.protected_workflow: r.append("PROBE_NOT_PROTECTED_WORKFLOW")
        if not bundle.probe.credentialed_probe: r.append("PROBE_NOT_CREDENTIALED")
        for f in ("request_hash", "response_hash", "redacted_fixture_hash"):
            if not is_hash(getattr(bundle.probe, f)): r.append(f"{f.upper()}_MISSING")
        if bundle.probe.raw_secret_material_present or bundle.probe.raw_url_with_query_secret_present: r.append("PROBE_CONTAINS_SECRET")
        if bundle.probe.raw_provider_error_present: r.append("PROBE_CONTAINS_RAW_PROVIDER_ERROR")
    if not bundle.runtime_ports: r.append("NO_ACTIVE_RUNTIME_PORT")
    for port in bundle.runtime_ports:
        if not port.active_in_runtime: r.append(f"RUNTIME_PORT_NOT_ACTIVE:{port.port_name}")
    if p.reviewed_unix_seconds + p.freshness_ttl_seconds < bundle.now_unix_seconds: r.append("EVIDENCE_EXPIRED")
    if bundle.contract_drift_detected: r.append("CONTRACT_DRIFT_DETECTED")
    if bundle.credential_failure: r.append("CREDENTIAL_FAILURE")
    if bundle.program_identity_changed: r.append("PROGRAM_IDENTITY_CHANGED")
    if bundle.rpc_quorum_disagreed: r.append("RPC_QUORUM_DISAGREED")
    if p.provider in {ProviderName.MARGINFI, ProviderName.KAMINO} and not is_hash(bundle.observed_program_hash): r.append("DEPLOYED_PROGRAM_OBSERVATION_MISSING")
    if p.provider == ProviderName.SOLANA_RPC and not is_hash(bundle.rpc_quorum_hash): r.append("RPC_QUORUM_HASH_MISSING")
    return ProviderAdmission(ADMISSION_SCHEMA_VERSION, p.provider, AdmissionDecision.BLOCKED if r else AdmissionDecision.ADMITTED, tuple(dict.fromkeys(r)), sha256_json(bundle), p.reviewed_unix_seconds + p.freshness_ttl_seconds, bundle.runtime_ports)

class JupiterV2BuildAdapter:
    endpoint = "https://api.jup.ag/swap/v2/build"
    def __init__(self, transport: BoundedTransport | None = None) -> None: self.transport = transport
    @staticmethod
    def build_request(payload: Mapping[str, Any], api_key: str | None = None) -> HttpRequestSpec:
        if not payload: raise ProviderConformanceError("JUPITER_BUILD_PAYLOAD_REQUIRED")
        headers = {"content-type": "application/json"}
        if api_key: headers["x-api-key"] = api_key
        return HttpRequestSpec("POST", JupiterV2BuildAdapter.endpoint, headers, dict(payload), 3.0, 1_500_000, "jupiter_final_build")
    def build(self, payload: Mapping[str, Any], api_key: str | None = None) -> HttpResponseEvidence:
        if self.transport is None: raise ProviderConformanceError("PROTECTED_TRANSPORT_REQUIRED")
        response = self.transport.request(self.build_request(payload, api_key))
        if not isinstance(response.body_json, Mapping) or "swapTransaction" in response.body_json: raise ProviderConformanceError("JUPITER_BUILD_RESPONSE_NOT_V2_BUILD")
        return response

class SolanaRpcEvidenceService:
    @staticmethod
    def rpc_request(rpc_url: str, method: str, params: list[Any] | None = None) -> HttpRequestSpec:
        if method not in {"getLatestBlockhash", "isBlockhashValid", "getTransaction", "getAccountInfo", "getSlot", "getVersion"}: raise ProviderConformanceError("UNSUPPORTED_RUNTIME_RPC_METHOD")
        return HttpRequestSpec("POST", rpc_url, {"content-type": "application/json"}, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}, 3.0, 2_000_000, "solana_rooted_rpc_evidence")
    @staticmethod
    def validate_context(response: Mapping[str, Any], min_context_slot: int | None = None) -> int:
        context = response.get("result", {}).get("context") if isinstance(response.get("result"), Mapping) else None
        if not isinstance(context, Mapping) or not isinstance(context.get("slot"), int): raise ProviderConformanceError("RPC_CONTEXT_MISSING")
        if min_context_slot is not None and context["slot"] < min_context_slot: raise ProviderConformanceError("RPC_CONTEXT_BELOW_MIN_CONTEXT_SLOT")
        return context["slot"]

class JitoReadOnlyAdapter:
    @staticmethod
    def get_tip_accounts_request(jito_rpc_url: str) -> HttpRequestSpec:
        return HttpRequestSpec("POST", jito_rpc_url, {"content-type": "application/json"}, {"jsonrpc": "2.0", "id": 1, "method": "getTipAccounts", "params": []}, 2.0, 256_000, "jito_readonly_tip_accounts")
    @staticmethod
    def reject_submission_method(method: str) -> None:
        if method in {"sendTransaction", "sendBundle", "simulateBundle"}: raise ProviderConformanceError("JITO_SUBMISSION_METHOD_FORBIDDEN_IN_B2")

class ProgramEvidenceProducer:
    @staticmethod
    def validate_program_observation(observation: Mapping[str, Any]) -> str:
        if not {"program_id", "programdata_address", "executable", "owner", "slot"}.issubset(observation): raise ProviderConformanceError("PROGRAM_OBSERVATION_INCOMPLETE")
        if observation.get("executable") is not True: raise ProviderConformanceError("PROGRAM_NOT_EXECUTABLE")
        if not isinstance(observation.get("slot"), int) or observation["slot"] <= 0: raise ProviderConformanceError("PROGRAM_SLOT_INVALID")
        return sha256_json(observation)

class ProviderAdmissionController:
    def __init__(self, bundles: list[ExternalEvidenceBundle]) -> None: self.bundles = {str(b.contract_pin.provider): b for b in bundles}
    def require_runtime_port(self, provider: ProviderName | str, port_name: str) -> RuntimeEvidencePort:
        bundle = self.bundles.get(str(provider))
        if bundle is None: raise ProviderConformanceError("PROVIDER_EVIDENCE_BUNDLE_MISSING")
        admission = evaluate_admission(bundle)
        if admission.decision != AdmissionDecision.ADMITTED: raise ProviderConformanceError("PROVIDER_BLOCKED:" + ",".join(admission.reason_codes))
        for port in admission.runtime_ports:
            if port.port_name == port_name and port.active_in_runtime: return port
        raise ProviderConformanceError("ACTIVE_RUNTIME_PORT_MISSING")

def protected_probe_plans() -> tuple[dict[str, Any], ...]:
    return (
        {"provider": ProviderName.JUPITER, "kind": "jupiter_build", "request": canonical(JupiterV2BuildAdapter.build_request({"quoteResponse": {"fixture": True}})), "required_env": ("JUPITER_API_KEY",), "port": canonical(make_runtime_port("jupiter_v2_build", "JupiterV2BuildAdapter", "PaperRuntimeDependencies.jupiter_v2_build", "external_evidence_bundle"))},
        {"provider": ProviderName.SOLANA_RPC, "kind": "solana_rpc_root", "request": canonical(SolanaRpcEvidenceService.rpc_request("${SOLANA_RPC_URL}", "getLatestBlockhash", [{"commitment": "finalized"}])), "required_env": ("SOLANA_RPC_URL",), "port": canonical(make_runtime_port("rooted_rpc_evidence", "SolanaRpcEvidenceService", "PaperRuntimeDependencies.rooted_rpc", "external_evidence_bundle"))},
        {"provider": ProviderName.JITO_READONLY, "kind": "jito_get_tip_accounts", "request": canonical(JitoReadOnlyAdapter.get_tip_accounts_request("${JITO_RPC_URL}")), "required_env": ("JITO_RPC_URL",), "port": canonical(make_runtime_port("jito_readonly_tip_accounts", "JitoReadOnlyAdapter", "ReleaseCanaryPolicy.tip_policy", "external_evidence_bundle"))},
        {"provider": ProviderName.MARGINFI, "kind": "marginfi_program", "request": {"method": "getAccountInfo", "commitment": "finalized"}, "required_env": ("SOLANA_RPC_URL", "MARGINFI_PROGRAM_ID"), "port": canonical(make_runtime_port("marginfi_rooted_state", "ProgramEvidenceProducer", "PaperRuntimeDependencies.verified_marginfi_provider", "external_evidence_bundle"))},
    )

def evidence_bundle_from_probe(pin: ExternalContractPin, payload: Mapping[str, Any], runtime_ports: tuple[RuntimeEvidencePort, ...], *, protected_workflow: bool, credentialed_probe: bool, captured_unix_seconds: int, observed_program_hash: str | None = None, rpc_quorum_hash: str | None = None, now_unix_seconds: int | None = None) -> ExternalEvidenceBundle:
    redacted = redact_for_fixture(payload)
    probe = ProtectedProbeEvidence(pin.provider, sha256_json(redacted)[:24], captured_unix_seconds, protected_workflow, credentialed_probe, sha256_json(redacted.get("request", {})), sha256_json(redacted.get("response", {})), sha256_json(redacted))
    return ExternalEvidenceBundle(SCHEMA_VERSION, pin, probe, runtime_ports, observed_program_hash, rpc_quorum_hash, now_unix_seconds=now_unix_seconds or captured_unix_seconds)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="provider-conformance-b2"); sub = parser.add_subparsers(dest="command", required=True); sub.add_parser("plan"); replay = sub.add_parser("replay"); replay.add_argument("--bundle", type=Path, required=True); replay.add_argument("--port"); args = parser.parse_args(argv)
    if args.command == "plan": print(json.dumps(canonical(protected_probe_plans()), sort_keys=True, indent=2)); return 0
    data = json.loads(args.bundle.read_text()); pin = ExternalContractPin(**data["contract_pin"]); probe = None if data.get("probe") is None else ProtectedProbeEvidence(**data["probe"]); ports = tuple(RuntimeEvidencePort(**p) for p in data.get("runtime_ports", [])); bundle = ExternalEvidenceBundle(data["schema_version"], pin, probe, ports, data.get("observed_program_hash"), data.get("rpc_quorum_hash"), now_unix_seconds=int(data.get("now_unix_seconds", 0))); admission = evaluate_admission(bundle)
    print(json.dumps({"decision": admission.decision.value, "reason_codes": list(admission.reason_codes), "evidence_hash": admission.evidence_hash}, sort_keys=True)); return 0 if admission.decision == AdmissionDecision.ADMITTED else 1

if __name__ == "__main__":
    raise SystemExit(main())
