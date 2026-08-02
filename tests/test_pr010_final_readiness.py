from src.pr010_final_readiness import REQUIRED_MERGES, SCHEMA_VERSION, Decision, evaluate_final_readiness

HASH = "0123456789abcdef" * 4


def manifest():
    return {
        "schema_version": SCHEMA_VERSION,
        "merged_prs": [
            {"id": pr, "merge_commit": f"{number:040x}", "verified_ancestor": True}
            for number, pr in enumerate(REQUIRED_MERGES, 1)
        ],
        "stale_open_branches": [],
        "product_graph": {
            "installed_wheel_graph_sha256": HASH,
            "release_bundle_sha256": HASH,
            "qualification_log_sha256": HASH,
            "single_composition_root": True,
            "source_wheel_parity": True,
            "clean_install_verified": True,
            "release_bundle_verified": True,
            "authority_count": 1,
            "superseded_proof_islands": [],
        },
        "production_debt": [{
            "id": "DEBT-1", "status": "closed",
            "evidence": {"materialized": True, "verified": True, "sha256": HASH, "path": "release/debt-1.json"},
        }],
    }


def codes(result):
    return {blocker.code for blocker in result.blockers}


def test_complete_materialized_final_state_is_ready():
    result = evaluate_final_readiness(manifest())
    assert result.decision is Decision.READY
    assert result.production_debt_closed == ("DEBT-1",)


def test_pr010_blocks_until_all_prior_prs_are_merged_in_order():
    item = manifest()
    item["merged_prs"] = item["merged_prs"][:4]
    assert "MERGE_ORDER" in codes(evaluate_final_readiness(item))


def test_debt_claim_without_materialized_evidence_stays_open():
    item = manifest()
    item["production_debt"][0]["evidence"]["materialized"] = False
    result = evaluate_final_readiness(item)
    assert result.decision is Decision.BLOCKED
    assert {"DEBT_WITHOUT_EVIDENCE", "OPEN_DEBT"} <= codes(result)
    assert result.production_debt_open == ("DEBT-1",)


def test_parallel_authorities_and_proof_islands_block_readiness():
    item = manifest()
    item["product_graph"]["authority_count"] = 2
    item["product_graph"]["superseded_proof_islands"] = ["legacy-gate"]
    assert {"PRODUCT_AUTHORITY", "PROOF_ISLANDS"} <= codes(evaluate_final_readiness(item))


def test_stale_branch_and_unverified_bundle_block_readiness():
    item = manifest()
    item["stale_open_branches"] = ["pr-004-old"]
    item["product_graph"]["release_bundle_verified"] = False
    assert {"STALE_BRANCHES", "PRODUCT_GRAPH"} <= codes(evaluate_final_readiness(item))
