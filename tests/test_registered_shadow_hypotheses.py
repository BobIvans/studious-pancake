from dataclasses import replace
import pytest
from src.mechanism_discovery.research_quality import (
    RegisteredHypothesis,
    ResearchEpisode,
    evaluate_registered_holdout,
)
from src.mechanism_discovery.evidence_native_core import EvidenceNativeError


def test_precommit_holdout_null_latency_and_multiple_testing():
    rows = tuple(
        ResearchEpisode(str(i), i * 10, i * 10 + 2, 10, 10) for i in range(1, 5)
    )
    spec = RegisteredHypothesis("h", 1, "f", 10, 1, 1)
    args = dict(train_end=22, embargo=1, raw_pvalue_num=1, raw_pvalue_den=1000)
    result = evaluate_registered_holdout(spec, rows, **args)
    assert result["holdout_episode_ids"] == ("3", "4")
    assert result["cost_adjusted_improvement_atoms"] == 9
    assert result["family_significant"]
    assert not evaluate_registered_holdout(
        replace(spec, family_test_count=100), rows, **args
    )["family_significant"]
    assert not result["execution_right"]
    for invalid in (replace(spec, registered_at_ns=31), replace(spec, latency_ns=2)):
        with pytest.raises(EvidenceNativeError):
            evaluate_registered_holdout(invalid, rows, **args)
    with pytest.raises(EvidenceNativeError, match="OVERLAP"):
        evaluate_registered_holdout(
            spec, (rows[0], replace(rows[1], feature_available_at=11)), **args
        )
