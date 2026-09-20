"""SUPER-05 closure over the existing Solana strategy-family authorities.

SUPER-05 aggregates W2-13, W2-14 and W2-15.  The implementation deliberately
does not create another orderbook, LST, liquidation, rate-market, signer, sender
or economic-ledger authority.  It proves that every primary NF in this SUPER
package resolves to an accepted repository owner and keeps operational
qualification separate from code closure.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import importlib
import json
from pathlib import Path
from typing import Mapping, Sequence

SCHEMA_VERSION = "super05.strategy-vertical-closure.v1"

EXPECTED_PRIMARY_NF = frozenset(
    {
        "NF-070",
        "NF-072",
        "NF-073",
        "NF-074",
        "NF-081",
        "NF-119",
        "NF-120",
        "NF-121",
        "NF-122",
        "NF-138",
        "NF-139",
        "NF-140",
        "NF-141",
        "NF-142",
        "NF-143",
        "NF-144",
        "NF-145",
        "NF-146",
        "NF-147",
        "NF-148",
        "NF-149",
        "NF-150",
        "NF-151",
        "NF-152",
        "NF-153",
        "NF-154",
    }
)

AGG06_SUPER05_NF = frozenset(
    {
        "NF-070",
        "NF-073",
        "NF-119",
        "NF-120",
        "NF-121",
        "NF-122",
        "NF-138",
        "NF-139",
        "NF-140",
        "NF-141",
        "NF-142",
        "NF-143",
        "NF-151",
        "NF-153",
    }
)
AGG07_SUPER05_NF = frozenset(
    {
        "NF-072",
        "NF-074",
        "NF-144",
        "NF-145",
        "NF-146",
        "NF-147",
        "NF-148",
        "NF-149",
        "NF-150",
    }
)
AGG10_SUPER05_NF = frozenset({"NF-081", "NF-152", "NF-154"})


@dataclass(frozen=True, slots=True)
class ChildContract:
    child_pr: str
    w2_id: str
    primary_nf: tuple[str, ...]
    owner_module: str
    owner_symbols: tuple[str, ...]
    implementation_status: str = "SATISFIED_BY_EXISTING"
    activation_status: str = "DEFAULT_OFF"


CHILD_CONTRACTS: tuple[ChildContract, ...] = (
    ChildContract(
        "PR-108",
        "W2-13",
        ("NF-070", "NF-120"),
        "src.agg06_solana_venues",
        ("validate_clob_window", "quote_clob"),
    ),
    ChildContract(
        "PR-109",
        "W2-13",
        (),
        "src.providers.orderbook.adapters",
        ("OpenBookV2VenueAdapter",),
        implementation_status="SATISFIED_BY_EXISTING_RELATED_ONLY",
    ),
    ChildContract(
        "PR-110",
        "W2-13",
        ("NF-138",),
        "src.agg06_solana_venues",
        ("qualify_clob_amm",),
    ),
    ChildContract(
        "PR-111",
        "W2-14",
        ("NF-073", "NF-121", "NF-122", "NF-139", "NF-151"),
        "src.agg06_solana_venues",
        (
            "qualify_redemption",
            "qualify_lst_conversion",
            "qualify_basket",
            "qualify_lst_nav",
            "qualify_lp_parity",
        ),
    ),
    ChildContract(
        "PR-112",
        "W2-14",
        ("NF-140", "NF-141", "NF-153"),
        "src.agg06_solana_venues",
        ("quote_dynamic_fee", "qualify_time_fee", "apply_token2022_fee"),
    ),
    ChildContract(
        "PR-113",
        "W2-14",
        ("NF-119", "NF-142", "NF-143"),
        "src.agg06_solana_venues",
        ("qualify_lifecycle", "qualify_post_swap", "qualify_migration"),
    ),
    ChildContract(
        "PR-118",
        "W2-14",
        ("NF-081", "NF-152", "NF-154"),
        "src.decision.agg10",
        ("OrderflowObservation", "CoverageGapHypothesis", "OracleDivergenceSignal"),
    ),
    ChildContract(
        "PR-114",
        "W2-15",
        ("NF-072", "NF-144"),
        "src.liquidation.agg07",
        ("build_liquidation_watchlist", "LiquidationTriggerEvidence"),
    ),
    ChildContract(
        "PR-115",
        "W2-15",
        ("NF-145", "NF-146"),
        "src.liquidation.agg07",
        (
            "build_flash_funded_liquidation_candidate",
            "select_non_conflicting_liquidations",
        ),
    ),
    ChildContract(
        "PR-116",
        "W2-15",
        ("NF-147", "NF-148"),
        "src.lending.agg07",
        ("ProtocolResearchEvidence", "evaluate_capacity_release"),
    ),
    ChildContract(
        "PR-117",
        "W2-15",
        ("NF-074", "NF-149", "NF-150"),
        "src.lending.agg07",
        ("RateMarketFrame", "evaluate_strip_merge", "compare_rate_venues"),
    ),
)

ARTIFACT_PATHS = {
    "AGG-06": Path("release_artifacts/agg/AGG-06/coverage.json"),
    "AGG-07": Path("release_artifacts/agg/agg-07/summary.json"),
    "AGG-10": Path("release_artifacts/agg/AGG-10/coverage.json"),
}

ARTIFACT_REQUIRED_NF = {
    "AGG-06": AGG06_SUPER05_NF,
    "AGG-07": AGG07_SUPER05_NF,
    "AGG-10": AGG10_SUPER05_NF,
}


@dataclass(frozen=True, slots=True)
class Super05Report:
    schema_version: str
    child_count: int
    primary_nf_count: int
    implementation_complete: bool
    qualification_complete: bool
    implementation_status: str
    operational_status: str
    live_enabled: bool
    release_claim_allowed: bool
    blockers: tuple[str, ...]
    errors: tuple[str, ...]
    children: tuple[ChildContract, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_artifacts(root: Path) -> dict[str, Mapping[str, object]]:
    payloads: dict[str, Mapping[str, object]] = {}
    for agg_id, relative in ARTIFACT_PATHS.items():
        path = root / relative
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{agg_id} coverage artifact must be a JSON object")
        payloads[agg_id] = payload
    return payloads


def _validate_child_ownership(errors: list[str]) -> None:
    child_ids = [item.child_pr for item in CHILD_CONTRACTS]
    if len(child_ids) != len(set(child_ids)):
        errors.append("SUPER05_DUPLICATE_CHILD_OWNER")
    if len(CHILD_CONTRACTS) != 11:
        errors.append(f"SUPER05_CHILD_COUNT:{len(CHILD_CONTRACTS)}")

    owned = [nf for item in CHILD_CONTRACTS for nf in item.primary_nf]
    duplicates = sorted(nf for nf, count in Counter(owned).items() if count != 1)
    if duplicates:
        errors.append("SUPER05_DUPLICATE_NF_OWNER:" + ",".join(duplicates))
    missing = sorted(EXPECTED_PRIMARY_NF - set(owned))
    extra = sorted(set(owned) - EXPECTED_PRIMARY_NF)
    if missing:
        errors.append("SUPER05_NF_MISSING:" + ",".join(missing))
    if extra:
        errors.append("SUPER05_NF_EXTRA:" + ",".join(extra))

    related_only = [item for item in CHILD_CONTRACTS if not item.primary_nf]
    if len(related_only) != 1 or related_only[0].child_pr != "PR-109":
        errors.append("SUPER05_RELATED_ONLY_CHILD_INVALID")


def _validate_symbols(errors: list[str]) -> None:
    for item in CHILD_CONTRACTS:
        try:
            module = importlib.import_module(item.owner_module)
        except Exception as exc:
            errors.append(
                f"SUPER05_OWNER_IMPORT_FAILED:{item.child_pr}:{type(exc).__name__}"
            )
            continue
        for symbol in item.owner_symbols:
            if not hasattr(module, symbol):
                errors.append(
                    f"SUPER05_OWNER_SYMBOL_MISSING:{item.child_pr}:"
                    f"{item.owner_module}:{symbol}"
                )


def _validate_artifacts(
    payloads: Mapping[str, Mapping[str, object]],
    errors: list[str],
    blockers: list[str],
) -> None:
    for agg_id, required in ARTIFACT_REQUIRED_NF.items():
        payload = payloads.get(agg_id)
        if payload is None:
            errors.append(f"SUPER05_ARTIFACT_MISSING:{agg_id}")
            continue
        primary = payload.get("primary_nf")
        if not isinstance(primary, list) or not all(isinstance(item, str) for item in primary):
            errors.append(f"SUPER05_ARTIFACT_PRIMARY_NF_INVALID:{agg_id}")
            continue
        absent = sorted(required - set(primary))
        if absent:
            errors.append(
                f"SUPER05_ARTIFACT_NF_MISSING:{agg_id}:" + ",".join(absent)
            )
        if payload.get("live_enabled") is not False:
            errors.append(f"SUPER05_ARTIFACT_LIVE_NOT_FALSE:{agg_id}")
        implementation = payload.get("implementation_status")
        if implementation != "IMPLEMENTED_OFFLINE":
            errors.append(
                f"SUPER05_IMPLEMENTATION_STATUS_UNEXPECTED:{agg_id}:{implementation}"
            )

    agg06 = payloads.get("AGG-06", {})
    agg07 = payloads.get("AGG-07", {})

    if agg06.get("operational_status") != "QUALIFIED":
        blockers.append("SUPER05_AGG06_OPERATIONAL_EVIDENCE_UNQUALIFIED")
    for item in agg06.get("mandatory_external_evidence", ()):
        if isinstance(item, str):
            blockers.append("SUPER05_AGG06_EXTERNAL:" + item)

    if agg07.get("operational_status") != "QUALIFIED":
        blockers.append("SUPER05_AGG07_OPERATIONAL_EVIDENCE_UNQUALIFIED")
    for item in agg07.get("external_blockers", ()):
        if isinstance(item, str):
            blockers.append("SUPER05_AGG07_EXTERNAL:" + item)


def _validate_orderbook_runtime(errors: list[str], blockers: list[str]) -> None:
    try:
        package = importlib.import_module("src.providers.orderbook")
    except Exception as exc:
        errors.append(f"SUPER05_ORDERBOOK_IMPORT_FAILED:{type(exc).__name__}")
        return
    if getattr(package, "__quarantined__", None) is not True:
        errors.append("SUPER05_ORDERBOOK_QUARANTINE_EXPECTATION_CHANGED")
    capability = getattr(package, "__runtime_capability__", None)
    if capability == "fixture-only":
        blockers.append("SUPER05_ORDERBOOK_RUNTIME_FIXTURE_ONLY")
    elif capability not in {"shadow-only", "offline-verified"}:
        errors.append(f"SUPER05_ORDERBOOK_CAPABILITY_UNKNOWN:{capability}")


def evaluate_super05(
    *,
    root: Path | None = None,
    artifacts: Mapping[str, Mapping[str, object]] | None = None,
) -> Super05Report:
    """Verify SUPER-05 implementation closure without promoting live authority."""

    errors: list[str] = []
    blockers: list[str] = []
    _validate_child_ownership(errors)
    _validate_symbols(errors)

    payloads = (
        dict(artifacts)
        if artifacts is not None
        else _load_artifacts(root or _repo_root())
    )
    _validate_artifacts(payloads, errors, blockers)
    _validate_orderbook_runtime(errors, blockers)

    unique_blockers = tuple(dict.fromkeys(blockers))
    unique_errors = tuple(dict.fromkeys(errors))
    implementation_complete = not unique_errors
    qualification_complete = implementation_complete and not unique_blockers
    return Super05Report(
        schema_version=SCHEMA_VERSION,
        child_count=len(CHILD_CONTRACTS),
        primary_nf_count=len(EXPECTED_PRIMARY_NF),
        implementation_complete=implementation_complete,
        qualification_complete=qualification_complete,
        implementation_status=(
            "VERIFIED_OFFLINE" if implementation_complete else "BLOCKED_IMPLEMENTATION"
        ),
        operational_status=("QUALIFIED" if qualification_complete else "UNQUALIFIED"),
        live_enabled=False,
        release_claim_allowed=False,
        blockers=unique_blockers,
        errors=unique_errors,
        children=CHILD_CONTRACTS,
    )


__all__ = [
    "AGG06_SUPER05_NF",
    "AGG07_SUPER05_NF",
    "AGG10_SUPER05_NF",
    "ARTIFACT_PATHS",
    "CHILD_CONTRACTS",
    "EXPECTED_PRIMARY_NF",
    "SCHEMA_VERSION",
    "ChildContract",
    "Super05Report",
    "evaluate_super05",
]
