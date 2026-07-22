from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.authority_map import AuthorityMap, AuthorityMapError

ROOT = Path(__file__).resolve().parents[1]


def _raw() -> dict[str, object]:
    return json.loads(
        (ROOT / "config/runtime_authority_map.json").read_text(encoding="utf-8")
    )


def test_numeric_verticals_have_one_active_branch_and_live_is_hard_disabled():
    authority = AuthorityMap.load_default()
    assert [item.roadmap_pr for item in authority.verticals] == [
        f"PR-{index:02d}" for index in range(1, 11)
    ]
    assert sum(bool(item.active_branches) for item in authority.verticals) == 1
    assert authority.verticals[0].active_branches == (
        "roadmap/pr-01-repository-authority-consolidation",
    )
    assert all(item.hard_disabled for item in authority.verticals[7:])


def test_repository_contract_matches_entrypoint_capabilities_and_package_mirrors():
    authority = AuthorityMap.load_default()
    assert authority.validate_repository(ROOT) == ()
    assert authority.supported_entrypoint.target == "src.cli_pr189:main"
    assert authority.product_state == "not-production-ready"


def test_open_pull_requests_are_candidates_not_runtime_authorities():
    authority = AuthorityMap.load_default()
    assert authority.open_pr_queue
    assert all(item.authority_status != "active" for item in authority.open_pr_queue)
    superseded = {
        item.github_pr
        for item in authority.open_pr_queue
        if item.authority_status == "superseded"
    }
    assert {127, 199, 217, 223, 233} <= superseded


def test_duplicate_concern_fails_closed(tmp_path: Path):
    raw = _raw()
    duplicate = copy.deepcopy(raw["authorities"][0])
    raw["authorities"].append(duplicate)
    path = tmp_path / "authority.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(AuthorityMapError, match="duplicate authority concern"):
        AuthorityMap.load(path)


def test_second_active_branch_for_one_vertical_fails_closed(tmp_path: Path):
    raw = _raw()
    raw["verticals"][0]["active_branches"].append("competing/pr-01")
    path = tmp_path / "authority.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(AuthorityMapError, match="multiple active branches"):
        AuthorityMap.load(path)


def test_superseded_implementation_cannot_remain_active_owner(tmp_path: Path):
    raw = _raw()
    raw["superseded_implementations"].append(
        {
            "path": raw["authorities"][0]["owner_path"],
            "status": "quarantined",
            "replacement": "other",
        }
    )
    path = tmp_path / "authority.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(
        AuthorityMapError,
        match="superseded implementation is also an active owner",
    ):
        AuthorityMap.load(path)
