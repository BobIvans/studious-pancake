import json, subprocess, sys
from dataclasses import dataclass
import pytest
from src.observability import *
from src.observability.export import export_jsonl
from src.observability.metrics import rejection_funnel, daily_shadow_summary
from src.observability.redaction import sanitize


def test_schema_identity_idempotency_and_projection(tmp_path):
    s=ObservabilityStore(tmp_path/'obs.db')
    e=make_event(event_type=EventType.opportunity_detected, logical_opportunity_id='opp', plan_hash='plan', sequence_no=1, attributes={'latency_ms':10})
    assert s.append(e) is True
    assert s.append(e) is False
    with pytest.raises(ObservabilityError):
        s.append(make_event(event_type=EventType.quote_requested, logical_opportunity_id='opp', plan_hash='plan', sequence_no=1))
    s2=ObservabilityStore(tmp_path/'obs.db')
    assert len(s2.events_for(opportunity_id='opp')) == 1
    assert s2.db.execute('select terminal from opportunity_projection where logical_opportunity_id=?',('opp',)).fetchone()[0] == 0


def test_reason_taxonomy_unknown_and_ambiguous():
    code, ev = classify_exception(RuntimeError('private api_key=secret route exploded'))
    assert code in (ReasonCode.ROUTE_NOT_FOUND, ReasonCode.INTERNAL_UNCLASSIFIED)
    assert 'secret' not in json.dumps(ev)
    assert REASON_REGISTRY[ReasonCode.AMBIGUOUS_SUBMISSION].terminal is False
    namespaces={c.name.split('_')[0] for c in ReasonCode}
    for ns in 'SIGNAL DEDUP QUOTA PROVIDER STALE CONTRACT LIQUIDITY ROUTE VENUE MINT CAPITAL FEE RISK PLAN COMPILE ALT TX CU SIMULATION SUBMISSION JITO RPC BLOCKHASH AMBIGUOUS RECONCILIATION CONFIG DISABLED INTERNAL OBSERVABILITY'.split():
        assert ns in namespaces


def test_pnl_truth_requires_structured_reconciliation():
    with pytest.raises(ValueError):
        make_event(event_type=EventType.simulation_completed, logical_opportunity_id='o', plan_hash='p', sequence_no=1, attributes={'realized_pnl': {'amount_base_units': 1}})
    with pytest.raises(ValueError):
        make_event(event_type=EventType.simulation_completed, logical_opportunity_id='o', plan_hash='p', sequence_no=1, attributes={'simulated_pnl': 0})
    e=make_event(event_type=EventType.balance_reconciled, logical_opportunity_id='o', plan_hash='p', sequence_no=2, attributes={'realized_pnl': {'amount_base_units': 1, 'mint':'So111'}})
    assert e.attributes['realized_pnl']['amount_base_units'] == 1

@dataclass
class SecretBox:
    authorization: str
    nested: dict

def test_redaction_corpus_never_persists_or_exports_secret(tmp_path):
    secret='super_secret_api_key_literal_123'
    payload={'url':f'https://rpc.example/?api_key={secret}','headers':{'Authorization':'Bearer '+secret},'exc':RuntimeError('token='+secret),'bytes':b'wirebytes'*20,'box':SecretBox(secret, {'mnemonic':'seed words '+secret}), 'pubkey':'So11111111111111111111111111111111111111112'}
    clean=sanitize(payload)
    assert secret not in json.dumps(clean)
    assert 'So11111111111111111111111111111111111111112' in json.dumps(clean)
    s=ObservabilityStore(tmp_path/'obs.db')
    s.append(make_event(event_type=EventType.quote_rejected, logical_opportunity_id='opp', plan_hash='p', sequence_no=1, reason_code=ReasonCode.PROVIDER_UNHEALTHY, attributes=payload))
    db_bytes=(tmp_path/'obs.db').read_bytes()
    assert secret.encode() not in db_bytes
    manifest=export_jsonl(s, tmp_path/'export')
    assert secret not in open(manifest['path']).read()


def test_metrics_funnel_and_export_idempotent(tmp_path):
    s=ObservabilityStore(tmp_path/'m.db')
    for i, et in enumerate([EventType.opportunity_detected, EventType.quote_received, EventType.route_planned, EventType.feasibility_rejected],1):
        s.append(make_event(event_type=et, logical_opportunity_id='o', plan_hash='p', sequence_no=i, reason_code=ReasonCode.CAPITAL_INSUFFICIENT if 'rejected' in et.value else None, attributes={'latency_ms': i*10}))
    f=rejection_funnel(s); assert f['stages']['opportunity_detected']==1 and f['not_attempted']==1 and f['latency']['p95_ms']['quote_received']=='N/A'
    assert daily_shadow_summary(s)['simulated_pnl_distribution'] == 'N/A'
    m1=export_jsonl(s,tmp_path/'x')
    first_manifest_count=s.db.execute('select count(*) from export_manifest').fetchone()[0]
    first_authoritative_count=s.db.execute('select count(*) from archive_segment_manifest').fetchone()[0]
    m2=export_jsonl(s,tmp_path/'x')
    second_manifest_count=s.db.execute('select count(*) from export_manifest').fetchone()[0]
    second_authoritative_count=s.db.execute('select count(*) from archive_segment_manifest').fetchone()[0]
    assert m1['checksum']==m2['checksum']
    assert m1['manifest_count'] == 4 and m2['manifest_count'] == 0
    assert first_manifest_count == second_manifest_count == 4
    assert first_authoritative_count == second_authoritative_count == 4


def test_replay_offline_and_digest_divergence(tmp_path):
    db=tmp_path/'r.db'; s=ObservabilityStore(db)
    e=make_event(event_type=EventType.attempt_terminal, logical_opportunity_id='o', plan_hash='p', sequence_no=1, attempt_id='a', outcome=Outcome.ambiguous, reason_code=ReasonCode.AMBIGUOUS_SUBMISSION)
    s.append(e)
    ok=subprocess.run([sys.executable,'-m','src.observability.replay','--db',str(db),'--attempt-id','a','--format','json','--verify'],capture_output=True,text=True)
    assert ok.returncode==0 and 'network_free' in ok.stdout
    with s.db: s.db.execute("update event_log set payload_digest='bad' where attempt_id='a'")
    bad=subprocess.run([sys.executable,'-m','src.observability.replay','--db',str(db),'--attempt-id','a','--verify'],capture_output=True,text=True)
    assert bad.returncode != 0 and 'PAYLOAD_DIGEST_DIVERGENCE' in bad.stdout
