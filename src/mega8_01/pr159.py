"""PR-159 / NF-385..388: governed analytical queries and views."""

from __future__ import annotations

import re

from .common import artifact, fail_closed, canonical_hash, require_sha256, require_text

_MUTATING_SQL = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|attach|detach|copy|call)\b",
    re.IGNORECASE,
)


def register_query_contract(
    query_id: str,
    sql: str,
    dataset_revision: str,
):
    qid = require_text(query_id, "query_id")
    statement = require_text(sql, "sql")
    revision = require_text(dataset_revision, "dataset_revision")
    if _MUTATING_SQL.search(statement):
        return fail_closed(
            child="PR-159",
            nf="NF-385",
            action="register_query_contract",
            subject_id=qid,
            reason="MALFORMED_INPUT",
            payload={"dataset_revision": revision},
        )
    return artifact(
        child="PR-159",
        nf="NF-385",
        action="register_query_contract",
        subject_id=qid,
        payload={
            "sql_sha256": canonical_hash(statement),
            "dataset_revision": revision,
            "read_only": True,
        },
    )


def materialize_research_view(
    query_id: str,
    query_contract_sha256: str,
    dataset_revision: str,
    result_sha256: str,
):
    qid = require_text(query_id, "query_id")
    query_hash = require_sha256(query_contract_sha256, "query_contract_sha256")
    revision = require_text(dataset_revision, "dataset_revision")
    result_hash = require_sha256(result_sha256, "result_sha256")
    return artifact(
        child="PR-159",
        nf="NF-386",
        action="materialize_research_view",
        subject_id=qid,
        payload={
            "query_contract_sha256": query_hash,
            "dataset_revision": revision,
            "result_sha256": result_hash,
        },
    )


def fingerprint_query_plan(
    query_id: str,
    explain_plan: str,
    engine_version: str,
):
    qid = require_text(query_id, "query_id")
    plan = require_text(explain_plan, "explain_plan")
    engine = require_text(engine_version, "engine_version")
    return artifact(
        child="PR-159",
        nf="NF-387",
        action="fingerprint_query_plan",
        subject_id=qid,
        payload={
            "engine_version": engine,
            "plan_sha256": canonical_hash({"engine": engine, "plan": plan}),
        },
    )


def reproduce_evidence_query(
    query_id: str,
    expected_result_sha256: str,
    observed_result_sha256: str,
):
    qid = require_text(query_id, "query_id")
    expected = require_sha256(expected_result_sha256, "expected_result_sha256")
    observed = require_sha256(observed_result_sha256, "observed_result_sha256")
    if expected != observed:
        return fail_closed(
            child="PR-159",
            nf="NF-388",
            action="reproduce_evidence_query",
            subject_id=qid,
            reason="INCONSISTENT_STATE",
            payload={"expected": expected, "observed": observed},
        )
    return artifact(
        child="PR-159",
        nf="NF-388",
        action="reproduce_evidence_query",
        subject_id=qid,
        payload={"expected": expected, "observed": observed},
    )
