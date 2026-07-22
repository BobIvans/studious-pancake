from __future__ import annotations
import hashlib, json, re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

HEX64=re.compile(r'^[0-9a-f]{64}$')
IMG=re.compile(r'^sha256:[0-9a-f]{64}$')

class Stage(str,Enum):
    ARTIFACT_VERIFIED='artifact_verified'; SHADOW_DEPLOYED='shadow_deployed'; PAPER_READY='paper_ready'; BOUNDED_CANARY='bounded_canary'; LIMITED_LIVE='limited_live'; COMPLETE='complete'; ROLLBACK='rollback'
class Decision(str,Enum):
    PROMOTE='PROMOTE'; FREEZE='FREEZE'; ROLLBACK_REQUIRED='ROLLBACK_REQUIRED'; COMPLETE='COMPLETE'
class Reason(str,Enum):
    INVALID_RELEASE_IDENTITY='INVALID_RELEASE_IDENTITY'; RELEASE_REVOKED='RELEASE_REVOKED'; CRITICAL_VULNERABILITY='CRITICAL_VULNERABILITY'; SECURITY_FLOOR_VIOLATION='SECURITY_FLOOR_VIOLATION'; MISSING_PREVIOUS_KNOWN_GOOD='MISSING_PREVIOUS_KNOWN_GOOD'; DESIRED_OBSERVED_MISMATCH='DESIRED_OBSERVED_MISMATCH'; DATABASE_INCOMPATIBLE='DATABASE_INCOMPATIBLE'; POLICY_MISMATCH='POLICY_MISMATCH'; HEALTH_TRIGGER='HEALTH_TRIGGER'; OBSERVATION_WINDOW_NOT_MET='OBSERVATION_WINDOW_NOT_MET'; HUMAN_APPROVAL_MISSING='HUMAN_APPROVAL_MISSING'; ROLLBACK_BUNDLE_INCOMPLETE='ROLLBACK_BUNDLE_INCOMPLETE'; ROLLBACK_TARGET_UNSAFE='ROLLBACK_TARGET_UNSAFE'; MULTIPLE_SUBMISSION_GENERATIONS='MULTIPLE_SUBMISSION_GENERATIONS'; OLD_WORKLOAD_STILL_ALIVE='OLD_WORKLOAD_STILL_ALIVE'; NON_DURABLE_HISTORY='NON_DURABLE_HISTORY'; FORBIDDEN_DEPLOY_SURFACE='FORBIDDEN_DEPLOY_SURFACE'

def canon(v:Any)->str:
    def n(x:Any)->Any:
        if isinstance(x,float): raise TypeError('floats not accepted in release identity')
        if isinstance(x,Enum): return x.value
        if isinstance(x,tuple): return [n(y) for y in x]
        if isinstance(x,list): return [n(y) for y in x]
        if isinstance(x,Mapping): return {str(k):n(y) for k,y in sorted(x.items())}
        if hasattr(x,'to_dict'): return n(x.to_dict())
        return x
    return json.dumps(n(v),sort_keys=True,separators=(',',':'),ensure_ascii=False)

def stable_hash(v:Any,*,domain:str)->str:
    return hashlib.sha256((domain+':'+canon(v)).encode()).hexdigest()

def is_hash(v:str)->bool: return bool(HEX64.match(v))
def is_img(v:str)->bool: return bool(IMG.match(v))

@dataclass(frozen=True)
class Failure:
    reason:Reason; detail:str

@dataclass(frozen=True)
class ProductionRelease:
    release_id:str; release_rank:int; code_commit:str; image_digest:str; wheel_hashes:tuple[str,...]; policy_bundle_hash:str; config_schema_version:str; db_schema_version:str; event_schema_versions:tuple[str,...]; evidence_schema_versions:tuple[str,...]; program_asset_provider_pins_hash:str; signer_version:str; deployment_manifest_hash:str; sandbox_profile_hash:str; egress_profile_hash:str; previous_known_good_release_id:str|None; compatibility_window:tuple[str,...]; minimum_security_floor_rank:int=0; revoked:bool=False; critical_vulnerabilities:tuple[str,...]=()
    def to_dict(self)->dict[str,Any]: return self.__dict__.copy()
    @property
    def identity_hash(self)->str: return stable_hash(self.to_dict(),domain='flashloan-bot/production-release')

@dataclass(frozen=True)
class DesiredObservedState:
    desired_release_id:str; observed_release_id:str|None; desired_image_digest:str; observed_image_digest:str|None; desired_policy_bundle_hash:str; observed_policy_bundle_hash:str|None; desired_db_schema_version:str; observed_db_schema_version:str|None; desired_signer_version:str; observed_signer_version:str|None; deployment_generation:int; active_traffic_generation:int; active_submission_generations:int; old_workload_terminated:bool
    def mismatches(self)->tuple[str,...]:
        out=[]
        for n in ('release_id','image_digest','policy_bundle_hash','db_schema_version','signer_version'):
            if getattr(self,'desired_'+n)!=getattr(self,'observed_'+n): out.append(n)
        return tuple(out)
    def to_dict(self)->dict[str,Any]: return self.__dict__.copy()

