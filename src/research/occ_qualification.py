"""Registered finite offline research campaigns for SCE, owned by Studious.

Reuses MDE point-in-time selection, PR148 cost arithmetic, installed lending
repayment and intent clearing. Positive modeled edge grants no execution right.
"""

from __future__ import annotations

from dataclasses import asdict
from contextlib import closing
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any, Callable

from src.lending.financing import FinancingEvidence
from src.lending.shadow_capacity import ShadowFundingCapacity, debt_is_closed
from src.market_data_evolution.qualification_dataset import (
    ResearchDatasetView,
    canonical,
    digest,
    file_digest,
    unique_json,
)
from src.market_economics_pr148 import ExactCostLedger
from src.mechanism_discovery.intent_graph import ClearingIntent, clear_intents

REQUEST_SCHEMA = "studious.occ-research-request.v1"
RECEIPT_SCHEMA = "studious.occ-research-receipt.v1"
PACKS = (
    "circular_triangular",
    "liquidation_swap",
    "peg_wrapper",
    "intent_clearing",
    "capital_timeline",
)
_CONFIG = {
    "schema",
    "experiment_id",
    "mode",
    "pack",
    "cutoff",
    "max_age",
    "anchor",
    "seed",
    "criteria_sha256",
    "holdout_sha256",
    "stop_after_records",
}


