from __future__ import annotations

import pytest

from src.durable_paper_runtime_pr156 import (
    PR156ConcurrencyEvidence,
    PR156DurableStoreEvidence,
    PR156Manifest,
    PR156MultiRpcEvidence,
    PR156ObservabilityEvidence,
    PR156RuntimeError,
    PR156RuntimeTruthBinding,
    PR156ShadowHarnessEvidence,
    PR156StageBudget,
    PR156State,
    PR156TransportEvidence,
    PR156WebhookEvidence,
    REQUIRED_DURABLE_TABLES,
    REQUIRED_FAULTS,
    assert_pr156_review_ready,
    evaluate_pr156,
    make_stage_budgets,
    sha256_json,
)

BASE_MAIN = "a" * 40


def h(name: str) -> str:
    return sha256_json({"fixture": name})


def good(**overrides: object) -> PR156Manifest:
    values: dict[str, object] = {
        "repo_full_name": "BobIvans/studious-pancake",
        "branch": "pr-156-durable-paper-runtime-gate",
        "runtime_truth": PR156RuntimeTruthBinding(BASE_MAIN, h("truth"), h("policy"), h("admission"), h("market"), h("tx")),
        "durable_store": PR156DurableStoreEvidence(True, False, True, True, True, REQUIRED_DURABLE_TABLES, h("backup")),
        "concurrency": PR156ConcurrencyEvidence(True, True, True, True, True, True, True, make_stage_budgets()),
        "transport": PR156TransportEvidence(True, True, True, True, True, True),
        "webhook": PR156WebhookEvidence(True, True, True, True, True, True),
        "multi_rpc": PR156MultiRpcEvidence(True, True, True, True),
        "observability": PR156ObservabilityEvidence(True, True, True, h("replay"), True, True),
        "shadow_harness": PR156ShadowHarnessEvidence(True, h("soak"), True, True, 0, True, True, REQUIRED_FAULTS),
    }
    values.update(overrides)
    return PR156Manifest(**values)  # type: ignore[arg-type]


def test_happy_path_review_ready_but_live_and_sender_disabled() -> None:
    decision = evaluate_pr156(good(profitable_fixture_claim=True, healthy_idle_claim=True))
    assert decision.state is PR156State.REVIEW_READY
    assert decision.paper_runtime_claim_allowed is True
    assert decision.healthy_idle_claim_allowed is True
    assert decision.live_claim_allowed is False
    assert decision.sender_submission_allowed is False


def test_jsonl_cannot_remain_authoritative() -> None:
    store = PR156DurableStoreEvidence(True, True, True, True, True, REQUIRED_DURABLE_TABLES, h("backup"))
    assert "JSONL_STILL_AUTHORITATIVE" in evaluate_pr156(good(durable_store=store)).blockers


def test_required_durable_tables_are_complete() -> None:
    tables = tuple(t for t in REQUIRED_DURABLE_TABLES if t != "outbox")
    store = PR156DurableStoreEvidence(True, False, True, True, True, tables, h("backup"))
    assert "DURABLE_TABLE_MISSING:outbox" in evaluate_pr156(good(durable_store=store)).blockers


def test_runner_must_be_continuous_and_structured() -> None:
    conc = PR156ConcurrencyEvidence(True, False, False, True, True, True, True, make_stage_budgets())
    blockers = evaluate_pr156(good(concurrency=conc)).blockers
    assert "RUNNER_NOT_CONTINUOUS" in blockers
    assert "STRUCTURED_CONCURRENCY_MISSING" in blockers


def test_each_stage_needs_budget() -> None:
    budgets = tuple(b for b in make_stage_budgets() if b.stage_id != "paper_outcome")
    conc = PR156ConcurrencyEvidence(True, True, True, True, True, True, True, budgets)
    assert "STAGE_BUDGET_MISSING:paper_outcome" in evaluate_pr156(good(concurrency=conc)).blockers


def test_stage_p95_cannot_exceed_deadline() -> None:
    budget = PR156StageBudget("discovery", 100, 1, p95_latency_ms=150)
    budgets = tuple(budget if b.stage_id == "discovery" else b for b in make_stage_budgets())
    conc = PR156ConcurrencyEvidence(True, True, True, True, True, True, True, budgets)
    assert "STAGE_P95_EXCEEDS_DEADLINE:discovery" in evaluate_pr156(good(concurrency=conc)).blockers


def test_transport_must_be_hardened() -> None:
    blockers = evaluate_pr156(good(transport=PR156TransportEvidence(False, True, False, True, True, False))).blockers
    assert "RESPONSE_SIZE_LIMIT_MISSING" in blockers
    assert "REDIRECT_POLICY_MISSING" in blockers
    assert "RAW_SECRET_EXCEPTION_RISK" in blockers


def test_webhook_needs_auth_fast_ack_dedup_and_backfill() -> None:
    blockers = evaluate_pr156(good(webhook=PR156WebhookEvidence(False, False, True, False, True, False))).blockers
    assert "WEBHOOK_AUTH_HEADER_NOT_VERIFIED" in blockers
    assert "WEBHOOK_FAST_ACK_MISSING" in blockers
    assert "WEBHOOK_DEDUP_NOT_PERSISTENT" in blockers
    assert "WEBHOOK_GAP_BACKFILL_MISSING" in blockers


def test_rpc_aliases_cannot_count_as_quorum() -> None:
    assert "RPC_ALIAS_QUORUM_RISK" in evaluate_pr156(good(multi_rpc=PR156MultiRpcEvidence(True, True, True, False))).blockers


def test_observability_requires_replay_hash() -> None:
    obs = PR156ObservabilityEvidence(True, True, True, "not-a-hash", True, True)
    assert "REPLAY_HASH_INVALID" in evaluate_pr156(good(observability=obs)).blockers


def test_shadow_harness_must_be_sender_free_and_keyless() -> None:
    harness = PR156ShadowHarnessEvidence(True, h("soak"), True, True, 0, False, False, REQUIRED_FAULTS)
    blockers = evaluate_pr156(good(shadow_harness=harness)).blockers
    assert "SENDER_PRESENT_IN_SOAK" in blockers
    assert "PRIVATE_KEY_PRESENT_IN_SOAK" in blockers


def test_required_fault_injections_are_complete() -> None:
    faults = tuple(f for f in REQUIRED_FAULTS if f != "db_lock")
    harness = PR156ShadowHarnessEvidence(True, h("soak"), True, True, 0, True, True, faults)
    assert "FAULT_INJECTION_MISSING:db_lock" in evaluate_pr156(good(shadow_harness=harness)).blockers


def test_live_claim_and_sender_enabled_are_blocked() -> None:
    blockers = evaluate_pr156(good(live_claim=True, sender_enabled=True)).blockers
    assert "LIVE_CLAIM_FORBIDDEN_IN_PR156" in blockers
    assert "SENDER_ENABLED_FORBIDDEN_IN_PR156" in blockers


def test_assert_helper_raises_typed_blocker_summary() -> None:
    with pytest.raises(PR156RuntimeError) as exc:
        assert_pr156_review_ready(good(repo_full_name="other/repo"))
    assert "PR156_BLOCKED:REPO_MISMATCH" in str(exc.value)
