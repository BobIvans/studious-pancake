"""PR-301 / NF-889..892: evidence-grounded AI development research."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega808Error, Result, result, stable_hash


def search_evidence_for_research(records: Sequence[Mapping[str,object]], *, query_terms: Sequence[str]) -> Result:
    terms=tuple(str(x).lower() for x in query_terms if str(x))
    if not terms:
        raise Mega808Error("QUERY_REQUIRED")
    matches=[]
    for record in records:
        text=" ".join(str(v) for v in record.values()).lower()
        if all(term in text for term in terms):
            matches.append(dict(record))
    return result("search_evidence_for_research", {"query_terms":terms,"matches":tuple(matches),"source_count":len(records)})


def generate_upstream_dossier(*, repository: str, commit: str, path: str, symbol: str, license_id: str|None, tests_found: bool) -> Result:
    if not repository or len(commit)!=40 or not path or not symbol:
        raise Mega808Error("UPSTREAM_PIN_INCOMPLETE")
    blockers=() if license_id else ("LICENSE_UNVERIFIED",)
    return result("generate_upstream_dossier", {"repository":repository,"commit":commit,"path":path,"symbol":symbol,"license_id":license_id,"tests_found":tests_found,"source_copy_allowed":False}, status="OK" if not blockers else "INCOMPLETE", blockers=blockers)


def draft_pr_research_brief(*, scope: str, evidence_ids: Sequence[str], non_goals: Sequence[str]) -> Result:
    if not scope or not evidence_ids:
        raise Mega808Error("BRIEF_EVIDENCE_REQUIRED")
    return result("draft_pr_research_brief", {"scope":scope,"evidence_ids":tuple(dict.fromkeys(evidence_ids)),"non_goals":tuple(non_goals),"execution_authority":False})


def verify_agent_citations(citations: Sequence[Mapping[str,object]], *, current_source_hashes: Mapping[str,str]) -> Result:
    stale=[]
    unsupported=[]
    for idx,citation in enumerate(citations):
        source=str(citation.get("source",""))
        digest=str(citation.get("hash",""))
        if not source or source not in current_source_hashes:
            unsupported.append(idx)
        elif current_source_hashes[source]!=digest:
            stale.append(idx)
    blockers=()
    if unsupported: blockers+=("UNSUPPORTED_CITATION",)
    if stale: blockers+=("STALE_CITATION",)
    return result("verify_agent_citations", {"citation_count":len(citations),"unsupported":tuple(unsupported),"stale":tuple(stale),"verified":not blockers}, status="OK" if not blockers else "BLOCKED", blockers=blockers)
