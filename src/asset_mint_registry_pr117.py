"""PR-117 asset/mint registry and Token-2022 safety gate.

This module is deliberately offline: it validates the committed registry contract
and never connects to RPC, signs transactions, or claims live execution support.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

PR117_SCHEMA_VERSION = "pr117.asset-mint-registry.v1"
PR117_RESULT_SCHEMA_VERSION = "pr117.asset-mint-registry-result.v1"
PR117_DEFAULT_REGISTRY_PATH = "src/resources/asset_mint_registry_pr117.json"
PR117_DEFAULT_UNIVERSE_PATH = "src/resources/discovery_universe.json"
LEGACY_SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFJmNchboJLH2e2UrfW"

_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_TOKEN_2022_EXTENSIONS = frozenset(
    {
        "confidential_transfer",
        "confidential_transfer_fee",
        "cpi_guard",
        "default_account_state",
        "interest_bearing",
        "memo_transfer",
        "non_transferable",
        "permanent_delegate",
        "transfer_fee_amount",
        "transfer_fee_config",
        "transfer_hook",
    }
)


class PR117AssetRegistryError(ValueError):
    """Raised when the PR-117 registry contract is structurally invalid."""


@dataclass(frozen=True, slots=True)
class PairAssetPolicy:
    pair_id: str
    base_mint: str
    intermediate_mint: str
    execution_allowed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PR117AssetRegistryResult:
    schema_version: str
    registry_path: str
    universe_path: str
    registry_valid: bool
    execution_ready: bool
    asset_count: int
    tradable_mint_count: int
    pair_results: tuple[PairAssetPolicy, ...]
    blockers: tuple[str, ...]
    execution_blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_pr117_asset_mint_registry(
    *,
    repo_root: str | Path,
    registry_path: str | Path = PR117_DEFAULT_REGISTRY_PATH,
    universe_path: str | Path = PR117_DEFAULT_UNIVERSE_PATH,
) -> PR117AssetRegistryResult:
    root = Path(repo_root).resolve()
    registry_rel = _safe_relative_path(registry_path, "registry_path")
    universe_rel = _safe_relative_path(universe_path, "universe_path")
    blockers: list[str] = []
    execution_blockers: list[str] = []
    warnings: list[str] = []

    try:
        registry = _read_json(root / registry_rel)
        universe = _read_json(root / universe_rel)
    except PR117AssetRegistryError as exc:
        return _result(
            registry_rel, universe_rel, False, False, 0, 0, (), [str(exc)], [], []
        )

    schema_version = _string(registry, "schema_version")
    if schema_version != PR117_SCHEMA_VERSION:
        blockers.append(f"PR117_SCHEMA_UNSUPPORTED:{schema_version}")

    policy = _mapping(registry.get("policy"), "policy")
    token_2022_fail_closed = _bool(policy, "all_token_2022_fail_closed", default=True)
    extension_policy = _extension_policy(registry, blockers)
    assets = _assets(registry, blockers)

    for asset in assets:
        _validate_asset(
            asset,
            extension_policy,
            token_2022_fail_closed,
            blockers,
            execution_blockers,
            warnings,
        )

    pairs = _pairs(
        universe, {asset["mint"]: asset for asset in assets}, execution_blockers
    )
    tradable_count = sum(
        1
        for asset in assets
        if asset["admission"] == "tradable"
        and not any(f":{asset['symbol']}" in item for item in execution_blockers)
    )
    if tradable_count == 0:
        warnings.append("PR117_NO_MINTS_CURRENTLY_EXECUTION_TRADABLE")

    registry_valid = not blockers
    execution_ready = registry_valid and tradable_count > 0 and not execution_blockers
    return _result(
        registry_rel,
        universe_rel,
        registry_valid,
        execution_ready,
        len(assets),
        tradable_count,
        pairs,
        blockers,
        execution_blockers,
        warnings,
    )


def _validate_asset(
    asset: Mapping[str, object],
    extension_policy: Mapping[str, str],
    token_2022_fail_closed: bool,
    blockers: list[str],
    execution_blockers: list[str],
    warnings: list[str],
) -> None:
    symbol = _string(asset, "symbol")
    token_program = _string(asset, "token_program")
    expected_program = (
        LEGACY_SPL_TOKEN_PROGRAM_ID
        if token_program == "legacy-spl-token"
        else TOKEN_2022_PROGRAM_ID
    )
    extensions = tuple(
        _string_value(item, "extensions[]")
        for item in _sequence(asset, "extensions", default=())
    )

    if not _BASE58_RE.fullmatch(_string(asset, "mint")):
        blockers.append(f"PR117_MINT_ADDRESS_INVALID:{symbol}")
    if _string(asset, "cluster") != "mainnet-beta":
        blockers.append(
            f"PR117_CLUSTER_UNSUPPORTED:{symbol}:{_string(asset, 'cluster')}"
        )
    if token_program not in {"legacy-spl-token", "token-2022"}:
        blockers.append(f"PR117_TOKEN_PROGRAM_UNSUPPORTED:{symbol}:{token_program}")
    if _string(asset, "token_program_id") != expected_program:
        blockers.append(f"PR117_TOKEN_PROGRAM_ID_MISMATCH:{symbol}")
    if not 0 <= _int(asset, "decimals") <= 18:
        blockers.append(f"PR117_DECIMALS_OUT_OF_RANGE:{symbol}")
    if not _string(asset, "provenance").strip():
        blockers.append(f"PR117_PROVENANCE_MISSING:{symbol}")
    if token_program == "legacy-spl-token" and extensions:
        blockers.append(f"PR117_LEGACY_SPL_EXTENSIONS_NOT_ALLOWED:{symbol}")

    if _string(asset, "admission") != "tradable":
        warnings.append(f"PR117_MINT_NOT_EXECUTION_TRADABLE:{symbol}")
        return

    _require_evidence(asset.get("rpc_evidence"), symbol, "RPC", execution_blockers)
    _require_evidence(
        asset.get("authority_evidence"), symbol, "AUTHORITY", execution_blockers
    )
    if (
        not _bool(asset, "reviewed", default=False)
        or not (_optional_string(asset, "reviewer") or "").strip()
    ):
        execution_blockers.append(f"PR117_MINT_REVIEW_MISSING:{symbol}")

    if token_program == "token-2022":
        if token_2022_fail_closed:
            execution_blockers.append(f"PR117_TOKEN_2022_FAIL_CLOSED:{symbol}")
        if not extensions:
            execution_blockers.append(f"PR117_TOKEN_2022_EXTENSIONS_MISSING:{symbol}")
        for extension in extensions:
            if extension_policy.get(extension) != "supported":
                execution_blockers.append(
                    f"PR117_TOKEN_2022_EXTENSION_NOT_SUPPORTED:{symbol}:{extension}"
                )

    if _string(asset, "asset_class") == "lst":
        _require_evidence(
            asset.get("oracle_evidence"), symbol, "ORACLE", execution_blockers
        )
        _require_evidence(
            asset.get("redemption_evidence"), symbol, "REDEMPTION", execution_blockers
        )


def _require_evidence(
    value: object,
    symbol: str,
    kind: str,
    execution_blockers: list[str],
) -> None:
    if value is None:
        execution_blockers.append(f"PR117_{kind}_EVIDENCE_MISSING:{symbol}")
        return
    evidence = _mapping(value, f"{kind.lower()}_evidence")
    reviewed = _string(evidence, "status") == "reviewed" and bool(
        (_optional_string(evidence, "reviewer") or "").strip()
    )
    if not reviewed:
        execution_blockers.append(f"PR117_{kind}_EVIDENCE_NOT_REVIEWED:{symbol}")
    if _optional_int(evidence, "slot") is None or _optional_int(evidence, "slot") <= 0:
        execution_blockers.append(f"PR117_{kind}_EVIDENCE_SLOT_MISSING:{symbol}")
    sha256 = _optional_string(evidence, "sha256")
    if sha256 is None or not _valid_sha256(sha256):
        execution_blockers.append(f"PR117_{kind}_EVIDENCE_HASH_INVALID:{symbol}")


def _pairs(
    universe: Mapping[str, object],
    assets_by_mint: Mapping[object, Mapping[str, object]],
    execution_blockers: list[str],
) -> tuple[PairAssetPolicy, ...]:
    results: list[PairAssetPolicy] = []
    for item in _sequence(universe, "pairs"):
        pair = _mapping(item, "pairs[]")
        pair_id = _string(pair, "pair_id")
        base_mint = _string(pair, "base_mint")
        intermediate_mint = _string(pair, "intermediate_mint")
        reasons = _pair_reasons(base_mint, intermediate_mint, assets_by_mint)
        if _bool(pair, "required", default=False) and reasons:
            execution_blockers.append(
                f"PR117_REQUIRED_PAIR_NOT_EXECUTION_READY:{pair_id}"
            )
        results.append(
            PairAssetPolicy(
                pair_id, base_mint, intermediate_mint, not reasons, tuple(reasons)
            )
        )
    return tuple(results)


def _pair_reasons(
    base_mint: str,
    intermediate_mint: str,
    assets_by_mint: Mapping[object, Mapping[str, object]],
) -> list[str]:
    reasons: list[str] = []
    for side, mint in (("BASE", base_mint), ("INTERMEDIATE", intermediate_mint)):
        asset = assets_by_mint.get(mint)
        if asset is None:
            reasons.append(f"{side}_MINT_NOT_IN_PR117_REGISTRY:{mint}")
        elif _string(asset, "admission") != "tradable":
            reasons.append(f"{side}_MINT_NOT_TRADABLE:{_string(asset, 'symbol')}")
    return reasons


def _assets(
    registry: Mapping[str, object],
    blockers: list[str],
) -> tuple[Mapping[str, object], ...]:
    assets: list[Mapping[str, object]] = []
    seen: set[str] = set()
    for index, item in enumerate(_sequence(registry, "assets")):
        try:
            asset = _mapping(item, f"assets[{index}]")
            _required_asset_fields(asset)
        except (PR117AssetRegistryError, ValueError) as exc:
            blockers.append(f"PR117_ASSET_ENTRY_INVALID:{index}:{exc}")
            continue
        mint = _string(asset, "mint")
        if mint in seen:
            blockers.append(f"PR117_DUPLICATE_MINT:{mint}")
        seen.add(mint)
        assets.append(asset)
    return tuple(assets)


def _required_asset_fields(asset: Mapping[str, object]) -> None:
    for field in (
        "symbol",
        "mint",
        "cluster",
        "token_program",
        "token_program_id",
        "asset_class",
        "admission",
        "provenance",
    ):
        _string(asset, field)
    _int(asset, "decimals")
    _mapping(asset.get("rpc_evidence"), "rpc_evidence")
    _mapping(asset.get("authority_evidence"), "authority_evidence")


def _extension_policy(
    registry: Mapping[str, object],
    blockers: list[str],
) -> dict[str, str]:
    matrix = _mapping(
        registry.get("token_2022_extension_matrix"), "token_2022_extension_matrix"
    )
    policy: dict[str, str] = {}
    for item in _sequence(matrix, "extensions"):
        row = _mapping(item, "token_2022_extension_matrix.extensions[]")
        policy[_string(row, "name")] = _string(row, "disposition")
    for name in sorted(_FORBIDDEN_TOKEN_2022_EXTENSIONS - set(policy)):
        blockers.append(f"PR117_EXTENSION_POLICY_MISSING:{name}")
    return policy


def _read_json(path: Path) -> Mapping[str, object]:
    try:
        return _mapping(json.loads(path.read_text(encoding="utf-8")), str(path))
    except FileNotFoundError as exc:
        raise PR117AssetRegistryError(f"FILE_MISSING:{path}") from exc
    except json.JSONDecodeError as exc:
        raise PR117AssetRegistryError(f"JSON_INVALID:{path}:{exc}") from exc


def _result(
    registry_path: str,
    universe_path: str,
    registry_valid: bool,
    execution_ready: bool,
    asset_count: int,
    tradable_mint_count: int,
    pair_results: Sequence[PairAssetPolicy],
    blockers: Sequence[str],
    execution_blockers: Sequence[str],
    warnings: Sequence[str],
) -> PR117AssetRegistryResult:
    return PR117AssetRegistryResult(
        schema_version=PR117_RESULT_SCHEMA_VERSION,
        registry_path=registry_path,
        universe_path=universe_path,
        registry_valid=registry_valid,
        execution_ready=execution_ready,
        asset_count=asset_count,
        tradable_mint_count=tradable_mint_count,
        pair_results=tuple(pair_results),
        blockers=tuple(dict.fromkeys(blockers)),
        execution_blockers=tuple(dict.fromkeys(execution_blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _safe_relative_path(value: str | Path, field: str) -> str:
    normalized = str(value).replace("\\", "/")
    if Path(value).is_absolute() or not normalized or normalized.startswith(("/", "~")):
        raise PR117AssetRegistryError(f"PATH_MUST_BE_REPO_RELATIVE:{field}")
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise PR117AssetRegistryError(f"PATH_UNSAFE:{field}")
    return normalized


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PR117AssetRegistryError(f"FIELD_NOT_OBJECT:{field}")
    return value


def _sequence(
    payload: Mapping[str, object],
    field: str,
    *,
    default: Sequence[object] | None = None,
) -> Sequence[object]:
    value = payload.get(field, default)
    if not isinstance(value, (list, tuple)):
        raise PR117AssetRegistryError(f"FIELD_NOT_LIST:{field}")
    return value


def _string(
    payload: Mapping[str, object], field: str, default: str | None = None
) -> str:
    return _string_value(payload.get(field, default), field)


def _optional_string(payload: Mapping[str, object], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    return _string_value(value, field)


def _string_value(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise PR117AssetRegistryError(f"FIELD_NOT_STRING:{field}")
    return value


def _bool(
    payload: Mapping[str, object],
    field: str,
    *,
    default: bool | None = None,
) -> bool:
    value = payload.get(field, default)
    if not isinstance(value, bool):
        raise PR117AssetRegistryError(f"FIELD_NOT_BOOL:{field}")
    return value


def _int(payload: Mapping[str, object], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise PR117AssetRegistryError(f"FIELD_NOT_INT:{field}")
    return value


def _optional_int(payload: Mapping[str, object], field: str) -> int | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise PR117AssetRegistryError(f"FIELD_NOT_INT:{field}")
    return value


def _valid_sha256(value: str) -> bool:
    return bool(_SHA256_RE.fullmatch(value)) and value != "0" * 64


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the PR-117 asset/mint registry safety gate."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--registry-path", default=PR117_DEFAULT_REGISTRY_PATH)
    parser.add_argument("--universe-path", default=PR117_DEFAULT_UNIVERSE_PATH)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-execution-ready", action="store_true")
    args = parser.parse_args(argv)
    result = evaluate_pr117_asset_mint_registry(
        repo_root=args.repo_root,
        registry_path=args.registry_path,
        universe_path=args.universe_path,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"PR-117 registry valid: {result.registry_valid}")
        print(f"PR-117 execution ready: {result.execution_ready}")
    if not result.registry_valid:
        return 1
    if args.require_execution_ready and not result.execution_ready:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
