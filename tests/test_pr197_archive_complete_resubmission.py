from __future__ import annotations

from dataclasses import dataclass
import inspect
from pathlib import Path
from typing import Mapping

import pytest

from src.submission.resubmission_proof_pr197 import (
    AbsenceProofState,
    ArchiveCompleteResubmissionClient,
    JitoReconciliationEvidence,
    ResubmissionProofError,
    RpcEvidenceSource,
    SQLiteResubmissionProofStore,
    resubmission_decision_from_proof,
)

H = "a" * 64
POLICY = "b" * 64
NEW_PERMIT = "c" * 64
GENESIS = "mainnet-genesis"
SIGNATURE = "signature-one"
BLOCKHASH = "old-blockhash"


@dataclass(frozen=True)
class Response:
    status_code: int
    body: object


class FakeHttp:
    def __init__(self, *, overrides: Mapping[tuple[str, str], object] | None = None):
        self.overrides = dict(overrides or {})
        self.calls: list[tuple[str, str, object]] = []

    async def post_json(self, url, body, *, headers, timeout_seconds):
        method = str(body["method"])
        self.calls.append((url, method, body["params"]))
        provider = "rpc-a" if "rpc-a" in url else "rpc-b"
        result = self.overrides.get((provider, method), self._default(method))
        return Response(
            200,
            {"jsonrpc": "2.0", "id": body["id"], "result": result},
        )

    @staticmethod
    def _default(method: str) -> object:
        if method == "getGenesisHash":
            return GENESIS
        if method == "getSlot":
            return 5_000
        if method == "getBlockHeight":
            return 101
        if method == "isBlockhashValid":
            return {"context": {"slot": 5_000}, "value": False}
        if method == "getSignatureStatuses":
            return {"context": {"slot": 5_000}, "value": [None]}
        if method == "getTransaction":
            return None
        raise AssertionError(method)


class Clock:
    def __init__(self, start: int):
        self.value = start

    def __call__(self) -> int:
        self.value += 1
        return self.value


def sources(*, archive_b: bool = True):
    return (
        RpcEvidenceSource("rpc-a", "operator-a", "https://rpc-a.example", True),
        RpcEvidenceSource("rpc-b", "operator-b", "https://rpc-b.example", archive_b),
    )


async def collect(
    http: FakeHttp,
    *,
    start_ns: int = 2_000,
    expiry_ns: int = 1_000,
    grace_ns: int = 500,
    archive_b: bool = True,
    jito: JitoReconciliationEvidence | None = None,
):
    client = ArchiveCompleteResubmissionClient(
        http,
        sources(archive_b=archive_b),
        clock_ns=Clock(start_ns),
    )
    return await client.collect_proof(
        attempt_id="attempt-197",
        attempt_generation=2,
        old_message_hash=H,
        old_signatures=(SIGNATURE,),
        old_blockhash=BLOCKHASH,
        last_valid_block_height=100,
        min_context_slot=10,
        policy_bundle_hash=POLICY,
        theoretical_expiry_observed_at_ns=expiry_ns,
        grace_period_ns=grace_ns,
        proof_ttl_ns=60,
        jito=jito,
    )


def test_client_has_no_caller_current_height_parameter() -> None:
    parameters = inspect.signature(
        ArchiveCompleteResubmissionClient.collect_proof
    ).parameters
    assert "current_block_height" not in parameters


@pytest.mark.asyncio
async def test_two_archive_sources_can_prove_absence_after_grace() -> None:
    http = FakeHttp()
    proof = await collect(http)

    assert proof.state is AbsenceProofState.VERIFIED_ABSENT
    assert proof.blockers() == ()
    decision = resubmission_decision_from_proof(proof, now_ns=proof.issued_at_ns)
    assert decision.allowed is True
    assert decision.requires_new_permit is True
    assert decision.proof_hash == proof.proof_hash

    methods = [method for _, method, _ in http.calls]
    assert methods.count("getBlockHeight") == 2
    assert methods.count("isBlockhashValid") == 2
    assert methods.count("getSignatureStatuses") == 2
    assert methods.count("getTransaction") == 2
    for _, method, params in http.calls:
        if method == "getSignatureStatuses":
            assert params[1]["searchTransactionHistory"] is True
        if method == "getTransaction":
            assert params[1]["commitment"] == "finalized"


