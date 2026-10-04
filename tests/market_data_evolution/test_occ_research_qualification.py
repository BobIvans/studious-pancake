"""Executable model qualification: no RPC, signing or market performance claims."""

from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import pytest
from hypothesis import given, strategies as st

from src.market_data_evolution.qualification_dataset import (
    ResearchDatasetView,
    canonical,
    digest,
    file_digest,
    iter_observations,
    compare_provider_views,
)
from src.research.occ_qualification import (
    cost_ledger,
    evaluate_pack,
    run_campaign,
    verify_atomic_route,
    verify_clearing,
)
from src.mechanism_discovery.intent_graph import ClearingIntent, clear_intents
from scripts.run_research_qualification import execute_request


def economics():
    return {
        "asset": "A",
        "decimals": 6,
        "principal_atoms": 1000,
        "repayment_atoms": 1001,
        "output_atoms": 1100,
        "costs": [
            {
                "name": name,
                "asset": "A",
                "decimals": 6,
                "atoms": 1 if name == "borrow" else 0,
                "included_in_quote": name == "borrow",
            }
            for name in (
                "borrow",
                "dex",
                "network",
                "priority",
                "tip",
                "failure",
                "slippage",
                "latency",
            )
        ],
    }


def route():
    return {
        "economics": economics(),
        "funding": {
            "evidence": {
                "lender_id": "fixture",
                "program_id": "fixture-program",
                "deployment_generation": 1,
                "evidence_sha256": "a" * 64,
                "decoder_identity": "fixture",
                "decoder_generation": 1,
            },
            "domain": "offline",
            "asset_identity": "A",
            "available_atoms": 1000,
            "fee_numerator": 1,
            "fee_denominator": 1000,
            "protocol_rounding_atoms": 0,
            "available_at_ns": 0,
            "expiry_ns": 100,
            "entitlement_verified": True,
            "atomic_repayment_verified": True,
        },
        "legs": [
            {
                "input_asset": "A",
                "output_asset": "B",
                "input_atoms": 1000,
                "output_atoms": 1050,
                "available_at_ns": 0,
                "expires_at_ns": 100,
                "domain": "offline",
            },
            {
                "input_asset": "B",
                "output_asset": "A",
                "input_atoms": 1050,
                "output_atoms": 1100,
                "available_at_ns": 0,
                "expires_at_ns": 100,
                "domain": "offline",
            },
        ],
        "settlement_delay_ns": 0,
        "instructions_supported": True,
    }


def config(pack="circular_triangular", stop=None):
    return {
        "schema": "studious.occ-research-config.v1",
        "experiment_id": "fixture",
        "mode": "REPLAY",
        "pack": pack,
        "cutoff": 10,
        "max_age": 10,
        "anchor": "slot:1",
        "seed": 7,
        "criteria_sha256": "a" * 64,
        "holdout_sha256": "b" * 64,
        "stop_after_records": stop,
    }


def record(payload, index=0, available=1, revision=0, missing=False):
    return {
        "schema": "occ.research-observation.v1",
        "origin": "OFFLINE_FIXTURE",
        "payload": payload,
        "anchor": "slot:1",
        "upstream_families": ["fixture-source"],
        "observation": {
            "observation_id": f"obs-{index}",
            "source_id": "fixture",
            "instrument_id": f"route-{index}",
            "value_atoms": 1,
            "event_at": 0,
            "first_seen_at": 1,
            "available_at": available,
            "revision_id": revision,
            "effective_from": 0,
            "effective_until": None,
            "instrument_version": "v1",
            "raw_payload_hash": digest(payload),
            "published_at": None,
            "missing": missing,
        },
    }


def dataset(tmp_path, rows):
    path = tmp_path / "data.jsonl"
    path.write_bytes(b"".join(canonical(row) + b"\n" for row in rows))
    return path


