"""PR-125 LST oracle/redemption governance policy.

This module is deliberately offline. It validates the committed LST policy and
returns fail-closed decisions; it does not call RPC, quote DEX routes, redeem,
unstake, submit transactions, or claim that any LST execution path is live.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

PR125_SCHEMA_VERSION = "pr125.lst-governance.v1"
PR125_RESULT_SCHEMA_VERSION = "pr125.lst-governance-result.v1"
PR125_DEFAULT_POLICY_PATH = "src/resources/lst_governance_pr125.json"
PR125_DEFAULT_UNIVERSE_PATH = "src/resources/discovery_universe.json"
LEGACY_SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFJmNchboJLH2e2UrfW"
_REQUIRED_LST_SYMBOLS = frozenset({"JitoSOL", "mSOL", "bSOL"})
_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


class PR125LSTGovernanceError(ValueError):
    """Raised when the PR-125 LST governance contract is invalid."""


@dataclass(frozen=True, slots=True)
class LSTAssetDecision:
    symbol: str
    mint: str
    execution_allowed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LSTPairDecision:
    pair_id: str
    symbol: str
    required: bool
    execution_allowed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PR125LSTGovernanceResult:
    schema_version: str
    policy_path: str
    universe_path: str
    policy_valid: bool
    lst_execution_ready: bool
    asset_decisions: tuple[LSTAssetDecision, ...]
    pair_decisions: tuple[LSTPairDecision, ...]
    blockers: tuple[str, ...]
    execution_blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_pr125_lst_governance_policy(
    *,
    repo_root: str | Path,
    policy_path: str | Path = PR125_DEFAULT_POLICY_PATH,
    universe_path: str | Path = PR125_DEFAULT_UNIVERSE_PATH,
) -> PR125LSTGovernanceResult:
    """Evaluate the committed LST policy without touching the network."""

    root = Path(repo_root).resolve()
    policy_rel = _safe_relative_path(policy_path, "policy_path")
    universe_rel = _safe_relative_path(universe_path, "universe_path")
    blockers: list[str] = []
    execution_blockers: list[str] = []
    warnings: list[str] = []

    try:
        policy = _read_json(root / policy_rel)
        universe = _read_json(root / universe_rel)
    except PR125LSTGovernanceError as exc:
        return _result(policy_rel, universe_rel, False, (), (), [str(exc)], [], [])

    schema_version = _string(policy, "schema_version")
    if schema_version != PR125_SCHEMA_VERSION:
        blockers.append(f"PR125_SCHEMA_UNSUPPORTED:{schema_version}")

    contract = _mapping(policy.get("policy"), "policy")
    _validate_global_policy(contract, blockers)
    strategies = _strategies(policy, blockers)
    assets = _assets(policy, blockers)
    asset_decisions = _asset_decisions(assets, contract, execution_blockers)
    pair_decisions = _pair_decisions(universe, asset_decisions, contract, blockers)

    if strategies.get("lst_fair_value_depeg") is None:
        blockers.append("PR125_FAIR_VALUE_STRATEGY_MISSING")
    if strategies.get("lst_redemption_unstake") is None:
        blockers.append("PR125_REDEMPTION_STRATEGY_MISSING")
    if strategies.get("circular_dex_arbitrage") is None:
        blockers.append("PR125_CIRCULAR_DEX_STRATEGY_MISSING")

    for decision in asset_decisions:
        execution_blockers.extend(
            f"{reason}:{decision.symbol}" for reason in decision.reasons
        )
    for decision in pair_decisions:
        execution_blockers.extend(
            f"{reason}:{decision.pair_id}" for reason in decision.reasons
        )

    policy_valid = not blockers
    lst_execution_ready = _execution_ready(
        policy_valid,
        asset_decisions,
        pair_decisions,
    )
    if not lst_execution_ready:
        warnings.append("PR125_LST_EXECUTION_DISABLED_UNTIL_REVIEWED_EVIDENCE")

    return _result(
        policy_rel,
        universe_rel,
        policy_valid,
        asset_decisions,
        pair_decisions,
        blockers,
        execution_blockers,
        warnings,
    )


def _validate_global_policy(
    contract: Mapping[str, object],
    blockers: list[str],
) -> None:
    if _bool(contract, "fair_value_requires_oracle_and_redemption") is not True:
        blockers.append("PR125_FAIR_VALUE_MUST_REQUIRE_ORACLE_AND_REDEMPTION")
    if _bool(contract, "abnormal_redemption_state_blocks") is not True:
        blockers.append("PR125_ABNORMAL_REDEMPTION_MUST_BLOCK")
    if _int(contract, "depeg_kill_switch_bps") <= 0:
        blockers.append("PR125_DEPEG_KILL_SWITCH_INVALID")
    if _int(contract, "max_total_lst_exposure_pct") != 0:
        blockers.append("PR125_TOTAL_LST_EXPOSURE_MUST_DEFAULT_ZERO")
    if _bool(contract, "optional_lst_pairs_enabled_by_default") is not False:
        blockers.append("PR125_OPTIONAL_LST_PAIRS_MUST_DEFAULT_DISABLED")


def _strategies(
    policy: Mapping[str, object],
    blockers: list[str],
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for item in _sequence(policy, "strategies"):
        strategy = _mapping(item, "strategies[]")
        strategy_id = _string(strategy, "strategy_id")
        result[strategy_id] = strategy
        price_sources = tuple(
            _string_value(value, f"strategies[{strategy_id}].price_sources[]")
            for value in _sequence(strategy, "price_sources", default=())
        )
        if strategy_id == "lst_fair_value_depeg":
            _validate_fair_value_strategy(price_sources, blockers)
        if strategy_id.startswith("lst_") and _bool(strategy, "enabled") is True:
            blockers.append(f"PR125_LST_STRATEGY_ENABLED_BY_DEFAULT:{strategy_id}")
    return result


def _validate_fair_value_strategy(
    price_sources: Sequence[str],
    blockers: list[str],
) -> None:
    if price_sources == ("dex_route_quote",):
        blockers.append("PR125_FAIR_VALUE_USES_DEX_ONLY")


def _assets(
    policy: Mapping[str, object],
    blockers: list[str],
) -> tuple[Mapping[str, object], ...]:
    assets: list[Mapping[str, object]] = []
    seen_mints: set[str] = set()
    symbols: set[str] = set()

    for item in _sequence(policy, "assets"):
        asset = _mapping(item, "assets[]")
        symbol = _string(asset, "symbol")
        mint = _string(asset, "mint")
        symbols.add(symbol)
        if mint in seen_mints:
            blockers.append(f"PR125_DUPLICATE_MINT:{mint}")
        seen_mints.add(mint)
        if not _BASE58_RE.fullmatch(mint):
            blockers.append(f"PR125_MINT_ADDRESS_INVALID:{symbol}")
        if _string(asset, "cluster") != "mainnet-beta":
            blockers.append(f"PR125_CLUSTER_UNSUPPORTED:{symbol}")
        _validate_token_contract(asset, blockers)
        assets.append(asset)

    for symbol in sorted(_REQUIRED_LST_SYMBOLS - symbols):
        blockers.append(f"PR125_REQUIRED_LST_MISSING:{symbol}")
    return tuple(assets)


def _validate_token_contract(
    asset: Mapping[str, object],
    blockers: list[str],
) -> None:
    symbol = _string(asset, "symbol")
    token_program = _string(asset, "token_program")
    program_id = _string(asset, "token_program_id")
    if token_program == "legacy-spl-token":
        if program_id != LEGACY_SPL_TOKEN_PROGRAM_ID:
            blockers.append(f"PR125_TOKEN_PROGRAM_ID_MISMATCH:{symbol}")
    elif token_program == "token-2022":
        if program_id != TOKEN_2022_PROGRAM_ID:
            blockers.append(f"PR125_TOKEN_PROGRAM_ID_MISMATCH:{symbol}")
    else:
        blockers.append(f"PR125_TOKEN_PROGRAM_UNSUPPORTED:{symbol}:{token_program}")
    if not 0 <= _int(asset, "decimals") <= 18:
        blockers.append(f"PR125_DECIMALS_OUT_OF_RANGE:{symbol}")
    _sequence(asset, "extensions", default=())


def _asset_decisions(
    assets: Sequence[Mapping[str, object]],
    contract: Mapping[str, object],
    execution_blockers: list[str],
) -> tuple[LSTAssetDecision, ...]:
    decisions: list[LSTAssetDecision] = []
    for asset in assets:
        symbol = _string(asset, "symbol")
        reasons = _asset_reasons(asset, contract)
        if reasons:
            execution_blockers.append(f"PR125_LST_DISABLED:{symbol}")
        decisions.append(
            LSTAssetDecision(
                symbol=symbol,
                mint=_string(asset, "mint"),
                execution_allowed=not reasons,
                reasons=tuple(dict.fromkeys(reasons)),
            )
        )
    return tuple(decisions)


def _asset_reasons(
    asset: Mapping[str, object],
    contract: Mapping[str, object],
) -> list[str]:
    reasons: list[str] = []
    if _string(asset, "admission") != "disabled_until_reviewed_evidence":
        reasons.append("PR125_LST_ADMISSION_NOT_FAIL_CLOSED")
    if _int(asset, "max_asset_exposure_pct") != 0:
        reasons.append("PR125_ASSET_EXPOSURE_MUST_DEFAULT_ZERO")
    if _evidence_status(asset, "official_mint_provenance") != "reviewed":
        reasons.append("PR125_OFFICIAL_MINT_PROVENANCE_NOT_REVIEWED")
    if _evidence_status(asset, "oracle_model") != "reviewed":
        reasons.append("PR125_ORACLE_MODEL_NOT_REVIEWED")
    if _evidence_status(asset, "redemption_model") != "reviewed":
        reasons.append("PR125_REDEMPTION_MODEL_NOT_REVIEWED")
    if _evidence_status(asset, "deployment_attestation") != "reviewed":
        reasons.append("PR125_DEPLOYMENT_ATTESTATION_NOT_REVIEWED")
    if _bool(contract, "abnormal_redemption_state_blocks") is not True:
        reasons.append("PR125_ABNORMAL_REDEMPTION_STATE_NOT_BLOCKING")
    return reasons


def _pair_decisions(
    universe: Mapping[str, object],
    asset_decisions: Sequence[LSTAssetDecision],
    contract: Mapping[str, object],
    blockers: list[str],
) -> tuple[LSTPairDecision, ...]:
    by_mint = {decision.mint: decision for decision in asset_decisions}
    optional_enabled = _bool(contract, "optional_lst_pairs_enabled_by_default")
    results: list[LSTPairDecision] = []

    for item in _sequence(universe, "pairs"):
        pair = _mapping(item, "pairs[]")
        pair_id = _string(pair, "pair_id")
        decision = by_mint.get(_string(pair, "intermediate_mint"))
        if decision is None:
            continue
        required = _bool(pair, "required", default=False)
        reasons = list(decision.reasons)
        if required:
            blockers.append(f"PR125_REQUIRED_LST_PAIR_FORBIDDEN:{pair_id}")
            reasons.append("PR125_REQUIRED_LST_PAIR_FORBIDDEN")
        if not optional_enabled:
            reasons.append("PR125_OPTIONAL_LST_PAIR_DISABLED_BY_DEFAULT")
        results.append(
            LSTPairDecision(
                pair_id=pair_id,
                symbol=decision.symbol,
                required=required,
                execution_allowed=not reasons,
                reasons=tuple(dict.fromkeys(reasons)),
            )
        )
    return tuple(results)


def _execution_ready(
    policy_valid: bool,
    asset_decisions: Sequence[LSTAssetDecision],
    pair_decisions: Sequence[LSTPairDecision],
) -> bool:
    return (
        policy_valid
        and bool(asset_decisions)
        and all(decision.execution_allowed for decision in asset_decisions)
        and all(decision.execution_allowed for decision in pair_decisions)
    )


def _evidence_status(asset: Mapping[str, object], field: str) -> str:
    evidence = _mapping(asset.get(field), field)
    return _string(evidence, "status")


def _read_json(path: Path) -> Mapping[str, object]:
    try:
        return _mapping(json.loads(path.read_text(encoding="utf-8")), str(path))
    except FileNotFoundError as exc:
        raise PR125LSTGovernanceError(f"FILE_MISSING:{path}") from exc
    except json.JSONDecodeError as exc:
        raise PR125LSTGovernanceError(f"JSON_INVALID:{path}:{exc}") from exc


def _result(
    policy_path: str,
    universe_path: str,
    policy_valid: bool,
    asset_decisions: Sequence[LSTAssetDecision],
    pair_decisions: Sequence[LSTPairDecision],
    blockers: Sequence[str],
    execution_blockers: Sequence[str],
    warnings: Sequence[str],
) -> PR125LSTGovernanceResult:
    return PR125LSTGovernanceResult(
        schema_version=PR125_RESULT_SCHEMA_VERSION,
        policy_path=policy_path,
        universe_path=universe_path,
        policy_valid=policy_valid,
        lst_execution_ready=_execution_ready(
            policy_valid,
            asset_decisions,
            pair_decisions,
        ),
        asset_decisions=tuple(asset_decisions),
        pair_decisions=tuple(pair_decisions),
        blockers=tuple(dict.fromkeys(blockers)),
        execution_blockers=tuple(dict.fromkeys(execution_blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _safe_relative_path(value: str | Path, field: str) -> str:
    normalized = str(value).replace("\\", "/")
    if Path(value).is_absolute() or not normalized:
        raise PR125LSTGovernanceError(f"PATH_MUST_BE_REPO_RELATIVE:{field}")
    if normalized.startswith(("/", "~")):
        raise PR125LSTGovernanceError(f"PATH_MUST_BE_REPO_RELATIVE:{field}")
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise PR125LSTGovernanceError(f"PATH_UNSAFE:{field}")
    return normalized


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PR125LSTGovernanceError(f"FIELD_NOT_OBJECT:{field}")
    return value


def _sequence(
    payload: Mapping[str, object],
    field: str,
    *,
    default: Sequence[object] | None = None,
) -> Sequence[object]:
    value = payload.get(field, default)
    if not isinstance(value, (list, tuple)):
        raise PR125LSTGovernanceError(f"FIELD_NOT_LIST:{field}")
    return value


def _string(
    payload: Mapping[str, object],
    field: str,
    default: str | None = None,
) -> str:
    return _string_value(payload.get(field, default), field)


def _string_value(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise PR125LSTGovernanceError(f"FIELD_NOT_STRING:{field}")
    return value


def _bool(
    payload: Mapping[str, object],
    field: str,
    *,
    default: bool | None = None,
) -> bool:
    value = payload.get(field, default)
    if not isinstance(value, bool):
        raise PR125LSTGovernanceError(f"FIELD_NOT_BOOL:{field}")
    return value


def _int(payload: Mapping[str, object], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise PR125LSTGovernanceError(f"FIELD_NOT_INT:{field}")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the PR-125 LST governance safety gate."
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--policy-path", default=PR125_DEFAULT_POLICY_PATH)
    parser.add_argument("--universe-path", default=PR125_DEFAULT_UNIVERSE_PATH)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-lst-execution-ready", action="store_true")
    args = parser.parse_args(argv)

    result = evaluate_pr125_lst_governance_policy(
        repo_root=args.repo_root,
        policy_path=args.policy_path,
        universe_path=args.universe_path,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"PR-125 policy valid: {result.policy_valid}")
        print(f"PR-125 LST execution ready: {result.lst_execution_ready}")
    if not result.policy_valid:
        return 1
    if args.require_lst_execution_ready and not result.lst_execution_ready:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
