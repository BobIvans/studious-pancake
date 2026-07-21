"""PR-117 asset/mint registry and Token-2022 safety gate.

The discovery universe previously listed mints with decimals only. PR-117 adds
an offline registry policy boundary: a mint can become execution-tradable only
when token program, authority policy, Token-2022 extensions, provenance and RPC
evidence are all explicit.

This module never connects to RPC and never enables trading. It validates the
registry contract that later online attestation code must populate.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from enum import StrEnum
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

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
        "transfer_fee_config",
        "transfer_fee_amount",
        "transfer_hook",
        "permanent_delegate",
        "default_account_state",
        "non_transferable",
        "memo_transfer",
        "cpi_guard",
        "interest_bearing",
        "confidential_transfer",
        "confidential_transfer_fee",
    }
)


class PR117AssetRegistryError(ValueError):
    """Raised when a PR-117 registry file is structurally invalid."""


class AssetAdmission(StrEnum):
    """Execution admission for one mint."""

    TRADABLE = "tradable"
    DISCOVERY_ONLY = "discovery-only"
    FORBIDDEN = "forbidden"


class TokenProgramKind(StrEnum):
    """Supported token program identities."""

    LEGACY_SPL = "legacy-spl-token"
    TOKEN_2022 = "token-2022"


class ExtensionDisposition(StrEnum):
    """Policy disposition for a Token-2022 extension."""

    SUPPORTED = "supported"
    DISCOVERY_ONLY = "discovery-only"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True, slots=True)
class AssetEvidenceRef:
    """Non-secret evidence pointer for a mint or authority review."""

    status: str
    slot: int | None = None
    sha256: str | None = None
    source: str = ""
    reviewer: str | None = None

    @property
    def reviewed(self) -> bool:
        return self.status == "reviewed" and bool((self.reviewer or "").strip())


@dataclass(frozen=True, slots=True)
class AssetMintEntry:
    """One canonical mint entry consumed by the PR-117 policy."""

    symbol: str
    mint: str
    cluster: str
    token_program: TokenProgramKind
    token_program_id: str
    decimals: int
    asset_class: str
    admission: AssetAdmission
    provenance: str
    rpc_evidence: AssetEvidenceRef
    authority_evidence: AssetEvidenceRef
    extensions: tuple[str, ...] = ()
    oracle_evidence: AssetEvidenceRef | None = None
    redemption_evidence: AssetEvidenceRef | None = None
    reviewed: bool = False
    reviewer: str | None = None


@dataclass(frozen=True, slots=True)
class PairAssetPolicy:
    """Execution policy for one configured discovery pair."""

    pair_id: str
    base_mint: str
    intermediate_mint: str
    execution_allowed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PR117AssetRegistryResult:
    """Machine-readable result for the PR-117 asset/mint safety gate."""

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
    """Evaluate asset registry safety without making online/RPC claims."""

    root = Path(repo_root).resolve()
    registry_rel = _safe_relative_path(registry_path, "registry_path")
    universe_rel = _safe_relative_path(universe_path, "universe_path")
    registry_file = root / registry_rel
    universe_file = root / universe_rel

    blockers: list[str] = []
    execution_blockers: list[str] = []
    warnings: list[str] = []

    registry_payload = _read_json_object(registry_file)
    universe_payload = _read_json_object(universe_file)

    schema_version = _string(registry_payload, "schema_version")
    if schema_version != PR117_SCHEMA_VERSION:
        blockers.append(f"PR117_SCHEMA_UNSUPPORTED:{schema_version}")

    extension_policy = _extension_policy(registry_payload, blockers)
    all_token_2022_forbidden = _bool(
        _mapping(registry_payload.get("policy"), "policy"),
        "all_token_2022_fail_closed",
        default=True,
    )

    entries = _asset_entries(registry_payload, blockers)
    entry_by_mint = {entry.mint: entry for entry in entries}
    for entry in entries:
        _validate_entry(
            entry,
            extension_policy,
            all_token_2022_forbidden,
            blockers,
            execution_blockers,
            warnings,
        )

    pair_results = _evaluate_universe_pairs(
        universe_payload,
        entry_by_mint,
        execution_blockers,
    )
    tradable_count = sum(
        1
        for entry in entries
        if entry.admission is AssetAdmission.TRADABLE
        and _asset_has_no_execution_blockers(entry, execution_blockers)
    )

    if tradable_count == 0:
        warnings.append("PR117_NO_MINTS_CURRENTLY_EXECUTION_TRADABLE")

    registry_valid = not blockers
    execution_ready = registry_valid and tradable_count > 0 and not execution_blockers
    return PR117AssetRegistryResult(
        schema_version=PR117_RESULT_SCHEMA_VERSION,
        registry_path=registry_rel,
        universe_path=universe_rel,
        registry_valid=registry_valid,
        execution_ready=execution_ready,
        asset_count=len(entries),
        tradable_mint_count=tradable_count,
        pair_results=pair_results,
        blockers=tuple(dict.fromkeys(blockers)),
        execution_blockers=tuple(dict.fromkeys(execution_blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _asset_has_no_execution_blockers(
    entry: AssetMintEntry,
    execution_blockers: Sequence[str],
) -> bool:
    marker = f":{entry.symbol}"
    return not any(marker in blocker for blocker in execution_blockers)


def _validate_entry(
    entry: AssetMintEntry,
    extension_policy: Mapping[str, ExtensionDisposition],
    all_token_2022_forbidden: bool,
    blockers: list[str],
    execution_blockers: list[str],
    warnings: list[str],
) -> None:
    prefix = entry.symbol
    if not _BASE58_RE.fullmatch(entry.mint):
        blockers.append(f"PR117_MINT_ADDRESS_INVALID:{prefix}")
    if entry.cluster != "mainnet-beta":
        blockers.append(f"PR117_CLUSTER_UNSUPPORTED:{prefix}:{entry.cluster}")
    if entry.decimals < 0 or entry.decimals > 18:
        blockers.append(f"PR117_DECIMALS_OUT_OF_RANGE:{prefix}")
    if not entry.provenance.strip():
        blockers.append(f"PR117_PROVENANCE_MISSING:{prefix}")

    expected_program = (
        LEGACY_SPL_TOKEN_PROGRAM_ID
        if entry.token_program is TokenProgramKind.LEGACY_SPL
        else TOKEN_2022_PROGRAM_ID
    )
    if entry.token_program_id != expected_program:
        blockers.append(f"PR117_TOKEN_PROGRAM_ID_MISMATCH:{prefix}")

    if entry.token_program is TokenProgramKind.LEGACY_SPL and entry.extensions:
        blockers.append(f"PR117_LEGACY_SPL_EXTENSIONS_NOT_ALLOWED:{prefix}")

    if entry.admission is not AssetAdmission.TRADABLE:
        warnings.append(f"PR117_MINT_NOT_EXECUTION_TRADABLE:{prefix}")
        return

    _require_reviewed_evidence(entry.rpc_evidence, prefix, "RPC", execution_blockers)
    _require_reviewed_evidence(
        entry.authority_evidence,
        prefix,
        "AUTHORITY",
        execution_blockers,
    )
    if not entry.reviewed or not (entry.reviewer or "").strip():
        execution_blockers.append(f"PR117_MINT_REVIEW_MISSING:{prefix}")

    if entry.token_program is TokenProgramKind.TOKEN_2022:
        if all_token_2022_forbidden:
            execution_blockers.append(f"PR117_TOKEN_2022_FAIL_CLOSED:{prefix}")
        if not entry.extensions:
            execution_blockers.append(f"PR117_TOKEN_2022_EXTENSIONS_MISSING:{prefix}")
        for extension in entry.extensions:
            disposition = extension_policy.get(extension)
            if disposition is not ExtensionDisposition.SUPPORTED:
                execution_blockers.append(
                    f"PR117_TOKEN_2022_EXTENSION_NOT_SUPPORTED:{prefix}:{extension}"
                )

    if entry.asset_class == "lst":
        _require_reviewed_evidence(
            entry.oracle_evidence,
            prefix,
            "ORACLE",
            execution_blockers,
        )
        _require_reviewed_evidence(
            entry.redemption_evidence,
            prefix,
            "REDEMPTION",
            execution_blockers,
        )


def _require_reviewed_evidence(
    evidence: AssetEvidenceRef | None,
    symbol: str,
    name: str,
    execution_blockers: list[str],
) -> None:
    if evidence is None:
        execution_blockers.append(f"PR117_{name}_EVIDENCE_MISSING:{symbol}")
        return
    if not evidence.reviewed:
        execution_blockers.append(f"PR117_{name}_EVIDENCE_NOT_REVIEWED:{symbol}")
    if evidence.slot is None or evidence.slot <= 0:
        execution_blockers.append(f"PR117_{name}_EVIDENCE_SLOT_MISSING:{symbol}")
    if evidence.sha256 is None or not _valid_sha256(evidence.sha256):
        execution_blockers.append(f"PR117_{name}_EVIDENCE_HASH_INVALID:{symbol}")


def _evaluate_universe_pairs(
    universe_payload: Mapping[str, object],
    entry_by_mint: Mapping[str, AssetMintEntry],
    execution_blockers: list[str],
) -> tuple[PairAssetPolicy, ...]:
    pairs: list[PairAssetPolicy] = []
    for item in _sequence(universe_payload, "pairs"):
        pair = _mapping(item, "pairs[]")
        pair_id = _string(pair, "pair_id")
        base_mint = _string(pair, "base_mint")
        intermediate_mint = _string(pair, "intermediate_mint")
        required = _bool(pair, "required", default=False)
        reasons: list[str] = []

        base_entry = entry_by_mint.get(base_mint)
        intermediate_entry = entry_by_mint.get(intermediate_mint)
        if base_entry is None:
            reasons.append(f"BASE_MINT_NOT_IN_PR117_REGISTRY:{base_mint}")
        elif base_entry.admission is not AssetAdmission.TRADABLE:
            reasons.append(f"BASE_MINT_NOT_TRADABLE:{base_entry.symbol}")

        if intermediate_entry is None:
            reasons.append(
                f"INTERMEDIATE_MINT_NOT_IN_PR117_REGISTRY:{intermediate_mint}"
            )
        elif intermediate_entry.admission is not AssetAdmission.TRADABLE:
            reasons.append(
                f"INTERMEDIATE_MINT_NOT_TRADABLE:{intermediate_entry.symbol}"
            )

        execution_allowed = not reasons
        if required and not execution_allowed:
            execution_blockers.append(
                f"PR117_REQUIRED_PAIR_NOT_EXECUTION_READY:{pair_id}"
            )

        pairs.append(
            PairAssetPolicy(
                pair_id=pair_id,
                base_mint=base_mint,
                intermediate_mint=intermediate_mint,
                execution_allowed=execution_allowed,
                reasons=tuple(reasons),
            )
        )

    return tuple(pairs)


def _asset_entries(
    registry_payload: Mapping[str, object],
    blockers: list[str],
) -> tuple[AssetMintEntry, ...]:
    entries: list[AssetMintEntry] = []
    seen: set[str] = set()
    for index, item in enumerate(_sequence(registry_payload, "assets")):
        try:
            entry = _parse_asset_entry(_mapping(item, f"assets[{index}]"))
        except (PR117AssetRegistryError, ValueError) as exc:
            blockers.append(f"PR117_ASSET_ENTRY_INVALID:{index}:{exc}")
            continue
        if entry.mint in seen:
            blockers.append(f"PR117_DUPLICATE_MINT:{entry.mint}")
        seen.add(entry.mint)
        entries.append(entry)
    return tuple(entries)


def _parse_asset_entry(payload: Mapping[str, object]) -> AssetMintEntry:
    return AssetMintEntry(
        symbol=_string(payload, "symbol"),
        mint=_string(payload, "mint"),
        cluster=_string(payload, "cluster"),
        token_program=TokenProgramKind(_string(payload, "token_program")),
        token_program_id=_string(payload, "token_program_id"),
        decimals=_int(payload, "decimals"),
        asset_class=_string(payload, "asset_class"),
        admission=AssetAdmission(_string(payload, "admission")),
        provenance=_string(payload, "provenance"),
        rpc_evidence=_parse_evidence(
            _mapping(payload.get("rpc_evidence"), "rpc_evidence")
        ),
        authority_evidence=_parse_evidence(
            _mapping(payload.get("authority_evidence"), "authority_evidence")
        ),
        extensions=tuple(
            _string_value(item, "extensions[]")
            for item in _sequence(payload, "extensions", default=())
        ),
        oracle_evidence=_optional_evidence(payload.get("oracle_evidence")),
        redemption_evidence=_optional_evidence(payload.get("redemption_evidence")),
        reviewed=_bool(payload, "reviewed", default=False),
        reviewer=_optional_string(payload, "reviewer"),
    )


def _parse_evidence(payload: Mapping[str, object]) -> AssetEvidenceRef:
    return AssetEvidenceRef(
        status=_string(payload, "status"),
        slot=_optional_int(payload, "slot"),
        sha256=_optional_string(payload, "sha256"),
        source=_string(payload, "source", default=""),
        reviewer=_optional_string(payload, "reviewer"),
    )


def _optional_evidence(value: object) -> AssetEvidenceRef | None:
    if value is None:
        return None
    return _parse_evidence(_mapping(value, "optional_evidence"))


def _extension_policy(
    registry_payload: Mapping[str, object],
    blockers: list[str],
) -> dict[str, ExtensionDisposition]:
    matrix_payload = _mapping(
        registry_payload.get("token_2022_extension_matrix"),
        "token_2022_extension_matrix",
    )
    observed: dict[str, ExtensionDisposition] = {}
    for item in _sequence(matrix_payload, "extensions"):
        row = _mapping(item, "token_2022_extension_matrix.extensions[]")
        name = _string(row, "name")
        try:
            observed[name] = ExtensionDisposition(_string(row, "disposition"))
        except ValueError as exc:
            blockers.append(f"PR117_EXTENSION_DISPOSITION_INVALID:{name}:{exc}")
    missing = _FORBIDDEN_TOKEN_2022_EXTENSIONS - set(observed)
    for name in sorted(missing):
        blockers.append(f"PR117_EXTENSION_POLICY_MISSING:{name}")
    return observed


def _read_json_object(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PR117AssetRegistryError(f"FILE_MISSING:{path}") from exc
    except json.JSONDecodeError as exc:
        raise PR117AssetRegistryError(f"JSON_INVALID:{path}:{exc}") from exc
    return _mapping(payload, str(path))


def _safe_relative_path(value: str | Path, field: str) -> str:
    path = Path(value)
    if path.is_absolute():
        raise PR117AssetRegistryError(f"PATH_MUST_BE_REPO_RELATIVE:{field}")
    normalized = str(value).replace("\\", "/")
    parts = normalized.split("/")
    if not normalized or normalized.startswith(("/", "~")):
        raise PR117AssetRegistryError(f"PATH_MUST_BE_REPO_RELATIVE:{field}")
    if any(part in {"", ".", ".."} for part in parts):
        raise PR117AssetRegistryError(f"PATH_UNSAFE:{field}")
    return normalized


def _valid_sha256(value: str) -> bool:
    return bool(_SHA256_RE.fullmatch(value)) and value != "0" * 64


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
    payload: Mapping[str, object],
    field: str,
    *,
    default: str | None = None,
) -> str:
    value = payload.get(field, default)
    return _string_value(value, field)


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

    try:
        result = evaluate_pr117_asset_mint_registry(
            repo_root=args.repo_root,
            registry_path=args.registry_path,
            universe_path=args.universe_path,
        )
    except PR117AssetRegistryError as exc:
        result = PR117AssetRegistryResult(
            schema_version=PR117_RESULT_SCHEMA_VERSION,
            registry_path=str(args.registry_path),
            universe_path=str(args.universe_path),
            registry_valid=False,
            execution_ready=False,
            asset_count=0,
            tradable_mint_count=0,
            pair_results=(),
            blockers=(f"PR117_REGISTRY_ERROR:{exc}",),
            execution_blockers=(),
            warnings=(),
        )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"PR-117 registry valid: {result.registry_valid}")
        print(f"PR-117 execution ready: {result.execution_ready}")
        for blocker in result.blockers:
            print(f"BLOCKER: {blocker}")
        for blocker in result.execution_blockers:
            print(f"EXECUTION_BLOCKER: {blocker}")
        for warning in result.warnings:
            print(f"WARNING: {warning}")

    if not result.registry_valid:
        return 1
    if args.require_execution_ready and not result.execution_ready:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AssetAdmission",
    "AssetEvidenceRef",
    "AssetMintEntry",
    "ExtensionDisposition",
    "LEGACY_SPL_TOKEN_PROGRAM_ID",
    "PR117AssetRegistryError",
    "PR117AssetRegistryResult",
    "PR117_DEFAULT_REGISTRY_PATH",
    "PR117_DEFAULT_UNIVERSE_PATH",
    "PR117_RESULT_SCHEMA_VERSION",
    "PR117_SCHEMA_VERSION",
    "PairAssetPolicy",
    "TOKEN_2022_PROGRAM_ID",
    "TokenProgramKind",
    "evaluate_pr117_asset_mint_registry",
    "main",
]