def test_exact_repayment_all_costs_and_unknown():
    assert verify_atomic_route(route(), cutoff=10)["net_atoms"] == 99
    p = route()
    p["economics"]["costs"][2]["atoms"] = 100
    assert verify_atomic_route(p, cutoff=10)["status"] == "NO_CANDIDATE"
    p["economics"]["costs"][2]["atoms"] = None
    assert verify_atomic_route(p, cutoff=10)["net_atoms"] is None
    p["economics"]["costs"][2]["asset"] = "SOL"
    with pytest.raises(ValueError, match="CONVERSION"):
        verify_atomic_route(p, cutoff=10)
    p = route()
    p["economics"]["costs"][0]["included_in_quote"] = False
    with pytest.raises(ValueError, match="BORROW_FEE"):
        verify_atomic_route(p, cutoff=10)


@pytest.mark.parametrize(
    "mutation",
    [
        "fee",
        "expired",
        "capacity",
        "actor",
        "cross-domain",
        "amount",
        "delay",
        "unsupported",
        "debt",
    ],
)
def test_atomic_negative_corpus(mutation):
    p = route()
    if mutation == "fee":
        p["economics"]["repayment_atoms"] = 1002
    if mutation == "expired":
        p["funding"]["expiry_ns"] = 10
    if mutation == "capacity":
        p["funding"]["available_atoms"] = 999
    if mutation == "actor":
        p["funding"]["entitlement_verified"] = False
    if mutation == "cross-domain":
        p["legs"][1]["domain"] = "other-chain"
    if mutation == "amount":
        p["legs"][1]["input_atoms"] = 1000
    if mutation == "delay":
        p["settlement_delay_ns"] = 1
    if mutation == "unsupported":
        p["instructions_supported"] = False
    if mutation == "debt":
        p["legs"][1]["output_atoms"] = 999
        p["economics"]["output_atoms"] = 999
    try:
        result = verify_atomic_route(p, cutoff=10)
    except ValueError:
        return
    assert result["status"] == "BLOCKED" and result["execution_right"] is False


def test_point_in_time_latest_not_future_missing_and_tail(tmp_path):
    rows = [record(route(), i) for i in range(45)]
    rows += [
        record(route(), 0, revision=1),
        record(route(), 0, available=11, revision=2),
        record(route(), 46, missing=True),
    ]
    data = dataset(tmp_path, rows)
    report = run_campaign(
        data,
        config(),
        expected_dataset_digest=file_digest(data),
        trials_path=tmp_path / "trials",
    )
    assert report["records"] == 48 and report["useful_calls"] == 45
    outcomes = [
        json.loads(line)["result"]
        for line in (tmp_path / "trials").read_bytes().splitlines()
    ]
    assert outcomes[0]["blockers"] == ["SUPERSEDED_REVISION"]
    assert outcomes[-2]["blockers"] == ["NOT_AVAILABLE_AT_DECISION"]
    assert outcomes[-1]["blockers"] == ["MISSING_OBSERVATION"]
    assert report["status"] == "MODEL_REPLAY_COMPLETED"
    assert report["outcome_counts"]["MODELED_CANDIDATE"] == 45


def test_replay_exact_failure_partial_and_no_useful_call(tmp_path):
    data = dataset(tmp_path, [record(route()), record({"invalid": "payload"}, 1)])
    reports = [
        run_campaign(
            data,
            config(),
            expected_dataset_digest=file_digest(data),
            trials_path=tmp_path / str(i),
        )
        for i in range(2)
    ]
    assert reports[0]["handler_calls"] == 2 and reports[0]["useful_calls"] == 1
    assert reports[0] == reports[1] and reports[0]["outcome_counts"]["FAILED"] == 1
    assert run_campaign(
        data,
        config(stop=1),
        expected_dataset_digest=file_digest(data),
        trials_path=tmp_path / "partial",
    )["pending"]
    data = dataset(tmp_path, [record(route(), available=11)])
    assert (
        run_campaign(
            data,
            config(),
            expected_dataset_digest=file_digest(data),
            trials_path=tmp_path / "none",
        )["status"]
        == "INVALID_CAMPAIGN"
    )


