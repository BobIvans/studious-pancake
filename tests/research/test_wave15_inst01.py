from dataclasses import replace
import pytest
from src.research.wave15_institution import (
    EvidenceArtifact,EvidenceResolver,InstitutionError,InstitutionSpec,Offer,ProviderProfile,
    RuleSnapshot,ServiceTask,allocate,canonical_hash,close_episode,
    enumerate_first_price_deviations,run_inst01_demo,run_service,simulate_participation,verify_delivery,
)

def make(mechanism="CAPPED_CRITICAL_PRICE"):
    spec=InstitutionSpec("i","INTEGER_SUM_V1","SYNTHETIC_RESEARCH")
    rule=RuleSnapshot("i",1,mechanism,10,6 if mechanism=="POSTED_PRICE" else None,("a","b","c"),1)
    task=ServiceTask("t","INTEGER_SUM_V1",(2,3,4),10,20,2,canonical_hash({"s":1}),rule.rule_hash,12)
    offers=(Offer("a","t",5,True,1,10),Offer("b","t",7,True,1,10),Offer("c","t",9,True,1,10))
    return spec,rule,task,offers

def evidence(task):
    return EvidenceArtifact.build(evidence_id="e",task_id=task.task_id,state_hash=task.state_hash,rule_hash=task.rule_hash,artifact_kind="TASK_INPUT",payload={"payload":list(task.payload)})

def test_demo_reproducible_and_effect_boundaries():
    a=run_inst01_demo(); b=run_inst01_demo()
    assert a["trace_hash"]==b["trace_hash"]
    assert a["verdict"].status=="PASS_FINITE_SYNTHETIC"
    assert not a["verdict"].production_ready and not a["verdict"].live_authorized

def test_critical_payment_second_bid_and_single_bid_reserve():
    _,rule,task,offers=make()
    assert (allocate(task,offers,rule).winner_id,allocate(task,offers,rule).payment)==("a",7)
    d=allocate(task,offers[:1],rule); assert (d.winner_id,d.payment)==("a",10)

def test_reverse_first_price_and_posted_price():
    _,r,t,o=make("REVERSE_FIRST_PRICE"); assert allocate(t,o,r).payment==5
    _,r,t,o=make("POSTED_PRICE"); d=allocate(t,o,r); assert (d.winner_id,d.payment)==("a",6)

def test_tie_precommitted_and_no_trade():
    _,r,t,_=make("REVERSE_FIRST_PRICE")
    tied=(Offer("b","t",5,True,1,10),Offer("a","t",5,True,1,10))
    assert allocate(t,tied,r).winner_id=="a"
    assert allocate(t,(Offer("a","t",99,True,1,10),),r).status=="NO_TRADE"

def test_bool_money_and_duplicate_provider_rejected():
    with pytest.raises(InstitutionError): RuleSnapshot("i",1,"REVERSE_FIRST_PRICE",True,None,(),1)
    _,r,t,_=make()
    with pytest.raises(InstitutionError):
        allocate(t,(Offer("a","t",5,True,1,10),Offer("a","t",6,True,1,10)),r)

def test_evidence_forgery_binding_and_finalization():
    _,_,task,_=make(); art=evidence(task); resolver=EvidenceResolver((art,))
    assert resolver.resolve(evidence_id="e",task=task,required_kind="TASK_INPUT")==art
    with pytest.raises(InstitutionError):
        EvidenceResolver((replace(art,content_hash="0"*64),)).resolve(evidence_id="e",task=task,required_kind="TASK_INPUT")
    with pytest.raises(InstitutionError): resolver.resolve(evidence_id="missing",task=task,required_kind="TASK_INPUT")
    with pytest.raises(InstitutionError): resolver.resolve(evidence_id="e",task=replace(task,task_id="other"),required_kind="TASK_INPUT")
    with pytest.raises(InstitutionError): resolver.resolve(evidence_id="e",task=task,required_kind="TASK_INPUT",require_finalized_economic=True)

def test_wrong_but_well_hashed_rejected_and_correct_accepted():
    _,r,t,o=make(); d=allocate(t,o,r); ev=evidence(t); resolver=EvidenceResolver((ev,))
    bad=verify_delivery(task=t,decision=d,delivery=run_service(t,d.winner_id,"SHIRK"),resolver=resolver,evidence_id="e",verified_at=11)
    good=verify_delivery(task=t,decision=d,delivery=run_service(t,d.winner_id,"FULL"),resolver=resolver,evidence_id="e",verified_at=11)
    assert bad.status=="REJECTED" and good.status=="VERIFIED"

def test_unknown_late_and_duplicate_close():
    _,r,t,o=make(); d=allocate(t,o,r); ev=evidence(t); resolver=EvidenceResolver((ev,))
    rec=verify_delivery(task=t,decision=d,delivery=run_service(t,d.winner_id,"UNKNOWN"),resolver=resolver,evidence_id="e",verified_at=11)
    ep=close_episode(task=t,decision=d,receipt=rec); assert ep.terminal_status=="HELD_UNKNOWN" and not ep.closed
    late=replace(run_service(t,d.winner_id),delivered_at=21)
    lr=verify_delivery(task=t,decision=d,delivery=late,resolver=resolver,evidence_id="e",verified_at=22)
    closed=close_episode(task=t,decision=d,receipt=lr); assert closed.terminal_status=="LATE" and closed.closed
    with pytest.raises(InstitutionError): close_episode(task=t,decision=d,receipt=lr,prior=closed)

def test_first_price_counterexample_exists():
    rows=enumerate_first_price_deviations(true_cost=5,others=(7,8),reserve=8)
    assert rows==enumerate_first_price_deviations(true_cost=5,others=(7,8),reserve=8)
    assert max(x["gain"] for x in rows)>0

def test_participation_exits_after_subsidy_removed():
    ps=(ProviderProfile("a",7,1),ProviderProfile("b",4,1))
    assert simulate_participation(ps,expected_payment=5,subsidy=3)[0].active
    assert not simulate_participation(ps,expected_payment=5,subsidy=0)[0].active
    assert simulate_participation(ps,expected_payment=5,subsidy=0)[1].active

def test_rule_generation_is_pinned():
    _,r,t,o=make()
    with pytest.raises(InstitutionError): allocate(t,o,replace(r,generation=2))
