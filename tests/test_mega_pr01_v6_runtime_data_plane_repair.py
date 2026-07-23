from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.mega_pr01_v6_runtime_data_plane_gate import (
    REQUIRED_FINDINGS,
    evaluate_mega_pr01_v6_runtime_data_plane_evidence,
)
from src.providers.jupiter.durable_quota import DurableJupiterQuotaManager
from src.providers.jupiter.quota import JupiterQuotaError, JupiterQuotaPurpose, cache_key


class MutableClock:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def run(coro):
    return asyncio.run(coro)


def _good_evidence() -> dict[str, object]:
    return {
        "closed_findings": REQUIRED_FINDINGS,
        "durable_jupiter_quota": {
            "api_account_scoped": True,
            "serialized_with_begin_immediate": True,
            "cross_process_tested": True,
            "restart_recovery_tested": True,
            "cooldown_persisted": True,
            "reserve_mark_used_release_atomic": True,
        },
        "semantic_jupiter_cache": {
            "canonical_json_sha256": True,
            "collision_property_tested": True,
            "lookup_before_quota_spend": True,
            "trace_id_excluded_from_identity": True,
            "provenance_bound_to_request_response": True,
            "identity_fields": (
                "api_account_hash",
                "endpoint_schema",
                "input_mint",
                "output_mint",
                "amount",
                "taker",
                "payer",
                "slippage_bps",
                "dex_policy",
                "purpose",
                "lifecycle_stage",
            ),
        },
        "management_secret_filesystem": {
            "uses_single_open_helper": True,
            "uses_no_follow": True,
            "fstat_before_after": True,
            "owner_only_enforced": True,
            "symlink_path_swap_tested": True,
            "check_then_open_removed": True,
        },
    }


def test_v6_gate_accepts_complete_sender_free_evidence() -> None:
    report = evaluate_mega_pr01_v6_runtime_data_plane_evidence(_good_evidence())
    assert report.ready
    assert report.to_dict()["live_enabled"] is False
    assert report.to_dict()["signer_loaded"] is False
    assert report.to_dict()["sender_loaded"] is False


def test_v6_gate_blocks_incomplete_findings_and_forbidden_runtime() -> None:
    evidence = _good_evidence()
    evidence["closed_findings"] = ("IMPL-85",)
    evidence["live_enabled"] = True

    report = evaluate_mega_pr01_v6_runtime_data_plane_evidence(evidence)
    codes = {item.code for item in report.violations}
    assert "MPR01_V6_FINDINGS_INCOMPLETE" in codes
    assert "MPR01_V6_FORBIDDEN_RUNTIME_SURFACE" in codes


def test_v6_gate_requires_secret_single_open_evidence() -> None:
    evidence = _good_evidence()
    filesystem = dict(evidence["management_secret_filesystem"])
    filesystem["check_then_open_removed"] = False
    evidence["management_secret_filesystem"] = filesystem

    report = evaluate_mega_pr01_v6_runtime_data_plane_evidence(evidence)
    assert {item.code for item in report.violations} == {
        "MPR01_V6_SECRET_CHECK_THEN_OPEN"
    }


def test_cache_key_is_collision_resistant_and_sha256() -> None:
    left = cache_key(("a|b", "c"))
    right = cache_key(("a", "b|c"))
    assert left != right
    assert len(left) == 64
    assert all(char in "0123456789abcdef" for char in left)


def test_durable_quota_is_shared_by_api_account_across_managers(tmp_path: Path) -> None:
    clock = MutableClock()
    db_path = tmp_path / "quota.sqlite3"
    first = DurableJupiterQuotaManager(
        db_path,
        api_account_id="acct",
        limit=1,
        window_seconds=60,
        finalization_reserve=0,
        clock=clock,
    )
    second = DurableJupiterQuotaManager(
        db_path,
        api_account_id="acct",
        limit=1,
        window_seconds=60,
        finalization_reserve=0,
        clock=clock,
    )

    token = run(first.reserve(JupiterQuotaPurpose.DISCOVERY, request_fingerprint="req-1"))
    with pytest.raises(JupiterQuotaError, match="account-wide-quota-exhausted"):
        run(second.reserve(JupiterQuotaPurpose.DISCOVERY, request_fingerprint="req-2"))

    run(first.release_unissued(token))
    replacement = run(second.reserve(JupiterQuotaPurpose.DISCOVERY, request_fingerprint="req-2"))
    assert replacement.request_fingerprint == "req-2"


def test_durable_retry_after_survives_restart(tmp_path: Path) -> None:
    clock = MutableClock()
    db_path = tmp_path / "quota.sqlite3"
    first = DurableJupiterQuotaManager(
        db_path,
        api_account_id="acct",
        limit=2,
        window_seconds=60,
        finalization_reserve=0,
        clock=clock,
    )
    first.record_http_429(30)

    restarted = DurableJupiterQuotaManager(
        db_path,
        api_account_id="acct",
        limit=2,
        window_seconds=60,
        finalization_reserve=0,
        clock=clock,
    )
    with pytest.raises(JupiterQuotaError, match="retry-after-active"):
        run(restarted.reserve(request_fingerprint="during-cooldown"))

    clock.advance(31)
    token = run(restarted.reserve(request_fingerprint="after-cooldown"))
    assert token.request_fingerprint == "after-cooldown"


def test_durable_cache_is_semantic_and_available_before_reservation(tmp_path: Path) -> None:
    clock = MutableClock()
    db_path = tmp_path / "quota.sqlite3"
    key = cache_key(
        (
            "api-account-sha",
            "/swap/v2/build",
            "So11111111111111111111111111111111111111112",
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            1_000_000,
            "taker-pubkey",
            50,
            ("Raydium",),
            (),
            "discovery",
        )
    )
    writer = DurableJupiterQuotaManager(
        db_path,
        api_account_id="acct",
        limit=1,
        window_seconds=60,
        finalization_reserve=0,
        clock=clock,
    )
    reader = DurableJupiterQuotaManager(
        db_path,
        api_account_id="acct",
        limit=1,
        window_seconds=60,
        finalization_reserve=0,
        clock=clock,
    )

    writer.cache_put(
        key,
        {"schema": "quote-fixture", "outAmount": "123"},
        ttl_seconds=10,
        provenance={"request_hash": key},
    )
    assert reader.cache_get(key) == {"schema": "quote-fixture", "outAmount": "123"}

    # A cache hit can be consumed before quota reservation; the DB still has
    # zero window occupancy, proving cache reuse does not spend a request.
    assert reader.snapshot()["window_occupancy"] == 0

    clock.advance(11)
    assert reader.cache_get(key) is None
