"""PR-296 / NF-869..872: evidence-backed qualification dashboard views."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Result, require_nonnegative, result


def render_qualification_dashboard(statuses: Mapping[str,str]) -> Result:
    allowed={"QUALIFIED","BLOCKED","DEFERRED","PAUSED","UNKNOWN","RESEARCH_ONLY","CODE_CLOSED"}
    normalized={str(k):str(v) for k,v in statuses.items()}
    invalid=tuple(sorted(k for k,v in normalized.items() if v not in allowed))
    return result("render_qualification_dashboard", {"statuses":normalized,"invalid_status_keys":invalid,"ready_claim":not invalid and bool(normalized)} ,status="OK" if not invalid else "BLOCKED", blockers=("UNKNOWN_STATUS_VALUE",) if invalid else ())


def render_strategy_funnel(*, observations: int, episodes: int, simulations: int, survivors: int, finalized_outcomes: int) -> Result:
    vals=[require_nonnegative(v,n) for v,n in ((observations,"observations"),(episodes,"episodes"),(simulations,"simulations"),(survivors,"survivors"),(finalized_outcomes,"finalized_outcomes"))]
    if not vals[0]>=vals[1]>=vals[2]>=vals[3]>=vals[4]:
        return result("render_strategy_funnel", {"observations":vals[0],"episodes":vals[1],"simulations":vals[2],"survivors":vals[3],"finalized_outcomes":vals[4]}, status="BLOCKED", blockers=("FUNNEL_ORDER_INVALID",))
    return result("render_strategy_funnel", {"observations":vals[0],"episodes":vals[1],"simulations":vals[2],"survivors":vals[3],"finalized_outcomes":vals[4]})


def render_data_quality_status(*, gaps: int, disagreements: int, stale_sources: int, source_count: int) -> Result:
    gaps=require_nonnegative(gaps,"gaps"); disagreements=require_nonnegative(disagreements,"disagreements"); stale=require_nonnegative(stale_sources,"stale_sources"); count=require_nonnegative(source_count,"source_count")
    blockers=tuple(code for condition,code in ((gaps>0,"DATA_GAPS"),(disagreements>0,"SOURCE_DISAGREEMENT"),(stale>0,"STALE_SOURCE")) if condition)
    return result("render_data_quality_status", {"gaps":gaps,"disagreements":disagreements,"stale_sources":stale,"source_count":count,"quality_complete":not blockers}, status="OK" if not blockers else "INCOMPLETE", blockers=blockers)


def render_release_blockers(blockers: Sequence[Mapping[str,str]]) -> Result:
    rows=tuple({"code":str(x.get("code","")),"owner":str(x.get("owner","")),"evidence":str(x.get("evidence",""))} for x in blockers)
    incomplete=tuple(i for i,row in enumerate(rows) if not all(row.values()))
    return result("render_release_blockers", {"blockers":rows,"incomplete_rows":incomplete,"release_blocked":bool(rows)}, status="BLOCKED" if rows else "OK", blockers=("OPEN_RELEASE_BLOCKERS",) if rows else ())