@dataclass(frozen=True)
class StagePlan:
    stage:Stage; min_observation_seconds:int; rollback_target_release_id:str; human_approvals_required:int; allow_submissions:bool=False
    def to_dict(self)->dict[str,Any]: return {'stage':self.stage.value,'min_observation_seconds':self.min_observation_seconds,'rollback_target_release_id':self.rollback_target_release_id,'human_approvals_required':self.human_approvals_required,'allow_submissions':self.allow_submissions}

@dataclass(frozen=True)
class RollbackBundle:
    target_release_id:str; previous_image_digest:str; previous_policy_bundle_hash:str; compatible_db_schema_versions:tuple[str,...]; migration_path_hash:str; signer_compatibility_hash:str; required_evidence_hashes:tuple[str,...]; old_binary_compatibility_tested:bool; rpo_statement_hash:str
    def complete(self)->bool:
        return all((self.target_release_id,is_img(self.previous_image_digest),is_hash(self.previous_policy_bundle_hash),is_hash(self.migration_path_hash),is_hash(self.signer_compatibility_hash),self.required_evidence_hashes,self.old_binary_compatibility_tested,is_hash(self.rpo_statement_hash))) and all(is_hash(x) for x in self.required_evidence_hashes)
    def to_dict(self)->dict[str,Any]: return self.__dict__.copy()

@dataclass(frozen=True)
class RolloutObservation:
    current_stage:Stage; started_s:int; now_s:int; metrics_ok:bool; readiness_ok:bool; no_unreconciled_attempts:bool; no_wallet_discrepancy:bool; no_provider_drift:bool; signer_matches:bool; db_migration_ok:bool; resource_ok:bool; alerting_ok:bool; security_scan_ok:bool; human_approvals:int; history_durable:bool; rollback_drill_rto_met:bool; triggers:tuple[str,...]=()
    @property
    def age_s(self)->int: return max(0,self.now_s-self.started_s)
    def bad(self)->tuple[str,...]:
        checks={'metrics':self.metrics_ok,'readiness':self.readiness_ok,'attempts':self.no_unreconciled_attempts,'wallet':self.no_wallet_discrepancy,'provider':self.no_provider_drift,'signer':self.signer_matches,'db':self.db_migration_ok,'resource':self.resource_ok,'alerting':self.alerting_ok,'security':self.security_scan_ok}
        return self.triggers+tuple(k for k,v in checks.items() if not v)
    def to_dict(self)->dict[str,Any]: return self.__dict__|{'current_stage':self.current_stage.value}

@dataclass(frozen=True)
class RolloutEvent:
    release_id:str; stage:Stage; decision:Decision; evidence_hash:str; previous_event_hash:str|None=None
    @property
    def event_hash(self)->str: return stable_hash({'release':self.release_id,'stage':self.stage.value,'decision':self.decision.value,'evidence':self.evidence_hash,'previous':self.previous_event_hash},domain='flashloan-bot/rollout-event')

@dataclass(frozen=True)
class Report:
    release_id:str; stage:Stage; decision:Decision; failures:tuple[Failure,...]; freeze_new_submissions:bool; rollback_target_release_id:str|None; rollout_event:RolloutEvent; report_hash:str=field(init=False)
    def __post_init__(self)->None: object.__setattr__(self,'report_hash',stable_hash({'release':self.release_id,'stage':self.stage.value,'decision':self.decision.value,'failures':[(f.reason.value,f.detail) for f in self.failures],'event':self.rollout_event.event_hash},domain='flashloan-bot/release-controller-report'))
    @property
    def can_promote(self)->bool: return self.decision in (Decision.PROMOTE,Decision.COMPLETE)
    @property
    def live_allowed(self)->bool: return False

def validate_release(r:ProductionRelease)->list[Failure]:
    f=[]
    for name in ('code_commit','policy_bundle_hash','program_asset_provider_pins_hash','deployment_manifest_hash','sandbox_profile_hash','egress_profile_hash'):
        if not is_hash(getattr(r,name)): f.append(Failure(Reason.INVALID_RELEASE_IDENTITY,name))
    if not is_img(r.image_digest) or not r.wheel_hashes or not all(is_hash(x) for x in r.wheel_hashes): f.append(Failure(Reason.INVALID_RELEASE_IDENTITY,'image/wheel'))
    if not r.event_schema_versions or not r.evidence_schema_versions: f.append(Failure(Reason.INVALID_RELEASE_IDENTITY,'schemas'))
    if r.revoked: f.append(Failure(Reason.RELEASE_REVOKED,r.release_id))
    if r.critical_vulnerabilities: f.append(Failure(Reason.CRITICAL_VULNERABILITY,','.join(r.critical_vulnerabilities)))
    if r.release_rank<r.minimum_security_floor_rank: f.append(Failure(Reason.SECURITY_FLOOR_VIOLATION,'below floor'))
    return f