def integer(value: object, *, minimum=0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError("INTEGER_ATOMIC_UNITS_REQUIRED")
    return value


def fields(value: object, required: set[str], optional=frozenset()) -> dict:
    if (
        not isinstance(value, dict)
        or not required.issubset(value)
        or set(value) - required - optional
    ):
        raise ValueError("RESEARCH_SCHEMA_FIELDS")
    return value


def cost_ledger(payload: dict) -> tuple[ExactCostLedger, list[str]]:
    required = {
        "asset",
        "decimals",
        "principal_atoms",
        "repayment_atoms",
        "output_atoms",
        "costs",
    }
    fields(payload, required)
    if not isinstance(payload["asset"], str) or not payload["asset"]:
        raise ValueError("ECONOMIC_ASSET_REQUIRED")
    integer(payload["decimals"])
    if payload["decimals"] > 38:
        raise ValueError("DECIMALS_INVALID")
    principal = integer(payload["principal_atoms"])
    repayment = integer(payload["repayment_atoms"])
    output = integer(payload["output_atoms"])
    if repayment < principal:
        raise ValueError("REPAYMENT_BELOW_PRINCIPAL")
    costs = payload["costs"]
    if not isinstance(costs, list):
        raise ValueError("EXPLICIT_COST_LEDGER_REQUIRED")
    names, unknown, deducted = set(), [], 0
    for row in costs:
        fields(row, {"name", "asset", "decimals", "atoms", "included_in_quote"})
        if not isinstance(row["name"], str) or not row["name"] or row["name"] in names:
            raise ValueError("DUPLICATE_OR_MISSING_COST_IDENTITY")
        names.add(row["name"])
        integer(row["decimals"])
        if (row["asset"], row["decimals"]) != (payload["asset"], payload["decimals"]):
            raise ValueError("POINT_IN_TIME_COST_CONVERSION_REQUIRED")
        if type(row["included_in_quote"]) is not bool:
            raise ValueError("COST_INCLUSION_BOOLEAN_REQUIRED")
        if row["atoms"] is None:
            unknown.append(row["name"])
        elif row["name"] == "borrow":
            # Borrow fee is already in required repayment, never subtract twice.
            if (
                integer(row["atoms"]) != repayment - principal
                or not row["included_in_quote"]
            ):
                raise ValueError("BORROW_FEE_MUST_MATCH_REPAYMENT_AND_BE_INCLUDED")
        elif not row["included_in_quote"]:
            deducted += integer(row["atoms"])
        else:
            integer(row["atoms"])
    # Mandatory route costs are explicit even when zero, never defaulted away.
    unknown += sorted(
        {
            "borrow",
            "dex",
            "network",
            "priority",
            "tip",
            "failure",
            "slippage",
            "latency",
        }
        - names
    )
    return ExactCostLedger(
        principal_atoms=principal,
        flash_fee_atoms=repayment - principal,
        required_repayment_atoms=repayment,
        gross_output_atoms=output,
        uncertainty_atoms=deducted,
    ), sorted(set(unknown))


def verify_atomic_route(payload: dict, *, cutoff: int) -> dict[str, Any]:
    fields(
        payload,
        {
            "economics",
            "funding",
            "legs",
            "settlement_delay_ns",
            "instructions_supported",
        },
    )
    ledger, unknown = cost_ledger(payload["economics"])
    if type(payload["instructions_supported"]) is not bool:
        raise ValueError("INSTRUCTION_SUPPORT_BOOLEAN_REQUIRED")
    funding = payload["funding"]
    fields(
        funding,
        {
            "evidence",
            "domain",
            "asset_identity",
            "available_atoms",
            "fee_numerator",
            "fee_denominator",
            "protocol_rounding_atoms",
            "available_at_ns",
            "expiry_ns",
            "entitlement_verified",
            "atomic_repayment_verified",
        },
    )
    for key in ("domain", "asset_identity"):
        if not isinstance(funding[key], str) or not funding[key]:
            raise ValueError("FUNDING_IDENTITY_REQUIRED")
    capacity = ShadowFundingCapacity(
        **{key: value for key, value in funding.items() if key != "evidence"},
        evidence=FinancingEvidence(**funding["evidence"]),
    )
    asset = payload["economics"]["asset"]
    repayment = capacity.repayment(
        ledger.principal_atoms,
        now_ns=cutoff,
        domain=capacity.domain,
        asset_identity=asset,
    )
    if repayment != ledger.required_repayment_atoms:
        raise ValueError("LENDER_REPAYMENT_TERMS_MISMATCH")
    legs = payload["legs"]
    if not isinstance(legs, list) or not legs:
        raise ValueError("ROUTE_LEGS_REQUIRED")
    previous_asset, previous_amount = asset, ledger.principal_atoms
    for leg in legs:
        fields(
            leg,
            {
                "input_asset",
                "output_asset",
                "input_atoms",
                "output_atoms",
                "available_at_ns",
                "expires_at_ns",
                "domain",
            },
        )
        for key in ("input_asset", "output_asset", "domain"):
            if not isinstance(leg[key], str) or not leg[key]:
                raise ValueError("ROUTE_ASSET_DOMAIN_IDENTITY_REQUIRED")
        for key in ("input_atoms", "output_atoms", "available_at_ns", "expires_at_ns"):
            integer(leg[key])
        if leg["domain"] != capacity.domain:
            raise ValueError("CROSS_DOMAIN_ROUTE_NON_ATOMIC")
        if (leg["input_asset"], leg["input_atoms"]) != (
            previous_asset,
            previous_amount,
        ):
            raise ValueError("ROUTE_AMOUNT_OR_ASSET_DISCONTINUITY")
        if not leg["available_at_ns"] <= cutoff < leg["expires_at_ns"]:
            raise ValueError("ROUTE_QUOTE_NOT_AVAILABLE_OR_EXPIRED")
        previous_asset, previous_amount = leg["output_asset"], leg["output_atoms"]
    if (previous_asset, previous_amount) != (asset, ledger.gross_output_atoms):
        raise ValueError("SETTLEMENT_ASSET_OR_AMOUNT_MISMATCH")
    atomic = integer(payload["settlement_delay_ns"]) == 0
    closed = debt_is_closed(
        outputs_by_asset={asset: previous_amount},
        repayments_by_asset={asset: repayment},
        native_wallet_atoms=0,
        native_cost_atoms=0,
    )
    blockers = unknown + ([] if atomic else ["DELAYED_SETTLEMENT_NON_ATOMIC"])
    if not payload["instructions_supported"]:
        blockers.append("UNSUPPORTED_INSTRUCTIONS")
    if not closed:
        blockers.append("REPAYMENT_SHORTFALL")
    return {
        "model": "ATOMIC",
        "status": (
            "BLOCKED"
            if blockers
            else (
                "MODELED_CANDIDATE"
                if ledger.conservative_profit_atoms > 0
                else "NO_CANDIDATE"
            )
        ),
        "net_atoms": None if unknown else ledger.conservative_profit_atoms,
        "repayment_atoms": repayment,
        "blockers": sorted(set(blockers)),
        "execution_right": False,
    }


def verify_clearing(
    intents: tuple[ClearingIntent, ...], result, *, cutoff: int
) -> bool:
    by_id = {item.intent_id: item for item in intents}
    if len(by_id) != len(intents):
        return False
    sold = {key: 0 for key in by_id}
    for fill in result.fills:
        left, right = by_id.get(fill.left_intent_id), by_id.get(fill.right_intent_id)
        if left is None or right is None or left == right:
            return False
        if (left.sell_asset, left.buy_asset, left.domain, left.access_id) != (
            right.buy_asset,
            right.sell_asset,
            right.domain,
            right.access_id,
        ):
            return False
        for order in (left, right):
            if (
                not order.available_at_ns <= cutoff < order.expires_at_ns
                or order.canceled_at_ns is not None
                and cutoff >= order.canceled_at_ns
            ):
                return False
        lq, rq = fill.left_sell_atoms, fill.right_sell_atoms
        if type(lq) is not int or type(rq) is not int or lq <= 0 or rq <= 0:
            return False
        if (
            rq * left.max_sell_atoms < left.minimum_buy_atoms * lq
            or lq * right.max_sell_atoms < right.minimum_buy_atoms * rq
        ):
            return False
        sold[left.intent_id] += lq
        sold[right.intent_id] += rq
    if any(sold[key] > item.max_sell_atoms for key, item in by_id.items()):
        return False
    return dict(result.remaining_sell_atoms) == {
        key: item.max_sell_atoms - sold[key] for key, item in by_id.items()
    }


def evaluate_pack(pack: str, payload: dict, *, cutoff: int) -> dict[str, Any]:
    if pack not in PACKS:
        raise ValueError("RESEARCH_PACK_UNSUPPORTED")
    if pack == "intent_clearing":
        fields(payload, {"intents", "lot_sizes"})
        intents = tuple(ClearingIntent(**row) for row in payload["intents"])
        result = clear_intents(
            intents,
            now_ns=cutoff,
            lot_sizes=tuple(tuple(x) for x in payload["lot_sizes"]),
        )
        if not verify_clearing(intents, result, cutoff=cutoff):
            raise ValueError("CLEARING_CONSTRAINT_VERIFICATION_FAILED")
        return {
            "model": "OFFLINE_CLEARING",
            "status": "MODELED_MATCH" if result.fills else "NO_FEASIBLE_CLEARING",
            "result": asdict(result),
            "execution_right": False,
        }
    if pack == "capital_timeline":
        fields(payload, {"strategy", "capital_atoms", "stages", "economics"})
        if payload["strategy"] not in {"cross_chain", "basis", "funding"}:
            raise ValueError("CAPITAL_STRATEGY_UNSUPPORTED")
        capital = integer(payload["capital_atoms"], minimum=1)
        stages = payload["stages"]
        if not isinstance(stages, list) or not stages:
            raise ValueError("CAPITAL_STAGES_REQUIRED")
        previous = cutoff
        blockers = []
        for stage in stages:
            fields(
                stage,
                {
                    "available_at_ns",
                    "start_ns",
                    "end_ns",
                    "locked_atoms",
                    "cashflow_atoms",
                    "settled",
                    "hedge_assumption",
                },
            )
            start, end, available = (
                integer(stage[k]) for k in ("start_ns", "end_ns", "available_at_ns")
            )
            integer(stage["locked_atoms"])
            integer(stage["cashflow_atoms"])
            if (
                not previous <= start <= end
                or available > cutoff
                or stage["locked_atoms"] > capital
            ):
                blockers.append("CAPITAL_TIME_OR_AVAILABILITY_INVALID")
            if (
                type(stage["settled"]) is not bool
                or not isinstance(stage["hedge_assumption"], str)
                or not stage["hedge_assumption"]
            ):
                raise ValueError("SETTLEMENT_HEDGE_ASSUMPTION_REQUIRED")
            if not stage["settled"]:
                blockers.append("SETTLEMENT_FAILURE_SCENARIO")
            previous = end
        ledger, unknown = cost_ledger(payload["economics"])
        if ledger.principal_atoms != capital:
            raise ValueError("CAPITAL_ECONOMIC_IDENTITY_MISMATCH")
        if ledger.gross_output_atoms != capital + sum(
            stage["cashflow_atoms"] for stage in stages
        ):
            raise ValueError("CAPITAL_CASHFLOW_ACCOUNTING_MISMATCH")
        blockers += unknown
        return {
            "model": "DELAYED_CAPITAL",
            "status": (
                "BLOCKED"
                if blockers
                else (
                    "MODELED_CANDIDATE"
                    if ledger.conservative_profit_atoms > 0
                    else "NO_CANDIDATE"
                )
            ),
            "net_atoms": None if unknown else ledger.conservative_profit_atoms,
            "exposure_duration_ns": previous - cutoff,
            "available_flashloan_repayment_from_future_cashflow": 0,
            "blockers": sorted(set(blockers)),
            "execution_right": False,
        }
    if pack == "liquidation_swap":
        fields(
            payload,
            {
                "route",
                "eligible_at_ns",
                "oracle_available_at_ns",
                "collateral_available_at_ns",
                "actor_eligible",
            },
        )
        for key in (
            "eligible_at_ns",
            "oracle_available_at_ns",
            "collateral_available_at_ns",
        ):
            integer(payload[key])
        if (
            payload["actor_eligible"] is not True
            or max(
                payload[k]
                for k in (
                    "eligible_at_ns",
                    "oracle_available_at_ns",
                    "collateral_available_at_ns",
                )
            )
            > cutoff
        ):
            return {
                "model": "ATOMIC",
                "status": "BLOCKED",
                "blockers": ["LIQUIDATION_STATE_NOT_ELIGIBLE_AT_DECISION"],
                "execution_right": False,
            }
        return verify_atomic_route(payload["route"], cutoff=cutoff)
    if pack == "peg_wrapper":
        fields(
            payload,
            {"route", "redemption_right", "redemption_delay_ns", "liquidity_atoms"},
        )
        if (
            payload["redemption_right"] is not True
            or integer(payload["liquidity_atoms"])
            < payload["route"]["economics"]["principal_atoms"]
        ):
            return {
                "model": "CONVERSION",
                "status": "BLOCKED",
                "blockers": ["REDEMPTION_RIGHT_OR_LIQUIDITY_MISSING"],
                "execution_right": False,
            }
        if integer(payload["redemption_delay_ns"]) > 0:
            return {
                "model": "DELAYED_CAPITAL",
                "status": "BLOCKED",
                "blockers": ["DELAYED_REDEMPTION_REQUIRES_CAPITAL_MODEL"],
                "execution_right": False,
            }
        return verify_atomic_route(payload["route"], cutoff=cutoff)
    return verify_atomic_route(payload, cutoff=cutoff)


def validate_config(value: object) -> dict:
    config = fields(value, _CONFIG)
    if (
        config["schema"] != "studious.occ-research-config.v1"
        or config["mode"] != "REPLAY"
        or config["pack"] not in PACKS
    ):
        raise ValueError("UNQUALIFIED_MODE_OR_PACK")
    for key in ("cutoff", "max_age", "seed"):
        integer(config[key])
    if config["stop_after_records"] is not None:
        integer(config["stop_after_records"], minimum=1)
    for key in ("criteria_sha256", "holdout_sha256"):
        if not isinstance(config[key], str) or not re.fullmatch(
            r"[0-9a-f]{64}", config[key]
        ):
            raise ValueError("FROZEN_CRITERIA_SPLIT_DIGEST_REQUIRED")
    for key in ("experiment_id", "anchor"):
        if not isinstance(config[key], str) or not config[key]:
            raise ValueError("EXPERIMENT_IDENTITY_REQUIRED")
    return config


def run_campaign(
    dataset: Path,
    config: dict,
    *,
    expected_dataset_digest: str,
    trials_path: Path,
    progress: Callable[[], None] = lambda: None,
) -> dict[str, Any]:
    config = validate_config(config)
    view = ResearchDatasetView(dataset, expected_dataset_digest)
    counts = {}
    families = set()
    calls = 0
    records = 0
    pending = False
    decisions = hashlib.sha256()
    with (
        tempfile.TemporaryDirectory(prefix="occ-trial-dedup-") as directory,
        trials_path.open("xb") as output,
        closing(sqlite3.connect(str(Path(directory) / "seen.sqlite3"))) as seen,
    ):
        seen.execute("CREATE TABLE opportunities(id TEXT PRIMARY KEY)")
        for row, reason, proof in view.decisions(
            cutoff=config["cutoff"], max_age=config["max_age"], anchor=config["anchor"]
        ):
            progress()
            if (
                config["stop_after_records"] is not None
                and records >= config["stop_after_records"]
            ):
                pending = True
                break
            records += 1
            families.update(row.upstream_families)
            if (
                not reason
                and seen.execute(
                    "SELECT 1 FROM opportunities WHERE id=?", (row.opportunity_id,)
                ).fetchone()
            ):
                reason = "DUPLICATE_OPPORTUNITY"
            if reason:
                result = {
                    "status": "BLOCKED",
                    "blockers": [reason],
                    "execution_right": False,
                }
            else:
                seen.execute(
                    "INSERT INTO opportunities VALUES (?)", (row.opportunity_id,)
                )
                calls += 1
                try:
                    result = evaluate_pack(
                        config["pack"], row.payload, cutoff=config["cutoff"]
                    )
                except (ValueError, TypeError, KeyError) as exc:
                    result = {
                        "status": "FAILED",
                        "reason": type(exc).__name__ + ":" + str(exc),
                        "execution_right": False,
                    }
            trial = {
                "ordinal": records,
                "opportunity_id": row.opportunity_id,
                "observation_id": row.observation.observation_id,
                "origin": "OFFLINE_FIXTURE",
                "handler_invoked": not bool(reason),
                "availability_proof": proof,
                "upstream_families": row.upstream_families,
                "result": result,
            }
            raw = canonical(trial) + b"\n"
            output.write(raw)
            decisions.update(raw)
            counts[result["status"]] = counts.get(result["status"], 0) + 1
        output.flush()
        os.fsync(output.fileno())
    view.verify()
    return {
        "schema": "studious.occ-research-campaign.v1",
        "mode": "REPLAY",
        "origin": "OFFLINE_FIXTURE",
        "campaign_executed": calls - counts.get("FAILED", 0) > 0,
        "status": (
            "PARTIAL"
            if pending
            else (
                "INVALID_CAMPAIGN"
                if calls - counts.get("FAILED", 0) == 0
                else "MODEL_REPLAY_COMPLETED"
            )
        ),
        "records": records,
        "handler_calls": calls,
        "useful_calls": calls - counts.get("FAILED", 0),
        "outcome_counts": counts,
        "declared_upstream_families": sorted(families),
        "decision_sha256": decisions.hexdigest(),
        "dataset_sha256": expected_dataset_digest,
        "config_sha256": digest(config),
        "pending": pending,
        "execution_right": False,
        "live_enabled": False,
        "transactions_sent": 0,
        "verified_property": "frozen-offline-model-replay",
        "limitations": [
            "No real market acquisition or protocol execution verified",
            "No installed Windows qualification",
            "Holdout digest is a binding only; no holdout benchmark evaluated",
        ],
    }


def handler_catalog() -> dict:
    return {
        "schema": "studious.occ-research-handlers.v1",
        "handlers": [
            {
                "id": "model_replay",
                "script": "scripts/run_research_qualification.py",
                "callable_owner": "src.research.occ_qualification.run_campaign",
                "modes": ["REPLAY"],
                "packs": list(PACKS),
                "effects": ["local_research_artifacts"],
                "qualified_scope": "OFFLINE_MODEL_ONLY",
            },
            {
                "id": "qualification_inspect",
                "script": "scripts/run_occ_memory_qualification.py",
                "callable_owner": "src.qualification_report.qualify_and_report",
                "modes": ["READ_ONLY"],
                "effects": ["local_inspection_artifacts"],
                "qualified_scope": "EXISTING_INSPECTION_CONTRACT",
            },
        ],
        "gaps": [
            "PAPER_REAL_ACQUISITION_ADAPTER_NOT_QUALIFIED",
            "DELL_INSTALLED_RECEIPT_NOT_CAPTURED",
        ],
        "live_enabled": False,
    }