def test_hash_drift_duplicate_keys_and_shared_upstream(tmp_path):
    data = dataset(tmp_path, [record(route()), record(route())])
    expected = file_digest(data)
    rows = tuple(iter_observations(data))
    assert not compare_provider_views(rows)["independent_views"]
    other = replace(rows[1], upstream_families=("independent",))
    assert compare_provider_views((rows[0], other))["independent_views"]
    data.write_bytes(data.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="DRIFT"):
        ResearchDatasetView(data, expected)
    data.write_bytes(b'{"schema":1,"schema":2}\n')
    with pytest.raises(ValueError, match="DUPLICATE"):
        list(iter_observations(data))


def test_liquidation_peg_and_capital_time():
    p = {
        "route": route(),
        "eligible_at_ns": 1,
        "oracle_available_at_ns": 1,
        "collateral_available_at_ns": 1,
        "actor_eligible": True,
    }
    assert evaluate_pack("liquidation_swap", p, cutoff=10)["net_atoms"] == 99
    p["oracle_available_at_ns"] = 11
    assert evaluate_pack("liquidation_swap", p, cutoff=10)["status"] == "BLOCKED"
    p = {
        "route": route(),
        "redemption_right": True,
        "redemption_delay_ns": 0,
        "liquidity_atoms": 1000,
    }
    assert evaluate_pack("peg_wrapper", p, cutoff=10)["net_atoms"] == 99
    p["redemption_delay_ns"] = 1
    assert evaluate_pack("peg_wrapper", p, cutoff=10)["model"] == "DELAYED_CAPITAL"
    for strategy in ("cross_chain", "basis", "funding"):
        p = {
            "strategy": strategy,
            "capital_atoms": 1000,
            "economics": economics(),
            "stages": [
                {
                    "available_at_ns": 1,
                    "start_ns": 10,
                    "end_ns": 20,
                    "locked_atoms": 1000,
                    "cashflow_atoms": 100,
                    "settled": True,
                    "hedge_assumption": "fixture",
                }
            ],
        }
        r = evaluate_pack("capital_timeline", p, cutoff=10)
        assert (
            r["net_atoms"] == 99
            and r["available_flashloan_repayment_from_future_cashflow"] == 0
        )
        p["stages"][0]["available_at_ns"] = 11
        assert evaluate_pack("capital_timeline", p, cutoff=10)["status"] == "BLOCKED"


def test_clearing_constraints_independent_of_solver():
    intents = (
        ClearingIntent("left", "A", "B", 10, 10, 0, 100),
        ClearingIntent("right", "B", "A", 10, 10, 0, 100),
    )
    result = clear_intents(intents, now_ns=10, lot_sizes=(("A", 1), ("B", 1)))
    assert result.fills and verify_clearing(intents, result, cutoff=10)
    bad = replace(result, fills=(replace(result.fills[0], left_sell_atoms=11),))
    assert not verify_clearing(intents, bad, cutoff=10)
    p = {"intents": [asdict(i) for i in intents], "lot_sizes": [["A", 1], ["B", 1]]}
    assert evaluate_pack("intent_clearing", p, cutoff=10)["status"] == "MODELED_MATCH"


@given(
    st.integers(min_value=1, max_value=10**24), st.integers(min_value=0, max_value=1000)
)
def test_integer_profit_never_counts_borrow_fee_twice(principal, fee):
    p = economics()
    p["principal_atoms"] = principal
    p["repayment_atoms"] = principal + fee
    p["output_atoms"] = principal + fee + 10
    p["costs"][0]["atoms"] = fee
    ledger, unknown = cost_ledger(p)
    assert not unknown and ledger.conservative_profit_atoms == 10


def test_exclusive_run_reuse_conflict_and_artifact_tampering(tmp_path):
    data = dataset(tmp_path, [record(route())])
    cfg = tmp_path / "config.json"
    cfg.write_bytes(canonical(config()))
    request = {
        "schema": "studious.occ-research-request.v1",
        "run_id": "example",
        "source_commit": "a" * 40,
        "dataset": str(data),
        "dataset_sha256": file_digest(data),
        "config": str(cfg),
        "config_sha256": file_digest(cfg),
        "output_root": str(tmp_path / "output"),
    }

    def verify(_):
        return None

    first = execute_request(request, verify_source=verify)
    second = execute_request(request, verify_source=verify)
    assert (
        not first["replayed"]
        and second["replayed"]
        and first["receipt"] == second["receipt"]
    )
    (tmp_path / "output/example/trials.jsonl").write_text("changed")
    with pytest.raises(ValueError, match="ARTIFACT_CHANGED"):
        execute_request(request, verify_source=verify)


