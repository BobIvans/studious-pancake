"""Verifier primitives for MPR-CLOSE-03 provider/protocol rooted data-plane checks.

These checks are intentionally sender-free and evidence-first. They do not call
live providers, do not read secrets, and do not promote live execution. Their
purpose is to bind the current repository state to explicit conformance reports
so that a draft PR can show which parts of MPR-CLOSE-03 are already wired and
which parts are still blocked pending reviewed evidence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

SCHEMA_SOLANA = "mpr-close-03.solana-v0-alt-conformance.v1"
SCHEMA_EXTERNAL = "mpr-close-03.external-contracts.v1"
SCHEMA_DRIFT = "mpr-close-03.provider-drift-probes.v1"

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class VerificationReport:
    schema_version: str
    ok: bool
    blockers: tuple[str, ...]
    facts: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "blockers": list(self.blockers),
            "facts": self.facts,
        }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _safe_exists(path: Path) -> bool:
    return path.exists() and path.is_file()


def _iter_repo_files(*suffixes: str):
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.parts and any(part.startswith(".") and part not in {".github"} for part in path.parts):
            continue
        if suffixes and path.suffix not in suffixes:
            continue
        yield path


def _count_occurrences(needle: str, *suffixes: str) -> int:
    total = 0
    for path in _iter_repo_files(*suffixes):
        try:
            total += _read_text(path).count(needle)
        except UnicodeDecodeError:
            continue
    return total


def verify_solana_v0_alt_conformance(root: Path | None = None) -> VerificationReport:
    project_root = root or ROOT
    blockers: list[str] = []

    router_path = project_root / "src/providers/jupiter/router.py"
    router_text = _read_text(router_path) if _safe_exists(router_path) else ""
    delivery_exists = _safe_exists(project_root / "src/providers/helius/delivery.py")
    ingress_exists = _safe_exists(project_root / "src/providers/helius/authenticated_ingress.py")
    recovery_exists = _safe_exists(project_root / "src/providers/helius/rooted_recovery.py")
    v0_occurrences = _count_occurrences("maxSupportedTransactionVersion", ".py", ".json", ".md")
    finalized_occurrences = _count_occurrences('"finalized"', ".py", ".json")
    alt_occurrences = _count_occurrences("addressesByLookupTableAddress", ".py", ".json")

    facts = {
        "router_uses_swap_v2_build": "JUPITER_ROUTER_ENDPOINT = \"/swap/v2/build\"" in router_text,
        "v0_occurrences": v0_occurrences,
        "finalized_occurrences": finalized_occurrences,
        "alt_occurrences": alt_occurrences,
        "helius_delivery_module": delivery_exists,
        "helius_authenticated_ingress_module": ingress_exists,
        "helius_rooted_recovery_module": recovery_exists,
    }

    if not facts["router_uses_swap_v2_build"]:
        blockers.append("JUPITER_SWAP_V2_BUILD_NOT_BOUND")
    if v0_occurrences <= 0:
        blockers.append("SOLANA_MAX_SUPPORTED_TRANSACTION_VERSION_NOT_MATERIALIZED")
    if finalized_occurrences <= 0:
        blockers.append("FINALIZED_SETTLEMENT_EVIDENCE_NOT_MATERIALIZED")
    if alt_occurrences <= 0:
        blockers.append("ALT_LOOKUP_EVIDENCE_NOT_MATERIALIZED")
    if not delivery_exists:
        blockers.append("HELIUS_DELIVERY_MODULE_MISSING")
    if not ingress_exists:
        blockers.append("HELIUS_AUTHENTICATED_INGRESS_MODULE_MISSING")
    if not recovery_exists:
        blockers.append("HELIUS_ROOTED_RECOVERY_MODULE_MISSING")

    return VerificationReport(
        schema_version=SCHEMA_SOLANA,
        ok=not blockers,
        blockers=tuple(blockers),
        facts=facts,
    )


def verify_external_contracts(root: Path | None = None) -> VerificationReport:
    project_root = root or ROOT
    blockers: list[str] = []
    manifest_path = project_root / "src/resources/external_contracts.json"
    kamino_path = project_root / "src/resources/kamino_supported_combinations.json"
    manifest = _read_json(manifest_path)
    contracts = {item["provider"]: item for item in manifest.get("contracts", [])}
    kamino_registry = _read_json(kamino_path)
    combinations = kamino_registry.get("combinations", [])

    jupiter = contracts.get("jupiter", {})
    okx = contracts.get("okx", {})
    openocean = contracts.get("openocean", {})
    odos = contracts.get("odos", {})
    marginfi = contracts.get("marginfi", {})

    jupiter_probe = jupiter.get("conformance_probe") or {}
    jupiter_url = str(jupiter_probe.get("url", ""))
    jupiter_paths = tuple(jupiter_probe.get("required_json_paths", []))

    facts = {
        "manifest_schema_version": manifest.get("schema_version"),
        "kamino_registry_schema_version": kamino_registry.get("schema_version"),
        "jupiter_status": jupiter.get("status"),
        "jupiter_probe_url": jupiter_url,
        "jupiter_uses_header_api_key": jupiter_probe.get("credential_mode") == "header-api-key",
        "jupiter_required_json_paths": list(jupiter_paths),
        "okx_status": okx.get("status"),
        "openocean_status": openocean.get("status"),
        "odos_status": odos.get("status"),
        "marginfi_status": marginfi.get("status"),
        "kamino_reviewed_combination_count": len(combinations),
        "kamino_claims_enabled_support": len(combinations) > 0,
    }

    if jupiter.get("status") != "active":
        blockers.append("JUPITER_NOT_ACTIVE")
    if "/swap/v2/build" not in jupiter_url:
        blockers.append("JUPITER_BUILD_URL_NOT_V2")
    if any(legacy in jupiter_url for legacy in ("/swap/v1/", "/swap/v2/swap-instructions", "/price/v2")):
        blockers.append("JUPITER_LEGACY_ENDPOINT_STILL_ACTIVE")
    if not facts["jupiter_uses_header_api_key"]:
        blockers.append("JUPITER_API_KEY_HEADER_POLICY_MISSING")
    if "addressesByLookupTableAddress" not in jupiter_paths:
        blockers.append("JUPITER_ALT_MAPPING_PATH_MISSING")
    if "blockhashWithMetadata.blockhash" not in jupiter_paths:
        blockers.append("JUPITER_BLOCKHASH_METADATA_PATH_MISSING")
    if okx.get("status") != "discovery-only":
        blockers.append("OKX_NOT_DISCOVERY_ONLY")
    if openocean.get("status") != "discovery-only":
        blockers.append("OPENOCEAN_NOT_DISCOVERY_ONLY")
    if odos.get("status") != "discovery-only":
        blockers.append("ODOS_NOT_DISCOVERY_ONLY")
    if marginfi.get("status") not in {"disabled-unverified", "fixture-only-blocked", "blocked-missing-protocol-evidence"}:
        blockers.append("MARGINFI_STATUS_UNSAFE")
    if len(combinations) != 0:
        blockers.append("KAMINO_REGISTRY_NOT_EMPTY_REQUIRES_HUMAN_REVIEW")

    return VerificationReport(
        schema_version=SCHEMA_EXTERNAL,
        ok=not blockers,
        blockers=tuple(blockers),
        facts=facts,
    )


def verify_provider_drift_probes(root: Path | None = None) -> VerificationReport:
    project_root = root or ROOT
    blockers: list[str] = []
    manifest = _read_json(project_root / "src/resources/external_contracts.json")
    contracts = manifest.get("contracts", [])

    artifact_paths: list[str] = []
    missing_artifacts: list[str] = []
    redaction_secret_hits = 0
    reviewed_sources = 0

    for contract in contracts:
        source_ref = str(contract.get("source_ref", ""))
        if "reviewed" in source_ref or "pending" in source_ref or "unresolved" in source_ref:
            reviewed_sources += 1
        payload = json.dumps(contract, sort_keys=True).lower()
        if any(token in payload for token in (" bearer ", "private_key", "secret_value", "-----begin")):
            redaction_secret_hits += 1
        for artifact in contract.get("artifacts", []):
            path = str(artifact.get("path", ""))
            if not path:
                continue
            artifact_paths.append(path)
            candidate = project_root / path
            if not candidate.exists():
                missing_artifacts.append(path)

    facts = {
        "contract_count": len(contracts),
        "artifact_count": len(artifact_paths),
        "missing_artifact_count": len(missing_artifacts),
        "missing_artifacts": missing_artifacts,
        "redaction_secret_hits": redaction_secret_hits,
        "reviewed_source_markers": reviewed_sources,
    }

    if len(contracts) == 0:
        blockers.append("NO_EXTERNAL_CONTRACTS_DEFINED")
    if redaction_secret_hits:
        blockers.append("SECRET_LIKE_MATERIAL_FOUND_IN_CONTRACT_MANIFEST")
    if reviewed_sources == 0:
        blockers.append("NO_REVIEWED_SOURCE_MARKERS")
    if missing_artifacts:
        blockers.append("CONTRACT_ARTIFACTS_MISSING_FROM_REPO")

    return VerificationReport(
        schema_version=SCHEMA_DRIFT,
        ok=not blockers,
        blockers=tuple(blockers),
        facts=facts,
    )


def emit_report(report: VerificationReport, *, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(report.to_dict(), indent=2, sort_keys=True)
    status = "ok" if report.ok else "blocked"
    lines = [f"schema={report.schema_version}", f"status={status}"]
    for key, value in sorted(report.facts.items()):
        lines.append(f"{key}={value}")
    for blocker in report.blockers:
        lines.append(f"BLOCKER: {blocker}")
    return "\n".join(lines)
