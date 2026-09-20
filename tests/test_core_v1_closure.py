from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from src.execution.core_v1_finalized_settlement import (
    CoreV1FinalizedSettlementProducer,
    DecodedCoreV1FinalizedEvidence,
)
from src.execution.finalized_economic_ledger import (
    EconomicPosting,
    FinalizedEconomicOutcome,
    PostingKind,
)
from src.paper_shadow.a2_exact_attempt_runtime import ExactAttemptRuntimeItem
from src.production_debt import ProductionDebtReport
from src.production_debt_profiles import (
    CoreV1ReleaseProfile,
    evaluate_core_v1_profile_debt,
    inspect_core_v1_code,
)
from src.runtime.core_v1_materializer import (
    CORE_V1_BLOCKED_EXTERNAL,
    CoreV1ExternalBlock,
    CoreV1MaterializedBatchSource,
)

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 64


def _global_report(*ids: str) -> ProductionDebtReport:
    blockers = tuple(
        {
            "id": debt_id,
            "batch": "test",
            "severity": "P0",
            "status": "implementation-pending",
            "title": debt_id,
            "surface": "test",
            "blocks_paper": True,
            "blocks_live": True,
            "observed_reason": "test",
            "required_actions": [],
            "evidence_refs": [],
        }
        for debt_id in ids
    )
    return ProductionDebtReport(
        inventory_schema_version="production-readiness.debt-inventory.v1",
        schema_version="production-readiness.debt-report.v1",
        production_ready=False,
        paper_ready=False,
        live_ready=False,
        blockers=blockers,
        consistency_errors=(),
        observed={},
        batches=(),
    )


def test_core_profile_is_exact_default_off_scope() -> None:
    profile = CoreV1ReleaseProfile.load(
        ROOT / "config/release_profiles/core-marginfi-jupiter-v1.json"
    )
    assert profile.profile_id == "core-marginfi-jupiter-v1"
    assert profile.strategy == "circular_arbitrage"
    assert profile.lender == "marginfi"
    assert profile.router == "jupiter"
    assert profile.submission_transport == "rpc"
    assert profile.live_enabled is False
    assert profile.unrestricted_live_allowed is False
    assert profile.automatic_scale_up_allowed is False
    assert profile.executed_canary_required_for_default_off_review is False


def test_installed_core_is_physically_wired_and_sender_free() -> None:
    facts = inspect_core_v1_code(ROOT)
    assert facts.code_complete, facts.blockers
    source = (ROOT / "src/runtime/runtime_entrypoint.py").read_text()
    assert "build_core_v1_composition" in source
    assert "build_installed_durable_paper_service(" not in source
    combined = "".join(
        (ROOT / path).read_text()
        for path in (
            "src/runtime/core_v1_composition.py",
            "src/runtime/core_v1_materializer.py",
            "src/execution/core_v1_finalized_settlement.py",
        )
    )
    for forbidden in (
        "src.execution.senders",
        "src.execution.live_control",
        "src.legacy_arb_bot",
        "src.ingest.",
    ):
        assert forbidden not in combined


def test_zero_opportunities_is_healthy_empty_exact_batch() -> None:
    materializer = SimpleNamespace(
        profile=SimpleNamespace(profile_id="core-marginfi-jupiter-v1"),
        release_id="release",
        materialize=lambda _draft: None,
    )
    source = CoreV1MaterializedBatchSource(materializer, lambda: ())
    batch = source()
    assert batch.evidence.ready is True
    assert batch.evidence.blockers == ()
    assert batch.items == ()


def test_missing_external_evidence_is_blocked_without_items() -> None:
    materializer = SimpleNamespace(
        profile=SimpleNamespace(profile_id="core-marginfi-jupiter-v1"),
        release_id="release",
        materialize=lambda _draft: None,
    )

    def blocked():
        raise CoreV1ExternalBlock(CORE_V1_BLOCKED_EXTERNAL)

    batch = CoreV1MaterializedBatchSource(materializer, blocked)()
    assert batch.evidence.ready is False
    assert batch.evidence.blockers == (CORE_V1_BLOCKED_EXTERNAL,)
    assert batch.items == ()


def test_materializer_contract_outputs_exact_runtime_items() -> None:
    from src.runtime.core_v1_materializer import CoreV1AttemptMaterializer

    annotation = CoreV1AttemptMaterializer.materialize.__annotations__["return"]
    assert annotation in {ExactAttemptRuntimeItem, "ExactAttemptRuntimeItem"}


