"""Wave 15 INST-01: deterministic research-only service procurement institution.

Bounded homogeneous-service procurement only. No signer, wallet, RPC send,
billing, remote mutation, capital, or release authority.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, is_dataclass
import hashlib, json
from typing import Any, Iterable, Mapping, Sequence

class InstitutionError(ValueError):
    pass

def _money(v:int, code:str)->int:
    if isinstance(v,bool) or not isinstance(v,int) or v<0: raise InstitutionError(code)
    return v

def _nonempty(v:str, code:str)->str:
    if not isinstance(v,str) or not v.strip(): raise InstitutionError(code)
    return v

def _norm(v:Any)->Any:
    if is_dataclass(v) and not isinstance(v,type): return _norm(asdict(v))
    if isinstance(v,Mapping): return {str(k):_norm(x) for k,x in sorted(v.items(),key=lambda p:str(p[0]))}
    if isinstance(v,(tuple,list)): return [_norm(x) for x in v]
    return v

def canonical_json(v:Any)->str:
    return json.dumps(_norm(v),sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)

def canonical_hash(v:Any)->str:
    return hashlib.sha256(canonical_json(v).encode()).hexdigest()

@dataclass(frozen=True,slots=True)
class InstitutionSpec:
    institution_id:str; service_kind:str; settlement_domain:str
    research_only:bool=True; live_effect:bool=False; signer_access:bool=False
    wallet_access:bool=False; remote_governance:bool=False
    def __post_init__(self):
        _nonempty(self.institution_id,"W15_INSTITUTION_ID_REQUIRED")
        _nonempty(self.service_kind,"W15_SERVICE_KIND_REQUIRED")
        _nonempty(self.settlement_domain,"W15_SETTLEMENT_DOMAIN_REQUIRED")
        if not self.research_only: raise InstitutionError("W15_RESEARCH_ONLY_REQUIRED")
        if self.live_effect or self.signer_access or self.wallet_access or self.remote_governance:
            raise InstitutionError("W15_EFFECT_BOUNDARY_VIOLATION")

@dataclass(frozen=True,slots=True)
class RuleSnapshot:
    institution_id:str; generation:int; mechanism:str; reserve:int
    posted_price:int|None; tie_order:tuple[str,...]; effective_at:int
    def __post_init__(self):
        _nonempty(self.institution_id,"W15_RULE_INSTITUTION_REQUIRED")
        if isinstance(self.generation,bool) or not isinstance(self.generation,int) or self.generation<1:
            raise InstitutionError("W15_RULE_GENERATION_INVALID")
        if self.mechanism not in {"POSTED_PRICE","REVERSE_FIRST_PRICE","CAPPED_CRITICAL_PRICE"}:
            raise InstitutionError("W15_MECHANISM_INVALID")
        _money(self.reserve,"W15_RESERVE_INVALID")
        if self.posted_price is not None: _money(self.posted_price,"W15_POSTED_PRICE_INVALID")
        if self.mechanism=="POSTED_PRICE" and self.posted_price is None:
            raise InstitutionError("W15_POSTED_PRICE_REQUIRED")
        if len(set(self.tie_order))!=len(self.tie_order): raise InstitutionError("W15_DUPLICATE_TIE_ID")
        if isinstance(self.effective_at,bool) or not isinstance(self.effective_at,int) or self.effective_at<0:
            raise InstitutionError("W15_EFFECTIVE_AT_INVALID")
    @property
    def rule_hash(self)->str: return canonical_hash(self)

@dataclass(frozen=True,slots=True)
class ServiceTask:
    task_id:str; service_kind:str; payload:tuple[int,...]; budget:int; deadline:int
    opened_at:int; state_hash:str; rule_hash:str; outside_option_cost:int; synthetic:bool=True
    def __post_init__(self):
        _nonempty(self.task_id,"W15_TASK_ID_REQUIRED"); _nonempty(self.service_kind,"W15_TASK_KIND_REQUIRED")
        if not self.payload or any(isinstance(x,bool) or not isinstance(x,int) for x in self.payload):
            raise InstitutionError("W15_TASK_PAYLOAD_INTEGER_REQUIRED")
        _money(self.budget,"W15_TASK_BUDGET_INVALID"); _money(self.outside_option_cost,"W15_OUTSIDE_OPTION_INVALID")
        if any(isinstance(x,bool) or not isinstance(x,int) or x<0 for x in (self.deadline,self.opened_at)):
            raise InstitutionError("W15_TASK_CLOCK_INVALID")
        if self.deadline<self.opened_at: raise InstitutionError("W15_DEADLINE_BEFORE_OPEN")
        _nonempty(self.state_hash,"W15_STATE_HASH_REQUIRED"); _nonempty(self.rule_hash,"W15_TASK_RULE_HASH_REQUIRED")

@dataclass(frozen=True,slots=True)
class Offer:
    provider_id:str; task_id:str; bid:int; eligible:bool; capacity:int; expected_finish:int
    def __post_init__(self):
        _nonempty(self.provider_id,"W15_PROVIDER_ID_REQUIRED"); _nonempty(self.task_id,"W15_OFFER_TASK_REQUIRED")
        _money(self.bid,"W15_BID_INVALID"); _money(self.capacity,"W15_CAPACITY_INVALID")
        if isinstance(self.expected_finish,bool) or not isinstance(self.expected_finish,int) or self.expected_finish<0:
            raise InstitutionError("W15_EXPECTED_FINISH_INVALID")

@dataclass(frozen=True,slots=True)
class AllocationDecision:
    task_id:str; rule_hash:str; mechanism:str; winner_id:str|None; payment:int|None
    status:str; eligible_offer_hashes:tuple[str,...]
    @property
    def decision_hash(self)->str: return canonical_hash(self)

@dataclass(frozen=True,slots=True)
class EvidenceArtifact:
    evidence_id:str; task_id:str; state_hash:str; rule_hash:str; artifact_kind:str
    payload:Mapping[str,Any]; rights_scope:str; finalized_economic:bool; content_hash:str
    @classmethod
    def build(cls,*,evidence_id:str,task_id:str,state_hash:str,rule_hash:str,artifact_kind:str,
              payload:Mapping[str,Any],rights_scope:str="research",finalized_economic:bool=False):
        body={"evidence_id":evidence_id,"task_id":task_id,"state_hash":state_hash,"rule_hash":rule_hash,
              "artifact_kind":artifact_kind,"payload":payload,"rights_scope":rights_scope,
              "finalized_economic":finalized_economic}
        return cls(content_hash=canonical_hash(body),**body)

class EvidenceResolver:
    def __init__(self, artifacts:Iterable[EvidenceArtifact]): self._items={x.evidence_id:x for x in artifacts}
    def resolve(self,*,evidence_id:str,task:ServiceTask,required_kind:str,require_finalized_economic:bool=False):
        a=self._items.get(evidence_id)
        if a is None: raise InstitutionError("W15_EVIDENCE_NOT_FOUND")
        expected=canonical_hash({"evidence_id":a.evidence_id,"task_id":a.task_id,"state_hash":a.state_hash,
          "rule_hash":a.rule_hash,"artifact_kind":a.artifact_kind,"payload":a.payload,
          "rights_scope":a.rights_scope,"finalized_economic":a.finalized_economic})
        if expected!=a.content_hash: raise InstitutionError("W15_EVIDENCE_HASH_MISMATCH")
        if a.task_id!=task.task_id: raise InstitutionError("W15_EVIDENCE_TASK_MISMATCH")
        if a.state_hash!=task.state_hash: raise InstitutionError("W15_EVIDENCE_STATE_MISMATCH")
        if a.rule_hash!=task.rule_hash: raise InstitutionError("W15_EVIDENCE_RULE_MISMATCH")
        if a.artifact_kind!=required_kind: raise InstitutionError("W15_EVIDENCE_KIND_MISMATCH")
        if a.rights_scope!="research": raise InstitutionError("W15_EVIDENCE_RIGHTS_REJECTED")
        if require_finalized_economic and not a.finalized_economic: raise InstitutionError("W15_EVIDENCE_NOT_FINALIZED")
        return a

def _eligible(task:ServiceTask, offers:Sequence[Offer], rule:RuleSnapshot)->list[Offer]:
    seen=set(); out=[]
    for o in offers:
        if o.task_id!=task.task_id or not o.eligible: continue
        if o.provider_id in seen: raise InstitutionError("W15_DUPLICATE_PROVIDER_OFFER")
        seen.add(o.provider_id)
        if o.capacity<1 or o.expected_finish>task.deadline or o.bid>rule.reserve or o.bid>task.budget: continue
        out.append(o)
    return out

def _rank(pid:str,rule:RuleSnapshot):
    try:return (rule.tie_order.index(pid),pid)
    except ValueError:return (len(rule.tie_order),pid)

def allocate(task:ServiceTask,offers:Sequence[Offer],rule:RuleSnapshot)->AllocationDecision:
    if task.rule_hash!=rule.rule_hash: raise InstitutionError("W15_TASK_RULE_SNAPSHOT_MISMATCH")
    e=_eligible(task,offers,rule); hashes=tuple(sorted(canonical_hash(x) for x in e))
    if not e:return AllocationDecision(task.task_id,rule.rule_hash,rule.mechanism,None,None,"NO_TRADE",hashes)
    if rule.mechanism=="POSTED_PRICE":
        price=rule.posted_price; assert price is not None
        candidates=[x for x in e if x.bid<=price]
        if price>task.budget or price>rule.reserve or not candidates:
            return AllocationDecision(task.task_id,rule.rule_hash,rule.mechanism,None,None,"NO_TRADE",hashes)
        winner=min(candidates,key=lambda x:_rank(x.provider_id,rule)); payment=price
    else:
        ranked=sorted(e,key=lambda x:(x.bid,_rank(x.provider_id,rule))); winner=ranked[0]
        payment=winner.bid if rule.mechanism=="REVERSE_FIRST_PRICE" else (rule.reserve if len(ranked)==1 else min(rule.reserve,ranked[1].bid))
    if payment>task.budget: raise InstitutionError("W15_PAYMENT_OVER_BUDGET")
    return AllocationDecision(task.task_id,rule.rule_hash,rule.mechanism,winner.provider_id,payment,"AWARDED",hashes)

@dataclass(frozen=True,slots=True)
class Delivery:
    task_id:str; provider_id:str; result:int|None; delivered_at:int; effort:str

def run_service(task:ServiceTask,provider_id:str,effort:str="FULL")->Delivery:
    if task.service_kind!="INTEGER_SUM_V1": raise InstitutionError("W15_UNSUPPORTED_SERVICE_KIND")
    if effort=="FULL": result=sum(task.payload)
    elif effort=="SHIRK": result=sum(task.payload[:-1])
    elif effort=="UNKNOWN": result=None
    else: raise InstitutionError("W15_EFFORT_INVALID")
    return Delivery(task.task_id,provider_id,result,task.opened_at+1,effort)

@dataclass(frozen=True,slots=True)
class VerificationReceipt:
    task_id:str; provider_id:str; decision_hash:str; status:str; expected_result:int|None
    observed_result:int|None; verified_at:int; evidence_id:str
    @property
    def receipt_hash(self)->str:return canonical_hash(self)

def verify_delivery(*,task:ServiceTask,decision:AllocationDecision,delivery:Delivery,
                    resolver:EvidenceResolver,evidence_id:str,verified_at:int)->VerificationReceipt:
    if decision.status!="AWARDED" or decision.winner_id is None: raise InstitutionError("W15_VERIFY_WITHOUT_AWARD")
    if delivery.task_id!=task.task_id or delivery.provider_id!=decision.winner_id:
        raise InstitutionError("W15_DELIVERY_BINDING_MISMATCH")
    resolver.resolve(evidence_id=evidence_id,task=task,required_kind="TASK_INPUT")
    expected=sum(task.payload) if task.service_kind=="INTEGER_SUM_V1" else None
    status="HELD_UNKNOWN" if delivery.result is None else "LATE" if delivery.delivered_at>task.deadline else "REJECTED" if delivery.result!=expected else "VERIFIED"
    return VerificationReceipt(task.task_id,delivery.provider_id,decision.decision_hash,status,expected,delivery.result,verified_at,evidence_id)

@dataclass(frozen=True,slots=True)
class InstitutionEpisode:
    task_id:str; rule_hash:str; decision_hash:str; receipt_hash:str|None; terminal_status:str; closed:bool

def close_episode(*,task:ServiceTask,decision:AllocationDecision,receipt:VerificationReceipt|None,prior:InstitutionEpisode|None=None):
    if prior is not None and prior.closed: raise InstitutionError("W15_DUPLICATE_CLOSE")
    if decision.status=="NO_TRADE": return InstitutionEpisode(task.task_id,task.rule_hash,decision.decision_hash,None,"NO_TRADE",True)
    if receipt is None:return InstitutionEpisode(task.task_id,task.rule_hash,decision.decision_hash,None,"HELD_UNKNOWN",False)
    if receipt.status=="HELD_UNKNOWN":return InstitutionEpisode(task.task_id,task.rule_hash,decision.decision_hash,receipt.receipt_hash,"HELD_UNKNOWN",False)
    return InstitutionEpisode(task.task_id,task.rule_hash,decision.decision_hash,receipt.receipt_hash,receipt.status,True)

def _fp_utility(cost:int,bid:int,others:Sequence[int],reserve:int)->int:
    if bid>reserve or any(x<bid for x in others):return 0
    return bid-cost

def enumerate_first_price_deviations(*,true_cost:int,others:Sequence[int],reserve:int):
    _money(true_cost,"W15_TRUE_COST_INVALID"); _money(reserve,"W15_RESERVE_INVALID")
    for x in others:_money(x,"W15_OTHER_BID_INVALID")
    truthful=_fp_utility(true_cost,true_cost,others,reserve); rows=[]
    for bid in range(reserve+1):
        u=_fp_utility(true_cost,bid,others,reserve)
        if u>truthful:rows.append({"true_cost":true_cost,"truthful_bid":true_cost,"deviation_bid":bid,"gain":u-truthful})
    return tuple(rows)

@dataclass(frozen=True,slots=True)
class ProviderProfile:
    provider_id:str; cost:int; outside_option:int; active:bool=True
    def __post_init__(self):
        _nonempty(self.provider_id,"W15_PROFILE_PROVIDER_REQUIRED"); _money(self.cost,"W15_PROFILE_COST_INVALID"); _money(self.outside_option,"W15_PROFILE_OUTSIDE_INVALID")

def simulate_participation(providers:Sequence[ProviderProfile],*,expected_payment:int,subsidy:int=0):
    _money(expected_payment,"W15_EXPECTED_PAYMENT_INVALID"); _money(subsidy,"W15_SUBSIDY_INVALID")
    return tuple(ProviderProfile(p.provider_id,p.cost,p.outside_option,expected_payment+subsidy-p.cost>=p.outside_option) for p in providers)

@dataclass(frozen=True,slots=True)
class InstitutionVerdict:
    status:str; primary_metric_cost_per_accepted_service:int|None; accepted_services:int
    total_resource_cost:int; client_utility:int|None; counterexamples:int
    synthetic_only:bool=True; production_ready:bool=False; live_authorized:bool=False

def run_inst01_demo(mechanism:str="CAPPED_CRITICAL_PRICE"):
    spec=InstitutionSpec("inst-01","INTEGER_SUM_V1","SYNTHETIC_RESEARCH")
    rule=RuleSnapshot(spec.institution_id,1,mechanism,8,6 if mechanism=="POSTED_PRICE" else None,("p1","p2","p3"),100)
    task=ServiceTask("task-1",spec.service_kind,(3,5,8),8,110,101,canonical_hash({"payload":[3,5,8]}),rule.rule_hash,9)
    offers=(Offer("p1",task.task_id,5,True,1,105),Offer("p2",task.task_id,7,True,1,106),Offer("p3",task.task_id,8,True,1,107))
    decision=allocate(task,offers,rule)
    if decision.winner_id is None:
        verdict=InstitutionVerdict("INCONCLUSIVE",None,0,0,None,0)
        return {"spec":spec,"rule":rule,"task":task,"decision":decision,"verdict":verdict}
    delivery=run_service(task,decision.winner_id)
    ev=EvidenceArtifact.build(evidence_id="task-input-1",task_id=task.task_id,state_hash=task.state_hash,rule_hash=task.rule_hash,artifact_kind="TASK_INPUT",payload={"payload":list(task.payload)})
    receipt=verify_delivery(task=task,decision=decision,delivery=delivery,resolver=EvidenceResolver((ev,)),evidence_id=ev.evidence_id,verified_at=108)
    episode=close_episode(task=task,decision=decision,receipt=receipt)
    accepted=int(receipt.status=="VERIFIED"); payment=decision.payment or 0; total=payment+1
    verdict=InstitutionVerdict("PASS_FINITE_SYNTHETIC" if accepted else "FAIL",total if accepted else None,accepted,total,task.outside_option_cost-total if accepted else 0,len(enumerate_first_price_deviations(true_cost=5,others=(7,8),reserve=8)))
    return {"spec":spec,"rule":rule,"task":task,"offers":offers,"decision":decision,"delivery":delivery,"receipt":receipt,"episode":episode,"verdict":verdict,"trace_hash":canonical_hash((spec,rule,task,offers,decision,delivery,receipt,episode,verdict))}