def evaluate_release_controller(*,release:ProductionRelease,known_releases:Sequence[ProductionRelease],state:DesiredObservedState,stage_plan:StagePlan,rollback_bundle:RollbackBundle,observation:RolloutObservation,previous_event_hash:str|None=None)->Report:
    known={r.release_id:r for r in known_releases}; failures=validate_release(release)
    if release.previous_known_good_release_id is None: failures.append(Failure(Reason.MISSING_PREVIOUS_KNOWN_GOOD,'missing'))
    if state.desired_release_id!=release.release_id or state.mismatches(): failures.append(Failure(Reason.DESIRED_OBSERVED_MISMATCH,','.join(state.mismatches())))
    if state.observed_db_schema_version not in release.compatibility_window: failures.append(Failure(Reason.DATABASE_INCOMPATIBLE,'observed db outside window'))
    if state.active_submission_generations>1 or (stage_plan.allow_submissions and state.active_submission_generations!=1): failures.append(Failure(Reason.MULTIPLE_SUBMISSION_GENERATIONS,str(state.active_submission_generations)))
    if not state.old_workload_terminated and state.active_traffic_generation!=state.deployment_generation: failures.append(Failure(Reason.OLD_WORKLOAD_STILL_ALIVE,'split traffic'))
    if not observation.history_durable: failures.append(Failure(Reason.NON_DURABLE_HISTORY,'history'))
    if observation.bad(): failures.append(Failure(Reason.HEALTH_TRIGGER,','.join(observation.bad())))
    if observation.age_s<stage_plan.min_observation_seconds: failures.append(Failure(Reason.OBSERVATION_WINDOW_NOT_MET,str(observation.age_s)))
    if observation.human_approvals<stage_plan.human_approvals_required: failures.append(Failure(Reason.HUMAN_APPROVAL_MISSING,str(observation.human_approvals)))
    if not observation.rollback_drill_rto_met or not rollback_bundle.complete(): failures.append(Failure(Reason.ROLLBACK_BUNDLE_INCOMPLETE,'rollback evidence'))
    target=known.get(rollback_bundle.target_release_id)
    if target is None: failures.append(Failure(Reason.ROLLBACK_TARGET_UNSAFE,'unknown target'))
    else:
        failures.extend(validate_release(target))
        if target.release_rank<release.minimum_security_floor_rank: failures.append(Failure(Reason.ROLLBACK_TARGET_UNSAFE,'below floor'))
        if release.db_schema_version not in rollback_bundle.compatible_db_schema_versions: failures.append(Failure(Reason.DATABASE_INCOMPATIBLE,'no rollback path'))
        if rollback_bundle.previous_image_digest!=target.image_digest: failures.append(Failure(Reason.ROLLBACK_TARGET_UNSAFE,'image mismatch'))
        if rollback_bundle.previous_policy_bundle_hash!=target.policy_bundle_hash: failures.append(Failure(Reason.POLICY_MISMATCH,'policy mismatch'))
    rollback_reasons={Reason.HEALTH_TRIGGER,Reason.DESIRED_OBSERVED_MISMATCH,Reason.DATABASE_INCOMPATIBLE,Reason.MULTIPLE_SUBMISSION_GENERATIONS,Reason.OLD_WORKLOAD_STILL_ALIVE}
    if not failures and observation.current_stage==Stage.COMPLETE: decision=Decision.COMPLETE
    elif not failures: decision=Decision.PROMOTE
    elif any(x.reason in rollback_reasons for x in failures): decision=Decision.ROLLBACK_REQUIRED
    else: decision=Decision.FREEZE
    evh=stable_hash({'release':release.identity_hash,'state':state.to_dict(),'plan':stage_plan.to_dict(),'rollback':rollback_bundle.to_dict(),'obs':observation.to_dict(),'failures':[(x.reason.value,x.detail) for x in failures]},domain='flashloan-bot/release-controller-evidence')
    event=RolloutEvent(release.release_id,observation.current_stage,decision,evh,previous_event_hash)
    return Report(release.release_id,observation.current_stage,decision,tuple(failures),bool(failures),rollback_bundle.target_release_id if failures else None,event)

FORBIDDEN=('rollback_to_shadow(','kubectl set image','kubectl rollout restart','image:latest','sendTransaction','Keypair.from_secret_key','Keypair.from_bytes','skipPreflight=true')
def scan_forbidden_release_surface(text:str)->tuple[Failure,...]:
    return tuple(Failure(Reason.FORBIDDEN_DEPLOY_SURFACE,t) for t in FORBIDDEN if t in text)
