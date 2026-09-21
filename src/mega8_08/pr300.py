"""PR-300 / NF-885..888: factual immutable audit/compliance exports."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega808Error, Result, require_nonnegative, result, stable_hash


def export_audit_records(records: Sequence[Mapping[str,object]], *, schema_version: str) -> Result:
    if not schema_version:
        raise Mega808Error("SCHEMA_VERSION_REQUIRED")
    rows=tuple(dict(row) for row in records)
    return result("export_audit_records", {"schema_version":schema_version,"records":rows,"record_count":len(rows),"export_hash":stable_hash("audit-export",rows)})


def compute_tax_lot_ledger(trades: Sequence[Mapping[str,object]], *, method: str="FIFO") -> Result:
    if method not in {"FIFO","LIFO","SPECIFIC_ID"}:
        raise Mega808Error("LOT_METHOD_UNSUPPORTED")
    lots=[]
    for trade in trades:
        qty=require_nonnegative(int(trade.get("quantity",0)),"quantity")
        cost=require_nonnegative(int(trade.get("cost",0)),"cost")
        lots.append((str(trade.get("asset","")),qty,cost,str(trade.get("id",""))))
    return result("compute_tax_lot_ledger", {"method":method,"lots":tuple(lots),"legal_or_tax_conclusion":False})


def enforce_record_retention(*, record_age_days: int, retention_days: int, legal_hold: bool=False) -> Result:
    age=require_nonnegative(record_age_days,"record_age_days")
    retain=require_nonnegative(retention_days,"retention_days")
    disposition="RETAIN" if legal_hold or age<retain else "ELIGIBLE_FOR_EXPIRY"
    return result("enforce_record_retention", {"record_age_days":age,"retention_days":retain,"legal_hold":legal_hold,"disposition":disposition})


def verify_compliance_export(export_payload: Mapping[str,object], *, expected_hash: str, required_fields: Sequence[str]) -> Result:
    actual=stable_hash("audit-export",export_payload.get("records",()))
    missing=tuple(field for field in required_fields if field not in export_payload)
    blockers=()
    if actual!=expected_hash: blockers+=("EXPORT_HASH_MISMATCH",)
    if missing: blockers+=("EXPORT_INCOMPLETE",)
    return result("verify_compliance_export", {"actual_hash":actual,"expected_hash":expected_hash,"missing_fields":missing,"verified":not blockers}, status="OK" if not blockers else "BLOCKED", blockers=blockers)
