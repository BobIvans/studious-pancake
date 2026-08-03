from scripts.verify_mpr_rp_runtime_platform_closure import verify


def test_mpr_rp_static_materialized_closure_gate() -> None:
    report = verify()
    assert report["accepted"] is True, report["blockers"]
