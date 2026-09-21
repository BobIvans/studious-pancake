"""PR-302 / NF-893..896: final frontier coverage and next-cycle discipline."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega808Error, Result, require_nonnegative, result, stable_hash


def audit_post238_strategy_coverage(requirements: Mapping[str,str], evidence_by_requirement: Mapping[str,str]) -> Result:
    missing=tuple(sorted(key for key in requirements if not evidence_by_requirement.get(key)))
    return result("audit_post238_strategy_coverage", {"requirement_count":len(requirements),"evidence_count":len(evidence_by_requirement),"missing_requirements":missing,"coverage_complete":not missing}, status="OK" if not missing else "INCOMPLETE", blockers=("COVERAGE_INCOMPLETE",) if missing else ())


def run_frontier_integration_campaign(*, cases: Sequence[Mapping[str,object]], max_cases: int, network_access: bool=False) -> Result:
    if network_access:
        raise Mega808Error("NETWORK_ACCESS_FORBIDDEN")
    limit=require_nonnegative(max_cases,"max_cases")
    selected=tuple(dict(case) for case in cases[:limit])
    outcomes=tuple(str(case.get("outcome","UNKNOWN")) for case in selected)
    return result("run_frontier_integration_campaign", {"case_count":len(selected),"outcomes":outcomes,"network_access":False,"bounded":len(cases)<=limit})


def publish_frontier_verdict(*, code_closed: bool, research_closed: bool, profile_qualified: bool, blockers: Sequence[str]) -> Result:
    blocker_tuple=tuple(dict.fromkeys(str(x) for x in blockers if str(x)))
    if blocker_tuple:
        verdict="BLOCKED"
    elif profile_qualified:
        verdict="QUALIFIED"
    elif code_closed and research_closed:
        verdict="MERGED"
    else:
        verdict="DEFERRED"
    return result("publish_frontier_verdict", {"verdict":verdict,"code_closed":code_closed,"research_closed":research_closed,"profile_qualified":profile_qualified,"blockers":blocker_tuple,"live_enabled":False}, status="OK" if not blocker_tuple else "BLOCKED", blockers=blocker_tuple)


def schedule_next_roadmap_cycle(findings: Sequence[Mapping[str,object]]) -> Result:
    accepted=[]
    rejected=[]
    for finding in findings:
        evidence=finding.get("evidence_hash")
        reproducible=bool(finding.get("reproducible",False))
        novel=bool(finding.get("novel",False))
        if evidence and reproducible and novel:
            accepted.append(dict(finding))
        else:
            rejected.append(str(finding.get("id","unknown")))
    return result("schedule_next_roadmap_cycle", {"accepted_findings":tuple(accepted),"rejected_ids":tuple(rejected),"next_cycle_created":bool(accepted),"reason":"EVIDENCE_BACKED_FINDINGS_ONLY"})
