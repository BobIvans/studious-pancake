from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.mega_pr01_v6_runtime_data_plane_gate import (
    REQUIRED_FINDINGS,
    evaluate_mega_pr01_v6_runtime_data_plane_evidence,
)
from src.providers.jupiter.durable_quota import DurableJupiterQuotaManager
from src.providers.jupiter.quota import (
    JupiterQuotaError,
    JupiterQuotaPurpose,
    cache_key,
)


class MutableClock:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def run(coro):
    return asyncio.run(coro)


def _valid_evidence() -> dict[str, object]:
    return {
        "finding_ids": sorted(REQUIRED_FINDINGS),
        "durable_jupiter_quota": {
            "sqlite_backed": True,
            "api_account_scoped": True,
            "begin_immediate_serialized": True,
            "cross_process_tested": True,
            "restart_recovery_tested": True,
            "cooldown_persisted": True,
            "mark_used_exactly_once": True,
            "limit": 60,
            "finalization_reserve": 4,
        },
        "semantic_jupiter_cache": {
            "canonical_json_sha256": True,
            "collision_property_tested": True,
            "lookup_before_quota_spend": True,
            "trace_id_excluded_from_identity": True,
            "provenance_bound_to_request_response": True,
            "identity_fields": [
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
            ],
        },
        "management_secret_read": {
            "uses_read_secure_regular_file": True,
            "single_open_no_follow": True,
            "fstat_before_after": True,
            "symlink_rejected": True,
            "path_swap_tested": True,
            "owner_only_required": True,
        },
        "live_enabled": False,
        "jito_enabled": False,
        "signer_loaded": False,
        "sender_loaded": False,
        "private_key_loaded": False,
        "provider_network_enabled": False,
    }


def test_cache_key_is_collision_resistant_for_delimiter_ambiguity() -> None:
    left = cache_key(("a|b", "c"))
    right = cache_key(("a", "b|c"))
    assert left != right
    assert left.startswith("jupiter-cache:v2:")
    assert right.startswith("jupiter-cache:v2:")


def test_cache_key_rejects_non_json_values() -> None:
    with pytest.raises(TypeError):
        cache_key((object(),))


def test_durable_quota_is_shared_across_instances(tmp_path: Path) -> None:
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

    token = run(
        first.reserve(JupiterQuotaPurpose.DISCOVERY, request_fingerprint="req-1")
    )
    with pytest.raises(JupiterQuotaError, match="account-wide-quota-exhausted"):
        run(
            second.reserve(
                JupiterQuotaPurpose.DISCOVERY, request_fingerprint="req-2"
            )
        )

    run(first.release_unissued(token))
    replacement = run(
        second.reserve(JupiterQuotaPurpose.DISCOVERY, request_fingerprint="req-2")
    )
    assert replacement.request_fingerprint == "req-2"


def test_durable_retry_after_survives_restart(tmp_path: Path) -> None:
    clock = MutableClock()
    db_path = tmp_path / "quota.sqlite3"
    first = DurableJupiterQuotaManager(
        db_path,
        api_account_id="acct",
        limit=2,
        finalization_reserve=0,
        clock=clock,
    )
    first.record_429(30.0)

    restarted = DurableJupiterQuotaManager(
        db_path,
        api_account_id="acct",
        limit=2,
        finalization_reserve=0,
        clock=clock,
    )
    with pytest.raises(JupiterQuotaError, match="retry-after-active"):
        run(restarted.reserve(request_fingerprint="during-cooldown"))

    clock.advance(31)
    token = run(restarted.reserve(request_fingerprint="after-cooldown"))
    assert token.request_fingerprint == "after-cooldown"


def test_durable_cache_is_semantic_and_available_before_reservation(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    db_path = tmp_path / "quota.sqlite3"
    key = cache_key(
        (
            "account-hash",
            "jupiter-v2-build",
            "mint-a",
            "mint-b",
            100,
            "taker",
            "payer",
            50,
            "dex-policy",
            "discovery",
            "quote",
        )
    )
    first = DurableJupiterQuotaManager(
        db_path, api_account_id="acct", limit=1, finalization_reserve=0, clock=clock
    )
    first.cache_put(key, {"outAmount": "101"}, ttl_seconds=10)

    restarted = DurableJupiterQuotaManager(
        db_path, api_account_id="acct", limit=1, finalization_reserve=0, clock=clock
    )
    assert restarted.cache_get(key) == {"outAmount": "101"}
    assert restarted.snapshot()["window_occupancy"] == 0


def test_v6_gate_accepts_complete_fail_closed_evidence() -> None:
    report = evaluate_mega_pr01_v6_runtime_data_plane_evidence(_valid_evidence())
    assert report.ok
    assert report.runtime_wiring_allowed
    assert not report.live_enabled
    assert not report.signer_loaded
    assert not report.sender_loaded


def test_v6_gate_blocks_missing_secret_and_forbidden_live_surface() -> None:
    evidence = _valid_evidence()
    evidence["live_enabled"] = True
    secret = dict(evidence["management_secret_read"])
    secret["single_open_no_follow"] = False
    evidence["management_secret_read"] = secret

    report = evaluate_mega_pr01_v6_runtime_data_plane_evidence(evidence)

    assert not report.ok
    assert {item.code for item in report.violations} >= {
        "MPR01_V6_SECRET_NOT_SINGLE_OPEN",
        "MPR01_V6_FORBIDDEN_RUNTIME_SURFACE",
    }
