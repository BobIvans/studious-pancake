import json
import pytest
from solders.instruction import Instruction
from solders.pubkey import Pubkey
from src.providers.marginfi import MarginfiFlashLoanProvider, MarginfiRejection, MarginfiRejectionCode, load_marginfi_contract_pin
from src.providers.marginfi.accounts import MarginfiAccountReader, RpcAccount

P = "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA"
G = "4qp6Fx6tnZkY5Wropq9wUYgtFxXKwE6viZxFHg3rdAG8"
MA = "Fk4G5NB5e1NyULQCCpTNLWCmChCW2UbDwpkEofqAiHk2"
AUTH = "11111111111111111111111111111111"
BANK = "HmpMfL8942fYJdwdVdzi7okQCXh6gwX1v6hN1Eks7gbC"
VAULT = "7hQfMh9N7Xmkuzw3jHMqUiEAn1ng4Vr4QtgEwrz5QZc"
VAUTH = "Gv1XxXGm2YQJ7F2JffU9Nc3VkMvLTZxXXyBmvX3TgKcX"
ORACLE = "SysvarC1ock11111111111111111111111111111111"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
ATA1 = "7UX3bG2AvfbbWAC4Wqd9m6mUXtwewfP7btrnvcNSG2h"
ATA2 = "9zHgUoJgGrKh4ZwVgtxYzBYzvD9Jq3qQnF2Y5xp9bzpS"

def enc(pin, name, obj): return pin.account_discriminator(name) + json.dumps(obj, sort_keys=True).encode()
class Rpc:
    def __init__(self, pin, **overrides):
        bank = {"group": G, "mint": USDC, "token_program": TOKEN, "liquidity_vault": VAULT, "liquidity_vault_authority": VAUTH, "oracle_keys": [ORACLE], "operational_state": "operational", "available_liquidity": 2_000_000}
        bank.update(overrides.pop("bank_overrides", {}))
        self.map = {P: RpcAccount(P, "BPFLoaderUpgradeab1e11111111111111111111111", b"", executable=True), G: RpcAccount(G, P, enc(pin, "marginfi_group", {"admin": AUTH})), MA: RpcAccount(MA, P, enc(pin, "marginfi_account", {"group": G, "authority": AUTH, "active_balances": []})), BANK: RpcAccount(BANK, P, enc(pin, "bank", bank))}
    def get_multiple_accounts(self, addresses): return 123, tuple(self.map.get(a) for a in addresses)

def snapshot(pin, **kw): return MarginfiAccountReader(pin, Rpc(pin, **kw)).read(group=G, margin_account=MA, authority=AUTH, bank=BANK, symbol="USDC", amount=1_000)

def test_official_sdk_golden_discriminators_and_instruction_data():
    pin = load_marginfi_contract_pin(); p = MarginfiFlashLoanProvider(pin); s = snapshot(pin)
    pre = p.prepare(snapshot=s, amount=1000, destination_token_account=ATA1, repayment_source_token_account=ATA2, min_final_balance=1010, safety_surplus=10)
    assert bytes(pre.borrow_instruction.data).hex() == "047e74353005d41fe803000000000000"
    assert bytes(pre.repay_instruction.data).hex() == "4fd1acb1de33ad97e80300000000000000"
    assert bytes(pre.end_template.data).hex() == "697cc96a9902089c"
    final = p.finalize(pre, [pre.borrow_instruction, Instruction(Pubkey.default(), b"swap-a", []), Instruction(Pubkey.default(), b"swap-b", []), pre.repay_instruction])
    assert bytes(final.instructions[0].data).hex() == "0e8321dc51bab46b0500000000000000"
    assert final.end_index == 5 and final.instructions[final.end_index] == pre.end_template
    assert str(final.instructions[0].program_id) == P

def test_min_final_balance_rejects_exact_in_without_surplus():
    pin = load_marginfi_contract_pin(); p = MarginfiFlashLoanProvider(pin)
    with pytest.raises(MarginfiRejection) as e: p.prepare(snapshot=snapshot(pin), amount=1000, destination_token_account=ATA1, repayment_source_token_account=ATA2, min_final_balance=999)
    assert e.value.code == MarginfiRejectionCode.MIN_FINAL_BALANCE

def test_sequence_mutation_rejected():
    pin = load_marginfi_contract_pin(); p = MarginfiFlashLoanProvider(pin); pre = p.prepare(snapshot=snapshot(pin), amount=1000, destination_token_account=ATA1, repayment_source_token_account=ATA2, min_final_balance=1000)
    with pytest.raises(MarginfiRejection): p.finalize(pre, [pre.repay_instruction, pre.borrow_instruction])
    with pytest.raises(MarginfiRejection): p.finalize(pre, [pre.borrow_instruction, pre.repay_instruction, pre.end_template])

def test_risk_accounts_are_bytewise_sorted_and_grouped():
    pin = load_marginfi_contract_pin(); p = MarginfiFlashLoanProvider(pin); pre = p.prepare(snapshot=snapshot(pin), amount=1, destination_token_account=ATA1, repayment_source_token_account=ATA2, min_final_balance=1)
    assert pre.risk_accounts == (BANK, ORACLE)
    assert pre.projected_active_balances == (BANK,)

def test_reader_rejects_wrong_owner_disabled_bank_liquidity_token_program():
    pin = load_marginfi_contract_pin()
    for overrides, code in [({"operational_state": "paused"}, MarginfiRejectionCode.BANK_DISABLED), ({"available_liquidity": 1}, MarginfiRejectionCode.INSUFFICIENT_LIQUIDITY), ({"token_program": "TokenzQdBNbLqP5VEhdkAS6EPuSEoHJFpS1234567"}, MarginfiRejectionCode.TOKEN_PROGRAM_MISMATCH)]:
        with pytest.raises(MarginfiRejection) as e: snapshot(pin, bank_overrides=overrides)
        assert e.value.code == code
