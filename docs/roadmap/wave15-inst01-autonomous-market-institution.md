# Wave 15 INST-01 — Evidence-Service Procurement Arena

First implemented Wave 15 vertical. Research-only and synthetic-only.

## Implemented
- immutable InstitutionSpec + RuleSnapshot generation binding;
- homogeneous ServiceTask / Offer / AllocationDecision;
- posted-price, reverse-first-price and capped critical-price procurement;
- deterministic precommitted tie handling, no-trade, deadline/capacity/budget eligibility;
- semantic EvidenceResolver binding evidence to task/state/rule/kind/rights;
- executable INTEGER_SUM_V1 service plus independent recomputation verifier;
- VERIFIED / REJECTED / LATE / HELD_UNKNOWN and duplicate-close prevention;
- bounded first-price unilateral-deviation counterexample search;
- outside-option participation and subsidy-removal behavior;
- reproducible end-to-end synthetic trace and scope-limited verdict.

## Not claimed
Not all 96 Wave 15 functions. No global IC, coalition proofness, Sybil resistance,
real demand/profit, production readiness, live authorization, signer/wallet/RPC,
external payments, or external qualification.

## Run
```bash
python scripts/verify_wave15_inst01.py
python -m pytest -q tests/research/test_wave15_inst01.py
```

PASS means only finite synthetic INST-01 semantics pass. It never promotes live execution.