def test_profile_scoping_ignores_optional_expansion_and_global_live_state() -> None:
    report = evaluate_core_v1_profile_debt(
        repo_root=ROOT,
        global_report=_global_report(
            "runtime.product-state",
            "runtime.live-entrypoint",
            "external.kamino-klend",
            "lending.kamino-supported-combinations",
            "external.jito-low-latency",
            "submission.jito-unbundling-protection",
            "external.helius-webhook-auth",
            "external.okx-signed-discovery",
        ),
    )
    assert report.core_v1_code_complete is True
    assert report.implementation_blockers == ()
    assert report.external_or_review_blockers == ()
    assert report.eligible_for_production_default_off_review is True
    assert report.production_ready is False
    assert report.release_claim_allowed is False
    assert report.live_enabled is False
    assert report.canary_eligible is False
    assert report.live_capable is False


def test_profile_scoping_keeps_required_external_evidence_blocked() -> None:
    report = evaluate_core_v1_profile_debt(
        repo_root=ROOT,
        global_report=_global_report(
            "external.marginfi-v2",
            "external.jupiter-swap-v2",
            "evidence.real-shadow-soak",
        ),
    )
    assert report.core_v1_code_complete is True
    assert report.core_v1_external_qualification_complete is False
    assert len(report.external_or_review_blockers) == 3
    assert report.eligible_for_production_default_off_review is False
    assert report.production_ready is False


def _raw_hash(raw: object) -> str:
    return hashlib.sha256(
        json.dumps(
            raw,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()


class _Decoder:
    decoder_identity = "test-core-v1-finalized-decoder"

    def decode(self, raw):
        evidence_hash = _raw_hash(raw)
        posting = EconomicPosting(
            posting_id="strategy",
            asset_id="spl:USDC:6",
            base_units=25_000,
            kind=PostingKind.STRATEGY_ASSET_DELTA,
            account_scope="payer-usdc",
            evidence_hash=SHA,
        )
        return DecodedCoreV1FinalizedEvidence(
            attempt_id="attempt",
            attempt_generation=1,
            message_hash=SHA,
            signed_transaction_digest=SHA,
            primary_signature="signature",
            confirmation_status="finalized",
            finalized_slot=123,
            release_hash=SHA,
            config_hash=SHA,
            policy_hash=SHA,
            cluster_genesis_hash=SHA,
            raw_evidence_hash=evidence_hash,
            meta_err=None,
            payer_pre_lamports=None,
            payer_post_lamports=None,
            meta_fee_lamports=None,
            marginfi_liability_pre_base_units=100,
            marginfi_liability_post_base_units=0,
            marginfi_required_repayment_base_units=100,
            marginfi_observed_repayment_base_units=100,
            postings=(posting,),
        )


def test_finalized_producer_derives_repayment_and_reuses_mpr2610() -> None:
    commit = CoreV1FinalizedSettlementProducer(_Decoder()).classify({"raw": "evidence"})
    assert commit.ledger.outcome is FinalizedEconomicOutcome.FINALIZED_REALIZED_PROFIT
    assert commit.ledger.economically_successful is True
    assert commit.release_capital is True
    assert commit.quarantine_capital is False


class _IncompleteDecoder(_Decoder):
    def decode(self, raw):
        value = super().decode(raw)
        return DecodedCoreV1FinalizedEvidence(
            attempt_id=value.attempt_id,
            attempt_generation=value.attempt_generation,
            message_hash=value.message_hash,
            signed_transaction_digest=value.signed_transaction_digest,
            primary_signature=value.primary_signature,
            confirmation_status="confirmed",
            finalized_slot=value.finalized_slot,
            release_hash=value.release_hash,
            config_hash=value.config_hash,
            policy_hash=value.policy_hash,
            cluster_genesis_hash=value.cluster_genesis_hash,
            raw_evidence_hash=value.raw_evidence_hash,
            meta_err=None,
            payer_pre_lamports=None,
            payer_post_lamports=None,
            meta_fee_lamports=None,
            marginfi_liability_pre_base_units=None,
            marginfi_liability_post_base_units=None,
            marginfi_required_repayment_base_units=None,
            marginfi_observed_repayment_base_units=None,
            postings=value.postings,
        )


def test_nonfinalized_economics_quarantines_capital() -> None:
    commit = CoreV1FinalizedSettlementProducer(_IncompleteDecoder()).classify(
        {"raw": "evidence"}
    )
    assert commit.ledger.outcome is FinalizedEconomicOutcome.UNKNOWN_QUARANTINED
    assert commit.release_capital is False
    assert commit.quarantine_capital is True
