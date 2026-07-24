#!/usr/bin/env python3
"""Verify the MPR-NEXT-08 Jupiter V2 contract and quarantine boundary."""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Final

import yaml

ROOT: Final = Path(__file__).resolve().parents[1]
SCHEMA_VERSION: Final = "mpr-next-08.jupiter-v2-contract-evidence.v1"
PRODUCT_CONTRACT_PATH: Final = "config/product_contract_pr195.json"
PACKAGED_PRODUCT_CONTRACT_PATH: Final = "src/resources/product_contract_pr195.json"
EXTERNAL_CONTRACTS_PATH: Final = "docs/external_contracts.yaml"
ROUTER_PATH: Final = "src/providers/jupiter/router.py"
MEGA_B2_PATH: Final = "src/providers/conformance/mega_b2.py"
PRODUCTION_SURFACE_PATH: Final = "src/resources/production_surface_manifest.json"
QUARANTINE_PATH: Final = "config/jupiter_endpoint_quarantine.json"
VERIFY_REPO_PATH: Final = "scripts/verify_repo.py"
ACTIVE_SCAN_TARGETS: Final[tuple[str, ...]] = (
    "src",
    PRODUCT_CONTRACT_PATH,
    PACKAGED_PRODUCT_CONTRACT_PATH,
)
TEXT_SUFFIXES: Final = frozenset({".py", ".json", ".yaml", ".yml", ".toml"})
EXPECTED_ORIGIN: Final = "https://api.jup.ag"
EXPECTED_METHOD: Final = "GET"
EXPECTED_PATH: Final = "/swap/v2/build"
EXPECTED_ADAPTER: Final = "src.providers.jupiter.router.JupiterRouterAdapter"
EXPECTED_PRODUCT_PATHS: Final = frozenset({"/price/v3", EXPECTED_PATH})
EXPECTED_FORBIDDEN_MARKERS: Final = frozenset(
    {
        "/swap/v1",
        "/swap/v2/quote",
        "/swap/v2/swap",
        "/swap/v2/swap-instructions",
    }
)
DIRECT_NETWORK_TOKENS: Final = (
    "import aiohttp",
    "from aiohttp",
    "import httpx",
    "from httpx",
    "import requests",
    "from requests",
    "ClientSession(",
    "requests.get(",
    "requests.post(",
    "httpx.get(",
    "httpx.post(",
    "urlopen(",
)


class JupiterV2ContractError(RuntimeError):
    """Raised when a required MPR-NEXT-08 artifact is missing or malformed."""


@dataclass(frozen=True, slots=True)
class JupiterV2ContractEvidence:
    schema_version: str
    accepted: bool
    blockers: tuple[str, ...]
    artifact_hashes: dict[str, str]
    product_contract_paths: tuple[str, ...]
    docs_endpoint: str | None
    router_endpoint: str | None
    mega_b2_method: str | None
    quarantined_paths: tuple[str, ...]
    policy_reference_paths: tuple[str, ...]
    scanned_active_files: int

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        payload["product_contract_paths"] = list(self.product_contract_paths)
        payload["quarantined_paths"] = list(self.quarantined_paths)
        payload["policy_reference_paths"] = list(self.policy_reference_paths)
        return payload


def _repo_file(root: Path, relative: str) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    if candidate == resolved_root or resolved_root not in candidate.parents:
        raise JupiterV2ContractError(f"path escapes repository root: {relative}")
    return candidate


def _read_bytes(root: Path, relative: str) -> bytes:
    try:
        return _repo_file(root, relative).read_bytes()
    except FileNotFoundError as exc:
        raise JupiterV2ContractError(f"required file is missing: {relative}") from exc


def _read_text(root: Path, relative: str) -> str:
    try:
        return _read_bytes(root, relative).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise JupiterV2ContractError(f"required file is not UTF-8: {relative}") from exc


