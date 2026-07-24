"""MPR-NEXT-03 provider/protocol conformance and drift-evidence gate.

This module is intentionally side-effect free: it does not call providers, submit
transactions, sign messages, or enable live trading.  It validates the immutable
manifest shape that real credentialed/read-only provider probes must satisfy
before provider evidence can be admitted into the paper/shadow runtime.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib import resources
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "mpr-next-03.provider-protocol-conformance.v1"
DEFAULT_RESOURCE = "provider_protocol_conformance_mpr_next_03.json"

REQUIRED_PROVIDERS: frozenset[str] = frozenset(
    {
        "solana_rpc_v0",
        "jupiter_swap_v2_build",
        "helius_webhook_auth",
        "marginfi_v2_identity",
        "kamino_klend_identity",
    }
)

DISCOVERY_ONLY_PROVIDERS: frozenset[str] = frozenset(
    {"okx_signed_discovery", "openocean_whitelist_discovery", "odos_immutable_transaction"}
)

FORBIDDEN_ACTIVE_ENDPOINT_FRAGMENTS: tuple[str, ...] = (
    "/swap/v1/quote",
    "/swap/v1/swap",
    "/swap/v1/swap-instructions",
)

REQUIRED_DRIFT_ARTIFACTS: frozenset[str] = frozenset(
    {
        "solana_rpc_v0_drift_probe",
        "jupiter_swap_v2_schema_probe",
        "helius_webhook_contract_probe",
        "marginfi_deployment_identity_probe",
        "kamino_klend_deployment_identity_probe",
    }
)


@dataclass(frozen=True, slots=True)
class ProviderConformanceReport:
    accepted: bool
    schema_version: str
    live_enabled: bool
    blockers: tuple[str, ...]
    provider_count: int
    drift_artifact_count: int
    manifest_digest: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def digest_payload(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def load_default_manifest() -> dict[str, Any]:
    root = resources.files("src.resources")
    return json.loads(root.joinpath(DEFAULT_RESOURCE).read_text(encoding="utf-8"))


def load_manifest(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _list(value: Any, name: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return value


def _bool(mapping: Mapping[str, Any], key: str) -> bool:
    value = mapping.get(key)
    if type(value) is not bool:
        raise ValueError(f"{key} must be boolean")
    return value


def _text(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _paths(provider: Mapping[str, Any]) -> tuple[str, ...]:
    values = _list(provider.get("active_paths", []), "active_paths")
    paths: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.startswith("/"):
            raise ValueError("active_paths entries must be absolute API paths")
        paths.append(value)
    return tuple(paths)


def _provider_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    providers = _list(manifest.get("providers"), "providers")
    output: dict[str, Mapping[str, Any]] = {}
    for row in providers:
        provider = _mapping(row, "provider")
        provider_id = _text(provider, "id")
        if provider_id in output:
            raise ValueError(f"duplicate provider id: {provider_id}")
        output[provider_id] = provider
    return output


def _drift_artifacts(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    artifacts = _list(manifest.get("drift_artifacts"), "drift_artifacts")
    output: dict[str, Mapping[str, Any]] = {}
    for row in artifacts:
        artifact = _mapping(row, "drift_artifact")
        artifact_id = _text(artifact, "id")
        if artifact_id in output:
            raise ValueError(f"duplicate drift artifact id: {artifact_id}")
        output[artifact_id] = artifact
    return output


def _validate_jupiter(provider: Mapping[str, Any], blockers: list[str]) -> None:
    paths = _paths(provider)
    if "/swap/v2/build" not in paths:
        blockers.append("JUPITER_V2_BUILD_PATH_MISSING")
    if any(fragment in path for path in paths for fragment in FORBIDDEN_ACTIVE_ENDPOINT_FRAGMENTS):
        blockers.append("JUPITER_ACTIVE_SWAP_V1_PATH_PRESENT")
    if _bool(provider, "raw_composable_instruction_endpoint") is not True:
        blockers.append("JUPITER_RAW_COMPOSABLE_ENDPOINT_NOT_DECLARED")
    managed = _mapping(provider.get("managed_execution"), "managed_execution")
    if _bool(managed, "composable_into_flashloan") is not False:
        blockers.append("JUPITER_MANAGED_EXECUTION_MUST_BE_NON_COMPOSABLE")


def _validate_solana(provider: Mapping[str, Any], blockers: list[str]) -> None:
    rpc = _mapping(provider.get("rpc"), "rpc")
    if rpc.get("maxSupportedTransactionVersion") != 0:
        blockers.append("SOLANA_V0_MAX_SUPPORTED_VERSION_REQUIRED")
    if _bool(rpc, "alt_reads_supported") is not True:
        blockers.append("SOLANA_ALT_READS_REQUIRED")
    if _bool(rpc, "finalized_settlement_required") is not True:
        blockers.append("SOLANA_FINALIZED_SETTLEMENT_REQUIRED")


def _validate_helius(provider: Mapping[str, Any], blockers: list[str]) -> None:
    webhook = _mapping(provider.get("webhook"), "webhook")
    if _bool(webhook, "authorization_header_required") is not True:
        blockers.append("HELIUS_AUTH_HEADER_REQUIRED")
    if _bool(webhook, "at_least_once_delivery") is not True:
        blockers.append("HELIUS_AT_LEAST_ONCE_REQUIRED")
    if _bool(webhook, "duplicate_safe_persistence") is not True:
        blockers.append("HELIUS_DUPLICATE_SAFE_PERSISTENCE_REQUIRED")
    if _bool(webhook, "ack_after_durable_enqueue") is not True:
        blockers.append("HELIUS_ACK_MUST_FOLLOW_DURABLE_ENQUEUE")


def _validate_deployment_identity(
    provider_id: str,
    provider: Mapping[str, Any],
    blockers: list[str],
) -> None:
    identity = _mapping(provider.get("deployment_identity"), "deployment_identity")
    for key in ("program_id", "rooted_slot", "schema_hash", "official_source_digest"):
        _text(identity, key)
    if _bool(identity, "independently_attested") is not True:
        blockers.append(f"{provider_id.upper()}_NOT_INDEPENDENTLY_ATTESTED")
    if _bool(identity, "sanitized_fixture_present") is not True:
        blockers.append(f"{provider_id.upper()}_SANITIZED_FIXTURE_MISSING")


def _validate_optional_provider(
    provider_id: str,
    provider: Mapping[str, Any],
    blockers: list[str],
) -> None:
    if _bool(provider, "runtime_admission_enabled"):
        blockers.append(f"{provider_id.upper()}_MUST_REMAIN_DISCOVERY_ONLY")
    if _bool(provider, "raw_composable_instruction_proven") is not False:
        blockers.append(f"{provider_id.upper()}_RAW_COMPOSABLE_PROOF_MUST_BE_FALSE")


def _validate_drift_artifacts(
    artifacts: Mapping[str, Mapping[str, Any]],
    blockers: list[str],
) -> None:
    missing = REQUIRED_DRIFT_ARTIFACTS - set(artifacts)
    for artifact_id in sorted(missing):
        blockers.append(f"DRIFT_ARTIFACT_MISSING:{artifact_id}")
    for artifact_id, artifact in sorted(artifacts.items()):
        if _bool(artifact, "signed") is not True:
            blockers.append(f"DRIFT_ARTIFACT_UNSIGNED:{artifact_id}")
        if _bool(artifact, "redacted") is not True:
            blockers.append(f"DRIFT_ARTIFACT_UNREDACTED:{artifact_id}")
        if _bool(artifact, "immutable") is not True:
            blockers.append(f"DRIFT_ARTIFACT_MUTABLE:{artifact_id}")
        kind = _text(artifact, "evidence_kind")
        if kind != "credentialed-read-only-probe":
            blockers.append(f"DRIFT_ARTIFACT_NOT_CREDENTIALED_PROBE:{artifact_id}")


def evaluate_provider_conformance(
    manifest: Mapping[str, Any] | None = None,
) -> ProviderConformanceReport:
    payload = _mapping(manifest or load_default_manifest(), "manifest")
    blockers: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        blockers.append("SCHEMA_VERSION_INVALID")
    if _bool(payload, "live_enabled"):
        blockers.append("LIVE_MUST_REMAIN_DISABLED")
    if _bool(payload, "transaction_submission_enabled"):
        blockers.append("SUBMISSION_MUST_REMAIN_DISABLED")

    providers = _provider_map(payload)
    missing_providers = REQUIRED_PROVIDERS - set(providers)
    for provider_id in sorted(missing_providers):
        blockers.append(f"REQUIRED_PROVIDER_MISSING:{provider_id}")

    for provider_id, provider in sorted(providers.items()):
        if provider_id == "jupiter_swap_v2_build":
            _validate_jupiter(provider, blockers)
        elif provider_id == "solana_rpc_v0":
            _validate_solana(provider, blockers)
        elif provider_id == "helius_webhook_auth":
            _validate_helius(provider, blockers)
        elif provider_id in {"marginfi_v2_identity", "kamino_klend_identity"}:
            _validate_deployment_identity(provider_id, provider, blockers)
        elif provider_id in DISCOVERY_ONLY_PROVIDERS:
            _validate_optional_provider(provider_id, provider, blockers)

    artifacts = _drift_artifacts(payload)
    _validate_drift_artifacts(artifacts, blockers)

    digest = digest_payload(payload)
    return ProviderConformanceReport(
        accepted=not blockers,
        schema_version=SCHEMA_VERSION,
        live_enabled=False,
        blockers=tuple(dict.fromkeys(blockers)),
        provider_count=len(providers),
        drift_artifact_count=len(artifacts),
        manifest_digest=digest,
    )
