from tools.mpr2606.pilot import classify


def _counts(*, tests=1, failures=0, errors=0, skipped=0):
    return {"tests": tests, "failures": failures, "errors": errors, "skipped": skipped}


def test_zero_tests_is_not_a_kill_even_with_zero_exit() -> None:
    assert classify(0, _counts(tests=0)) == "NOT_COVERED"


def test_assertion_failure_is_killed() -> None:
    assert classify(1, _counts(failures=1)) == "KILLED_BY_ASSERTION"


def test_collection_or_setup_error_is_inconclusive() -> None:
    assert classify(1, _counts(errors=1)) == "IMPORT_COLLECTION_ERROR"


def test_all_skipped_is_not_a_kill() -> None:
    assert classify(0, _counts(tests=2, skipped=2)) == "SKIPPED"


def test_green_mutant_survives_selected_tests() -> None:
    assert classify(0, _counts(tests=3)) == "SURVIVED_SELECTED_TESTS"


def test_timeout_is_not_a_kill() -> None:
    assert classify(1, _counts(failures=1), timed_out=True) == "TIMEOUT"
