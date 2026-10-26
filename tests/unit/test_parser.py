import pytest

from packages.ingestion.fixtures import load_fixture
from packages.ingestion.pytest_parser import parse_pytest_log


def test_actual_saved_assertion_log():
    result = parse_pytest_log(load_fixture("calculator-add").log.decode())
    assert result.failure_category == "APPLICATION_CODE_REGRESSION"
    assert result.failed_test_identifiers == ["test_calculator.py::test_add_positive_numbers"]
    assert result.failures[0].exception_type == "AssertionError"
    assert result.failures[0].message == "assert -1 == 5"
    assert result.failures[0].traceback[0].path == "test_calculator.py"
    assert result.failures[0].traceback[0].line == 5


def test_collection_import_error_and_ansi():
    result = parse_pytest_log("""
________________ ERROR collecting tests/test_api.py ________________
tests/test_api.py:3: in <module>
    import missing
E   ModuleNotFoundError: No module named 'missing'
\x1b[31mERROR tests/test_api.py\x1b[0m
""")
    assert result.failure_category == "DEPENDENCY_OR_IMPORT_FAILURE"
    assert result.failures[0].message == "No module named 'missing'"
    assert result.failures[0].traceback[0].line == 3


def test_multiple_failures_keep_their_own_exceptions():
    result = parse_pytest_log("""
________________ test_one ________________
tests/test_app.py:4: in test_one
E   ValueError: first error
________________ test_two ________________
tests/test_app.py:8: in test_two
E   AssertionError: second error
FAILED tests/test_app.py::test_one - ValueError: first error
FAILED tests/test_app.py::test_two - AssertionError: second error
""")
    assert [f.exception_type for f in result.failures] == ["ValueError", "AssertionError"]
    assert [f.message for f in result.failures] == ["first error", "second error"]
    assert [f.traceback[0].line for f in result.failures] == [4, 8]
    assert result.failure_category == "UNKNOWN_OR_UNSUPPORTED"


@pytest.mark.parametrize("text", ["", "1 passed in 0.01s", "Traceback (most recent call last):\n"])
def test_missing_summary_is_explicitly_unsupported(text):
    result = parse_pytest_log(text)
    assert result.failure_category == "UNKNOWN_OR_UNSUPPORTED"
    assert not result.failures
    assert any("No pytest short" in note for note in result.limitations)


def test_fixture_configuration_error():
    result = parse_pytest_log("""
________________ ERROR at setup of test_db ________________
E       fixture 'database' not found
ERROR tests/test_db.py::test_db
""")
    assert result.failure_category == "TEST_OR_ENVIRONMENT_CONFIGURATION"
    assert result.failures[0].exception_type is None


def test_ambiguous_same_named_tests_do_not_get_invented_tracebacks():
    result = parse_pytest_log("""
________________ test_same ________________
a.py:1: in test_same
E   ValueError: one
________________ test_same ________________
b.py:2: in test_same
E   TypeError: two
FAILED a.py::test_same - ValueError: one
FAILED b.py::test_same - TypeError: two
""")
    assert all(not f.traceback for f in result.failures)
    assert any("unambiguous" in note for note in result.limitations)