def test_interrupted_claim_is_never_reexecuted(tmp_path):
    data = dataset(tmp_path, [])
    cfg = tmp_path / "config.json"
    cfg.write_bytes(canonical(config()))
    request = {
        "schema": "studious.occ-research-request.v1",
        "run_id": "interrupted",
        "source_commit": "a" * 40,
        "dataset": str(data),
        "dataset_sha256": file_digest(data),
        "config": str(cfg),
        "config_sha256": file_digest(cfg),
        "output_root": str(tmp_path / "output"),
    }
    run = tmp_path / "output/interrupted"
    run.mkdir(parents=True)
    with pytest.raises(ValueError, match="RECONCILIATION_REQUIRED"):
        execute_request(request, verify_source=lambda _: None)


# Nonempty stateful corpus over the installed lender arithmetic. This is model
# qualification, not protocol instructions, state acquisition or real replay.
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule
from src.lending.financing import FinancingEvidence
from src.lending.shadow_capacity import ShadowFundingCapacity, debt_is_closed


class FundingArithmeticMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.capacity = ShadowFundingCapacity(
            FinancingEvidence("fixture", "fixture", 1, "a" * 64, "fixture", 1),
            "offline",
            "A",
            1000,
            1,
            1000,
            0,
            0,
            100,
            True,
            True,
        )
        self.obligations = []
        self.checks = 0

    @rule(principal=st.integers(min_value=1, max_value=1500))
    def borrow(self, principal):
        if principal > self.capacity.available_atoms:
            with pytest.raises(ValueError):
                self.capacity.repayment(
                    principal, now_ns=10, domain="offline", asset_identity="A"
                )
        else:
            debt = self.capacity.repayment(
                principal, now_ns=10, domain="offline", asset_identity="A"
            )
            self.obligations.append((principal, debt))
            assert debt == principal + 1
        self.checks += 1

    @rule(shortfall=st.booleans())
    def settlement(self, shortfall):
        if not self.obligations:
            return
        principal, debt = self.obligations.pop(0)
        output = debt - 1 if shortfall else debt
        assert (
            debt_is_closed(
                outputs_by_asset={"A": output},
                repayments_by_asset={"A": debt},
                native_wallet_atoms=0,
                native_cost_atoms=0,
            )
            is not shortfall
        )
        assert not debt_is_closed(
            outputs_by_asset={"B": debt},
            repayments_by_asset={"A": debt},
            native_wallet_atoms=0,
            native_cost_atoms=0,
        )
        self.checks += 1

    @invariant()
    def obligations_preserve_integer_exact_asset_debt(self):
        assert all(
            type(debt) is int and principal < debt
            for principal, debt in self.obligations
        )


TestFundingArithmeticMachine = FundingArithmeticMachine.TestCase


def test_all_failed_handlers_do_not_establish_a_useful_campaign(tmp_path):
    data = dataset(tmp_path, [record({"invalid": "payload"})])
    report = run_campaign(
        data,
        config(),
        expected_dataset_digest=file_digest(data),
        trials_path=tmp_path / "failed-trials",
    )
    assert report["handler_calls"] == 1 and report["useful_calls"] == 0
    assert not report["campaign_executed"] and report["status"] == "INVALID_CAMPAIGN"


def test_instrument_generation_is_part_of_economic_dedup_identity(tmp_path):
    data = dataset(tmp_path, [record(route(), 0), record(route(), 1)])
    rows = tuple(iter_observations(data))
    same = replace(
        rows[0], observation=replace(rows[0].observation, instrument_version="v2")
    )
    assert rows[0].opportunity_id != same.opportunity_id
