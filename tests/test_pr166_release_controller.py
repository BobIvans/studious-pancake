from dataclasses import replace
from src.release_controller_pr166 import *

H='a'*64; H2='b'*64; H3='c'*64; IMG='sha256:'+'1'*64; IMG2='sha256:'+'2'*64

def rel(id='rel-2',rank=2,prev='rel-1'):
    return ProductionRelease(id,rank,H,IMG,(H,H2),H,'cfg.v1','db.v2',('ev.v1',),('evid.v1',),H2,'signer.v1',H3,H,H2,prev,('db.v1','db.v2'),1)
def old(): return rel('rel-1',1,None)
def state():
    r=rel(); return DesiredObservedState(r.release_id,r.release_id,r.image_digest,r.image_digest,r.policy_bundle_hash,r.policy_bundle_hash,r.db_schema_version,r.db_schema_version,r.signer_version,r.signer_version,7,7,1,True)
def plan(stage=Stage.PAPER_READY):
    return StagePlan(stage,60,'rel-1',2,stage in (Stage.BOUNDED_CANARY,Stage.LIMITED_LIVE))
def rb():
    o=old(); return RollbackBundle(o.release_id,o.image_digest,o.policy_bundle_hash,('db.v1','db.v2'),H,H2,(H,H3),True,H3)
def obs(stage=Stage.PAPER_READY):
    return RolloutObservation(stage,0,120,True,True,True,True,True,True,True,True,True,True,2,True,True)
def rep(**kw):
    r=kw.pop('release',rel())
    return evaluate_release_controller(release=r,known_releases=kw.pop('known',[old(),r]),state=kw.pop('state',state()),stage_plan=kw.pop('stage_plan',plan()),rollback_bundle=kw.pop('rollback',rb()),observation=kw.pop('observation',obs()),previous_event_hash=kw.pop('previous_event_hash',None))
def reasons(x): return {f.reason for f in x.failures}

def test_clean_promotes_but_live_is_disabled():
    x=rep(); assert x.decision==Decision.PROMOTE and x.can_promote and not x.freeze_new_submissions and not x.live_allowed
def test_release_hash_changes_with_policy():
    assert rel().identity_hash!=replace(rel(),policy_bundle_hash=H2).identity_hash
def test_bad_image_blocks():
    assert Reason.INVALID_RELEASE_IDENTITY in reasons(rep(release=replace(rel(),image_digest='latest')))
def test_revoked_blocks():
    x=rep(release=replace(rel(),revoked=True)); assert Reason.RELEASE_REVOKED in reasons(x) and x.decision==Decision.FREEZE
def test_vulnerability_blocks():
    assert Reason.CRITICAL_VULNERABILITY in reasons(rep(release=replace(rel(),critical_vulnerabilities=('CVE',))))
def test_security_floor_blocks_downgrade():
    assert Reason.SECURITY_FLOOR_VIOLATION in reasons(rep(release=replace(rel(),release_rank=0)))
def test_previous_known_good_required():
    assert Reason.MISSING_PREVIOUS_KNOWN_GOOD in reasons(rep(release=rel(prev=None)))
def test_desired_observed_mismatch_requests_rollback():
    x=rep(state=replace(state(),observed_image_digest=IMG2)); assert Reason.DESIRED_OBSERVED_MISMATCH in reasons(x) and x.decision==Decision.ROLLBACK_REQUIRED
def test_db_schema_compatibility_required():
    assert Reason.DATABASE_INCOMPATIBLE in reasons(rep(state=replace(state(),observed_db_schema_version='db.v99')))
def test_single_submission_generation_required():
    assert Reason.MULTIPLE_SUBMISSION_GENERATIONS in reasons(rep(state=replace(state(),active_submission_generations=2)))
def test_old_workload_must_terminate():
    assert Reason.OLD_WORKLOAD_STILL_ALIVE in reasons(rep(state=replace(state(),active_traffic_generation=6,old_workload_terminated=False)))
def test_observation_window_required():
    assert Reason.OBSERVATION_WINDOW_NOT_MET in reasons(rep(observation=replace(obs(),now_s=30)))
def test_human_approvals_required():
    assert Reason.HUMAN_APPROVAL_MISSING in reasons(rep(observation=replace(obs(),human_approvals=1)))
def test_health_trigger_requests_rollback():
    x=rep(observation=replace(obs(),no_wallet_discrepancy=False)); assert Reason.HEALTH_TRIGGER in reasons(x) and x.decision==Decision.ROLLBACK_REQUIRED
def test_rollback_bundle_must_be_complete():
    assert Reason.ROLLBACK_BUNDLE_INCOMPLETE in reasons(rep(rollback=replace(rb(),old_binary_compatibility_tested=False)))
def test_rollback_target_cannot_be_revoked():
    assert Reason.RELEASE_REVOKED in reasons(rep(known=[replace(old(),revoked=True),rel()]))
def test_rollback_policy_must_match_target():
    assert Reason.POLICY_MISMATCH in reasons(rep(rollback=replace(rb(),previous_policy_bundle_hash=H2)))
def test_history_must_be_durable():
    assert Reason.NON_DURABLE_HISTORY in reasons(rep(observation=replace(obs(),history_durable=False)))
def test_complete_stage_can_complete():
    assert rep(stage_plan=plan(Stage.COMPLETE),observation=obs(Stage.COMPLETE)).decision==Decision.COMPLETE
def test_report_hash_stable_and_changes_with_evidence():
    assert rep().report_hash==rep().report_hash
    assert rep().report_hash!=rep(observation=replace(obs(),now_s=121)).report_hash
def test_event_chain_uses_previous_hash():
    a=rep(); b=rep(previous_event_hash=a.rollout_event.event_hash); assert a.rollout_event.event_hash!=b.rollout_event.event_hash and b.rollout_event.previous_event_hash==a.rollout_event.event_hash
def test_static_scan_flags_bypass_tokens():
    f=scan_forbidden_release_surface('rollback_to_shadow()\nKeypair.from_bytes(x)\nsendTransaction'); assert len(f)==3 and {x.reason for x in f}=={Reason.FORBIDDEN_DEPLOY_SURFACE}