@pytest.mark.asyncio
async def test_one_provider_finalized_transaction_blocks_resend() -> None:
    http = FakeHttp(
        overrides={
            (
                "rpc-b",
                "getSignatureStatuses",
            ): {
                "context": {"slot": 5_000},
                "value": [
                    {
                        "slot": 4_999,
                        "err": None,
                        "confirmationStatus": "finalized",
                    }
                ],
            },
            (
                "rpc-b",
                "getTransaction",
            ): {"slot": 4_999, "meta": {"err": None}},
        }
    )
    proof = await collect(http)

    assert proof.state is AbsenceProofState.LANDED
    decision = resubmission_decision_from_proof(proof, now_ns=proof.issued_at_ns)
    assert decision.allowed is False
    assert decision.requires_freeze is True


@pytest.mark.asyncio
async def test_non_archive_source_or_provider_disagreement_is_ambiguous() -> None:
    non_archive = await collect(FakeHttp(), archive_b=False)
    assert non_archive.state is AbsenceProofState.AMBIGUOUS
    assert "SOURCE_NOT_ARCHIVE_CAPABLE" in non_archive.blockers()

    disagreement = await collect(
        FakeHttp(
            overrides={
                (
                    "rpc-b",
                    "isBlockhashValid",
                ): {"context": {"slot": 5_000}, "value": True}
            }
        )
    )
    assert disagreement.state is AbsenceProofState.AMBIGUOUS
    assert "SOURCE_BLOCKHASH_INVALIDITY_NOT_PROVEN" in disagreement.blockers()


@pytest.mark.asyncio
async def test_grace_period_must_elapse() -> None:
    proof = await collect(FakeHttp(), start_ns=1_200, expiry_ns=1_000, grace_ns=500)
    assert proof.state is AbsenceProofState.AMBIGUOUS
    assert "OBSERVATION_GRACE_PERIOD_NOT_ELAPSED" in proof.blockers()


@pytest.mark.asyncio
async def test_jito_not_found_is_supplementary_not_sufficient() -> None:
    jito = JitoReconciliationEvidence(
        bundle_id="bundle-1",
        expected_signatures=(SIGNATURE,),
        inflight_status="not_found",
        durable_status="not_found",
        observed_at_ns=1_900,
    )
    proof = await collect(FakeHttp(), jito=jito)
    assert proof.state is AbsenceProofState.VERIFIED_ABSENT

    pending = JitoReconciliationEvidence(
        bundle_id="bundle-1",
        expected_signatures=(SIGNATURE,),
        inflight_status="pending",
        durable_status="not_found",
        observed_at_ns=1_900,
    )
    blocked = await collect(FakeHttp(), jito=pending)
    assert blocked.state is AbsenceProofState.AMBIGUOUS
    assert "JITO_INFLIGHT_NOT_TERMINALLY_ABSENT" in blocked.blockers()


@pytest.mark.asyncio
async def test_proof_is_short_lived_and_consumed_once(tmp_path: Path) -> None:
    proof = await collect(FakeHttp())
    store = SQLiteResubmissionProofStore(tmp_path / "resubmission.sqlite")
    store.record_proof(proof)

    authorization = store.authorize_new_permit(
        proof_hash=proof.proof_hash,
        new_permit_request_hash=NEW_PERMIT,
        now_ns=proof.issued_at_ns,
    )
    assert authorization.superseded_message_hash == H
    assert len(authorization.authorization_hash) == 64

    with pytest.raises(ResubmissionProofError, match="already consumed"):
        store.authorize_new_permit(
            proof_hash=proof.proof_hash,
            new_permit_request_hash=NEW_PERMIT,
            now_ns=proof.issued_at_ns,
        )


@pytest.mark.asyncio
async def test_late_landing_latches_freeze(tmp_path: Path) -> None:
    proof = await collect(FakeHttp())
    store = SQLiteResubmissionProofStore(tmp_path / "resubmission.sqlite")
    store.record_proof(proof)
    store.record_late_landing(
        proof_hash=proof.proof_hash,
        signature=SIGNATURE,
        observed_at_ns=proof.issued_at_ns + 1,
    )

    assert store.freeze_required(proof.proof_hash) is True
    with pytest.raises(ResubmissionProofError, match="late landing"):
        store.authorize_new_permit(
            proof_hash=proof.proof_hash,
            new_permit_request_hash=NEW_PERMIT,
            now_ns=proof.issued_at_ns + 2,
        )
