from __future__ import annotations
import base64, json
from fractions import Fraction
import pytest
from src.lending_indexer.contracts import ContractError, load_contracts
from src.lending_indexer.decode import decode_fixture_json
from src.lending_indexer.models import *
from src.lending_indexer.risk import assess_maintenance
from src.lending_indexer.snapshot import build_snapshot
from src.lending_indexer.candidates import classify

pytestmark = pytest.mark.unit

def _raw(contract, typ, body, *, owner=None, slot=10, commitment=Commitment.CONFIRMED):
    disc=contract.account_types[typ].discriminator
    data=disc+json.dumps(body,sort_keys=True).encode()
    return RawAccount("Acct111", owner or contract.program_id, data, False, slot, commitment)

def test_manifest_deployments_fail_closed_until_verified():
    contracts=load_contracts()
    assert {c.protocol for c in contracts} == {LendingProtocol.KAMINO, LendingProtocol.MARGINFI}
    for c in contracts:
        assert c.enabled is False
        assert c.disabled_reason and "DISABLED_UNVERIFIED_CONTRACT" in c.disabled_reason
        with pytest.raises(ContractError) as exc: c.require_enabled()
        assert exc.value.reason is ReasonCode.DISABLED_UNVERIFIED_CONTRACT

def test_contract_validation_rejects_legacy_offsets_and_bad_owner():
    c=load_contracts()[0]
    good=_raw(c,"reserve",{"layout_version":c.version})
    c.validate_typed_account("reserve", good)
    with pytest.raises(ContractError) as exc: c.validate_typed_account("reserve", RawAccount("x","legacy",good.data,False,10,Commitment.CONFIRMED))
    assert exc.value.reason is ReasonCode.INVALID_OWNER
    with pytest.raises(ContractError) as exc: c.validate_typed_account("reserve", RawAccount("x",c.program_id,b"not-old-offsets",False,10,Commitment.CONFIRMED))
    assert exc.value.reason is ReasonCode.INVALID_ACCOUNT_SIZE

def test_decode_rejects_disabled_jsonparsed_unknown_and_version_change():
    c=load_contracts()[1]
    acct=_raw(c,"bank",{"layout_version":c.version,"asset_weight":"8/10"})
    with pytest.raises(ContractError) as exc: decode_fixture_json(c,"bank",acct)
    assert exc.value.reason is ReasonCode.DISABLED_UNVERIFIED_CONTRACT
    enabled = c.__class__(**{**{k:getattr(c,k) for k in c.__dataclass_fields__}, "enabled": True})
    decoded=decode_fixture_json(enabled,"bank",acct)
    assert decoded.fields["asset_weight"] == "8/10"
    bad=RawAccount("Acct111",c.program_id,b"[not jsonParsed accepted]",False,10,Commitment.CONFIRMED)
    with pytest.raises(ContractError): decode_fixture_json(enabled,"bank",bad)
    changed=_raw(c,"bank",{"layout_version":"future"})
    with pytest.raises(ContractError) as exc: decode_fixture_json(enabled,"bank",changed)
    assert exc.value.reason is ReasonCode.INVALID_LAYOUT_VERSION

def test_snapshot_closure_rejects_mixed_commitment_and_old_dependency():
    c=load_contracts()[0]; a=_raw(c,"reserve",{"layout_version":c.version}, slot=11)
    snap=build_snapshot(c.protocol,c.deployment_id,10,Commitment.CONFIRMED,"Market",(a,),c.version)
    assert snap.account_set_hash
    with pytest.raises(ValueError, match="mixed commitments"):
        build_snapshot(c.protocol,c.deployment_id,10,Commitment.CONFIRMED,"Market",(RawAccount("a",c.program_id,a.data,False,10,Commitment.FINALIZED),),c.version)
    with pytest.raises(ValueError, match="older"):
        build_snapshot(c.protocol,c.deployment_id,10,Commitment.CONFIRMED,"Market",(RawAccount("a",c.program_id,a.data,False,9,Commitment.CONFIRMED),),c.version)

def test_marginfi_maintenance_health_not_nominal_ratio_or_fake_one():
    ev=RiskEvidence(("h",),"risk",("oracle",),(10,))
    assessment=assess_maintenance("acct", Fraction(95,1), Fraction(100,1), OracleStatus.VALID, ev)
    assert assessment.health == -5
    assert assessment.health_factor == Fraction(19,20)
    snap=LendingSnapshot(LendingProtocol.MARGINFI,"dep",10,Commitment.CONFIRMED,"group",(),"snap","v")
    cand=classify(LendingProtocol.MARGINFI,"dep",snap,assessment,(),LiquidationConstraints(None,None,None))
    assert cand.status is CandidateStatus.POTENTIALLY_LIQUIDATABLE
    assert "profitable" not in repr(cand).lower()
    zero=assess_maintenance("acct", Fraction(10), Fraction(0), OracleStatus.VALID, ev)
    assert zero.health_factor is None

def test_oracle_rejection_excludes_not_healthy_default():
    ev=RiskEvidence(("h",),"risk",("oracle",),(10,))
    a=assess_maintenance("acct", Fraction(1000), Fraction(1), OracleStatus.STALE, ev)
    snap=LendingSnapshot(LendingProtocol.KAMINO,"dep",10,Commitment.CONFIRMED,"market",(),"snap","v")
    cand=classify(LendingProtocol.KAMINO,"dep",snap,a,(),LiquidationConstraints(None,None,None),ReasonCode.ORACLE_STALE)
    assert cand.status is CandidateStatus.EXCLUDED
    assert cand.exclusion_reason is ReasonCode.ORACLE_STALE
