from src.execution.transaction_simulator import TransactionSimulator
from src.execution.shadow import CanonicalSimulator

def test_transaction_simulator_is_canonical_facade():
    assert issubclass(TransactionSimulator, CanonicalSimulator)
