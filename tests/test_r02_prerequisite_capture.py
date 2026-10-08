"""Replay authentic partial chain reads without promoting them to capital."""

from copy import deepcopy
import json
from pathlib import Path
import runpy

import pytest

from src.qualification_campaign.identity import digest

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "docs/verification/r02-2026-10-08"
replay = runpy.run_path(str(DIRECTORY / "capture_prerequisites.py"))["replay"]


def capture():
    return json.loads((DIRECTORY / "CAPTURE.json").read_text())


def seal(data):
    for row in data["records"]:
        row["response_hash"] = digest(row.get("response"))
        row["request_hash"] = digest(
            row["request_body"]
            if row["method"] == "GraphQL checkpoint"
            else {"method": row["method"], "params": row["params"]}
        )
    data["records_sha256"] = digest(data["records"])


def test_real_admin_replays_deterministically_without_capital_authority():
    data = capture()
    result = replay(data)
    assert result == replay(deepcopy(data))
    assert result["jupiter_admin"]["status"] is True
    assert result["jupiter_admin"]["flashloan_fee"] == 0
    assert result["qualified_edges"] == []
    assert result["execution_authority"] == "NONE"
    assert result["status"] == "BLOCKED_MISSING_PINNED_RESERVE_ABI"


def test_unsealed_capture_tampering_is_rejected():
    data = capture()
    data["records"][0]["observed_at_ns"] += 1
    with pytest.raises(ValueError, match="CAPTURE_HASH_MISMATCH"):
        replay(data)


def test_wrong_owner_rejected_even_with_consistent_capture_hashes():
    data = capture()
    data["records"][1]["response"]["result"]["value"][0][
        "owner"
    ] = "11111111111111111111111111111111"
    seal(data)
    with pytest.raises(ValueError, match="ADMIN_OWNER_MISMATCH"):
        replay(data)


def test_wrong_genesis_rejected_even_with_consistent_capture_hashes():
    data = capture()
    data["records"][0]["response"]["result"] = "wrong-network"
    seal(data)
    with pytest.raises(ValueError, match="GENESIS_MISMATCH"):
        replay(data)


def test_unfinalized_capture_is_not_accepted_as_finalized():
    data = capture()
    data["records"][1]["params"][1]["commitment"] = "processed"
    seal(data)
    with pytest.raises(ValueError, match="FINALIZED_BASE64_REQUIRED"):
        replay(data)


@pytest.mark.parametrize("field", ["sign_enabled", "send_enabled"])
def test_execution_flags_are_rejected(field):
    data = capture()
    data["records"][0][field] = True
    seal(data)
    with pytest.raises(ValueError, match="READ_ONLY_CAPTURE_REQUIRED"):
        replay(data)


def test_failed_network_read_cannot_become_successful_admin_observation():
    data = capture()
    for row in data["records"]:
        row.pop("response", None)
        row["error_type"] = "SanitizedTransportError"
        row["error"] = "network state unavailable"
    seal(data)
    result = replay(data)
    assert result["status"] == "NETWORK_STATE_UNAVAILABLE"
    assert result["jupiter_admin"] is None
    assert result["qualified_edges"] == []
