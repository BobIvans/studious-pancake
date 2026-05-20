#!/usr/bin/env python3
import os
P = "/Users/ivansbobrovs/Desktop/1solana-coin-signal-engine-main"

# Fix 1: ComputeBudget filter
txb = open(os.path.join(P, "src/ingest/tx_builder.py")).read()
old1 = '''                ix = self._parse_instruction(ix_data)
                
                # Phase 12: Deduplicate Associated Token Account creation'''
new1 = '''                ix = self._parse_instruction(ix_data)
                
                # Filter out Jupiter's ComputeBudget — SVM rejects duplicate CB
                if str(ix.program_id) == "ComputeBudget111111111111111111111111111111":
                    logger.debug("Cut Jupiter ComputeBudget duplicate")
                    continue
                
                # Phase 12: Deduplicate Associated Token Account creation'''
assert old1 in txb, "Fix 1: pattern not found"
txb = txb.replace(old1, new1, 1)
open(os.path.join(P, "src/ingest/tx_builder.py"), "w").write(txb)
print("FIX 1 OK")

# Fix 2: Jupiter URL
lra = open(os.path.join(P, "src/ingest/lst_route_aggregator.py")).read()
old2 = 'https://api.jup.ag/swap/v1/quote'
new2 = 'https://quote-api.jup.ag/v6/quote'
assert old2 in lra, "Fix 2: URL not found"
lra = lra.replace(old2, new2)
open(os.path.join(P, "src/ingest/lst_route_aggregator.py"), "w").write(lra)
print("FIX 2 OK")

# Fix 3: CU_PROFILES
txb = open(os.path.join(P, "src/ingest/tx_builder.py")).read()
old3 = '"xstock_oracle_lag":    400_000,'
new3 = '"xstock_oracle_lag":    800_000,'
assert old3 in txb, "Fix 3: CU not found"
txb = txb.replace(old3, new3)
open(os.path.join(P, "src/ingest/tx_builder.py"), "w").write(txb)
print("FIX 3 OK")
print("ALL FIXES APPLIED")