def _load_json(root: Path, relative: str) -> dict[str, Any]:
    try:
        value = json.loads(_read_text(root, relative))
    except json.JSONDecodeError as exc:
        raise JupiterV2ContractError(f"invalid JSON in {relative}: {exc}") from exc
    if not isinstance(value, dict):
        raise JupiterV2ContractError(f"{relative} must contain a JSON object")
    return value


def _load_yaml(root: Path, relative: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(_read_text(root, relative))
    except yaml.YAMLError as exc:
        raise JupiterV2ContractError(f"invalid YAML in {relative}: {exc}") from exc
    if not isinstance(value, dict):
        raise JupiterV2ContractError(f"{relative} must contain a YAML object")
    return value


def _as_dict(value: object, blockers: list[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        blockers.append(code)
        return {}
    return value


def _as_string_list(value: object, blockers: list[str], code: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        blockers.append(code)
        return ()
    return tuple(value)


def _require(condition: bool, blockers: list[str], code: str) -> None:
    if not condition:
        blockers.append(code)


def _assigned_string(source: str, name: str, source_path: str) -> str | None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise JupiterV2ContractError(f"invalid Python in {source_path}: {exc}") from exc
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    return None


def _quarantine_entries(
    payload: dict[str, Any],
    blockers: list[str],
) -> tuple[tuple[str, str], ...]:
    entries = payload.get("quarantined_paths")
    if not isinstance(entries, list):
        blockers.append("QUARANTINE_PATHS_MISSING")
        return ()
    parsed: list[tuple[str, str]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            blockers.append(f"QUARANTINE_ENTRY_INVALID:{index}")
            continue
        path = entry.get("path")
        boundary = entry.get("boundary")
        if not isinstance(path, str) or boundary not in {
            "module_file",
            "package_prefix",
        }:
            blockers.append(f"QUARANTINE_ENTRY_INVALID:{index}")
            continue
        parsed.append((path, str(boundary)))
    return tuple(parsed)


def _policy_reference_paths(
    payload: dict[str, Any],
    blockers: list[str],
) -> tuple[str, ...]:
    entries = payload.get("policy_reference_paths")
    if not isinstance(entries, list):
        blockers.append("POLICY_REFERENCE_PATHS_MISSING")
        return ()
    parsed: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            blockers.append(f"POLICY_REFERENCE_ENTRY_INVALID:{index}")
            continue
        path = entry.get("path")
        reason = entry.get("reason")
        if not isinstance(path, str) or not isinstance(reason, str) or not reason.strip():
            blockers.append(f"POLICY_REFERENCE_ENTRY_INVALID:{index}")
            continue
        parsed.append(path)
    if len(parsed) != len(set(parsed)):
        blockers.append("POLICY_REFERENCE_PATH_DUPLICATED")
    return tuple(parsed)


def _is_quarantined(relative: str, entries: tuple[tuple[str, str], ...]) -> bool:
    for path, boundary in entries:
        if boundary == "module_file" and relative == path:
            return True
        if boundary == "package_prefix" and relative.startswith(path.rstrip("/") + "/"):
            return True
    return False


def _is_exempt(
    relative: str,
    quarantine_entries: tuple[tuple[str, str], ...],
    policy_paths: tuple[str, ...],
) -> bool:
    return _is_quarantined(relative, quarantine_entries) or relative in policy_paths


def _iter_active_files(
    root: Path,
    quarantine_entries: tuple[tuple[str, str], ...],
    policy_paths: tuple[str, ...],
) -> tuple[Path, ...]:
    files: dict[str, Path] = {}
    for target in ACTIVE_SCAN_TARGETS:
        candidate = _repo_file(root, target)
        if candidate.is_file():
            relative = candidate.relative_to(root).as_posix()
            if not _is_exempt(relative, quarantine_entries, policy_paths):
                files[relative] = candidate
            continue
        if not candidate.is_dir():
            raise JupiterV2ContractError(f"active scan target is missing: {target}")
        for path in candidate.rglob("*"):
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            relative = path.relative_to(root).as_posix()
            if not _is_exempt(relative, quarantine_entries, policy_paths):
                files[relative] = path
    return tuple(files[key] for key in sorted(files))


def _validate_quarantine_boundary(
    root: Path,
    entries: tuple[tuple[str, str], ...],
    blockers: list[str],
) -> None:
    manifest = _load_json(root, PRODUCTION_SURFACE_PATH)
    forbidden = _as_dict(
        manifest.get("forbidden"),
        blockers,
        "PRODUCTION_SURFACE_FORBIDDEN_MISSING",
    )
    module_files = set(
        _as_string_list(
            forbidden.get("module_files"),
            blockers,
            "PRODUCTION_SURFACE_MODULE_FILES_INVALID",
        )
    )
    package_prefixes = set(
        _as_string_list(
            forbidden.get("package_prefixes"),
            blockers,
            "PRODUCTION_SURFACE_PACKAGE_PREFIXES_INVALID",
        )
    )
    for path, boundary in entries:
        _require(
            _repo_file(root, path).exists(),
            blockers,
            f"QUARANTINED_PATH_MISSING:{path}",
        )
        if boundary == "module_file":
            _require(
                path in module_files,
                blockers,
                f"QUARANTINE_NOT_IN_PRODUCTION_BOUNDARY:{path}",
            )
        else:
            normalized = path.rstrip("/") + "/"
            _require(
                normalized in package_prefixes,
                blockers,
                f"QUARANTINE_NOT_IN_PRODUCTION_BOUNDARY:{path}",
            )


def _validate_policy_references(
    root: Path,
    policy_paths: tuple[str, ...],
    forbidden_markers: tuple[str, ...],
    blockers: list[str],
) -> None:
    for relative in policy_paths:
        path = _repo_file(root, relative)
        _require(path.is_file(), blockers, f"POLICY_REFERENCE_PATH_MISSING:{relative}")
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        _require(
            any(marker in text for marker in forbidden_markers),
            blockers,
            f"POLICY_REFERENCE_HAS_NO_DEPRECATED_MARKER:{relative}",
        )
        if path.suffix == ".py":
            for token in DIRECT_NETWORK_TOKENS:
                _require(
                    token not in text,
                    blockers,
                    f"POLICY_REFERENCE_DIRECT_NETWORK:{relative}:{token}",
                )


def _mega_b2_method(source: str) -> str | None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise JupiterV2ContractError(f"invalid Python in {MEGA_B2_PATH}: {exc}") from exc
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "JupiterV2BuildAdapter":
            continue
        for member in node.body:
            if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if member.name != "build_request":
                continue
            for child in ast.walk(member):
                if not isinstance(child, ast.Call):
                    continue
                if not isinstance(child.func, ast.Name) or child.func.id != "HttpRequestSpec":
                    continue
                if child.args and isinstance(child.args[0], ast.Constant):
                    value = child.args[0].value
                    return value if isinstance(value, str) else None
    return None


def _validate_mega_b2(source: str, blockers: list[str]) -> str | None:
    method = _mega_b2_method(source)
    _require(
        'CURRENT_JUPITER_BUILD_PATH = "/swap/v2/build"' in source,
        blockers,
        "MEGA_B2_JUPITER_BUILD_PATH_MISMATCH",
    )
    _require(method == EXPECTED_METHOD, blockers, "MEGA_B2_JUPITER_METHOD_MISMATCH")
    _require(
        "JUPITER_BUILD_REQUIRED_PARAMETERS" in source,
        blockers,
        "MEGA_B2_JUPITER_REQUIRED_PARAMETERS_MISSING",
    )
    _require(
        "JUPITER_BUILD_METHOD_NOT_GET" in source,
        blockers,
        "MEGA_B2_ADMISSION_METHOD_GUARD_MISSING",
    )
    _require(
        "quoteResponse" not in source,
        blockers,
        "MEGA_B2_LEGACY_QUOTE_RESPONSE_PAYLOAD_PRESENT",
    )
    return method


def verify_mpr_next_08_jupiter_v2_contract(
    root: str | Path = ROOT,
) -> JupiterV2ContractEvidence:
    repo_root = Path(root).resolve()
    blockers: list[str] = []
    artifact_hashes: dict[str, str] = {}
    required_paths = (
        PRODUCT_CONTRACT_PATH,
        PACKAGED_PRODUCT_CONTRACT_PATH,
        EXTERNAL_CONTRACTS_PATH,
        ROUTER_PATH,
        MEGA_B2_PATH,
        PRODUCTION_SURFACE_PATH,
        QUARANTINE_PATH,
        VERIFY_REPO_PATH,
    )
    for relative in required_paths:
        artifact_hashes[relative] = hashlib.sha256(
            _read_bytes(repo_root, relative)
        ).hexdigest()

    source_contract = _read_bytes(repo_root, PRODUCT_CONTRACT_PATH)
    packaged_contract = _read_bytes(repo_root, PACKAGED_PRODUCT_CONTRACT_PATH)
    _require(
        source_contract == packaged_contract,
        blockers,
        "PRODUCT_CONTRACT_RESOURCE_DRIFT",
    )
    product_contract = _load_json(repo_root, PRODUCT_CONTRACT_PATH)
    endpoints = _as_dict(
        product_contract.get("endpoints"),
        blockers,
        "PRODUCT_CONTRACT_ENDPOINTS_MISSING",
    )
    jupiter = _as_dict(
        endpoints.get("jupiter"),
        blockers,
        "PRODUCT_CONTRACT_JUPITER_MISSING",
    )
    product_paths = _as_string_list(
        jupiter.get("paths"),
        blockers,
        "PRODUCT_CONTRACT_JUPITER_PATHS_INVALID",
    )
    _require(
        jupiter.get("origin") == EXPECTED_ORIGIN,
        blockers,
        "PRODUCT_CONTRACT_JUPITER_ORIGIN_MISMATCH",
    )
    _require(
        frozenset(product_paths) == EXPECTED_PRODUCT_PATHS,
        blockers,
        "PRODUCT_CONTRACT_JUPITER_PATH_SET_MISMATCH",
    )

    docs = _load_yaml(repo_root, EXTERNAL_CONTRACTS_PATH)
    providers = _as_dict(
        docs.get("providers"),
        blockers,
        "EXTERNAL_CONTRACTS_PROVIDERS_MISSING",
    )
    docs_jupiter = _as_dict(
        providers.get("jupiter_router"),
        blockers,
        "EXTERNAL_CONTRACTS_JUPITER_ROUTER_MISSING",
    )
    docs_endpoint_raw = _as_dict(
        docs_jupiter.get("instruction_endpoint"),
        blockers,
        "EXTERNAL_CONTRACTS_JUPITER_ENDPOINT_MISSING",
    )
    docs_endpoint = docs_endpoint_raw.get("path")
    _require(
        docs_jupiter.get("status") == "active",
        blockers,
        "EXTERNAL_CONTRACTS_JUPITER_NOT_ACTIVE",
    )
    _require(
        docs_jupiter.get("base_url") == EXPECTED_ORIGIN,
        blockers,
        "EXTERNAL_CONTRACTS_JUPITER_ORIGIN_MISMATCH",
    )
    _require(
        docs_endpoint_raw.get("method") == EXPECTED_METHOD,
        blockers,
        "EXTERNAL_CONTRACTS_JUPITER_METHOD_MISMATCH",
    )
    _require(
        docs_endpoint == EXPECTED_PATH,
        blockers,
        "EXTERNAL_CONTRACTS_JUPITER_PATH_MISMATCH",
    )
    _require(
        docs_jupiter.get("sole_active_entry_point") == EXPECTED_ADAPTER,
        blockers,
        "EXTERNAL_CONTRACTS_JUPITER_ADAPTER_MISMATCH",
    )

    router_source = _read_text(repo_root, ROUTER_PATH)
    router_endpoint = _assigned_string(
        router_source,
        "JUPITER_ROUTER_ENDPOINT",
        ROUTER_PATH,
    )
    _require(
        router_endpoint == EXPECTED_PATH,
        blockers,
        "JUPITER_ROUTER_ENDPOINT_MISMATCH",
    )
    _require(
        "session.get(" in router_source,
        blockers,
        "JUPITER_ROUTER_HTTP_METHOD_NOT_GET",
    )

    quarantine = _load_json(repo_root, QUARANTINE_PATH)
    _require(
        quarantine.get("schema_version")
        == "mpr-next-08.jupiter-endpoint-quarantine.v1",
        blockers,
        "QUARANTINE_SCHEMA_MISMATCH",
    )
    active_contract = _as_dict(
        quarantine.get("active_contract"),
        blockers,
        "QUARANTINE_ACTIVE_CONTRACT_MISSING",
    )
    _require(
        active_contract
        == {
            "adapter": EXPECTED_ADAPTER,
            "method": EXPECTED_METHOD,
            "origin": EXPECTED_ORIGIN,
            "path": EXPECTED_PATH,
        },
        blockers,
        "QUARANTINE_ACTIVE_CONTRACT_MISMATCH",
    )
    forbidden_markers = _as_string_list(
        quarantine.get("forbidden_endpoint_markers"),
        blockers,
        "QUARANTINE_FORBIDDEN_MARKERS_INVALID",
    )
    _require(
        frozenset(forbidden_markers) == EXPECTED_FORBIDDEN_MARKERS,
        blockers,
        "QUARANTINE_FORBIDDEN_MARKERS_MISMATCH",
    )
    quarantine_entries = _quarantine_entries(quarantine, blockers)
    policy_paths = _policy_reference_paths(quarantine, blockers)
    _validate_quarantine_boundary(repo_root, quarantine_entries, blockers)
    _validate_policy_references(
        repo_root,
        policy_paths,
        forbidden_markers,
        blockers,
    )

    mega_b2_source = _read_text(repo_root, MEGA_B2_PATH)
    mega_b2_method = _validate_mega_b2(mega_b2_source, blockers)

    active_files = _iter_active_files(
        repo_root,
        quarantine_entries,
        policy_paths,
    )
    for path in active_files:
        relative = path.relative_to(repo_root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            blockers.append(f"ACTIVE_SURFACE_NOT_UTF8:{relative}")
            continue
        for marker in forbidden_markers:
            if marker in text:
                blockers.append(f"FORBIDDEN_ACTIVE_JUPITER_ENDPOINT:{relative}:{marker}")

    verify_repo_text = _read_text(repo_root, VERIFY_REPO_PATH)
    _require(
        "scripts/verify_mpr_next_08_jupiter_v2_contract.py" in verify_repo_text,
        blockers,
        "VERIFY_REPO_DOES_NOT_RUN_MPR_NEXT_08",
    )

    unique_blockers = tuple(dict.fromkeys(blockers))
    return JupiterV2ContractEvidence(
        schema_version=SCHEMA_VERSION,
        accepted=not unique_blockers,
        blockers=unique_blockers,
        artifact_hashes=artifact_hashes,
        product_contract_paths=tuple(sorted(product_paths)),
        docs_endpoint=docs_endpoint if isinstance(docs_endpoint, str) else None,
        router_endpoint=router_endpoint,
        mega_b2_method=mega_b2_method,
        quarantined_paths=tuple(sorted(path for path, _ in quarantine_entries)),
        policy_reference_paths=tuple(sorted(policy_paths)),
        scanned_active_files=len(active_files),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT), help="Repository root to verify.")
    parser.add_argument("--json", action="store_true", help="Print evidence as JSON.")
    args = parser.parse_args(argv)

    try:
        evidence = verify_mpr_next_08_jupiter_v2_contract(args.root)
    except JupiterV2ContractError as exc:
        print(f"MPR-NEXT-08 verification error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(evidence.to_dict(), sort_keys=True, indent=2))
    elif evidence.accepted:
        print("MPR-NEXT-08 Jupiter V2 contract verification passed.")
    else:
        print("MPR-NEXT-08 Jupiter V2 contract verification failed:", file=sys.stderr)
        for blocker in evidence.blockers:
            print(f"- {blocker}", file=sys.stderr)
    return 0 if evidence.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
