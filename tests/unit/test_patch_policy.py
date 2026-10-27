import pytest

from packages.diagnosis.contracts import FileChange, PatchProposal
from packages.diagnosis.retrieval import fixture_source
from packages.verification.patches import validate_patch


@pytest.mark.parametrize(
    "path",
    ["../calculator.py", "/calculator.py", "test_calculator.py", "pytest.ini", "a\\calculator.py"],
)
def test_protected_or_unsafe_paths_rejected(path):
    with pytest.raises(ValueError):
        validate_patch(
            PatchProposal(explanation="bad", files=[FileChange(path=path, content="pass")]),
            fixture_source("calculator-add"),
        )


@pytest.mark.parametrize(
    "replacement",
    [
        "__import__('os')._exit(0)",
        "print('bypass')",
        "eval('left+right')",
        "globals()['left']",
    ],
)
def test_application_code_cannot_bypass_checks(replacement):
    original = fixture_source("calculator-add")
    content = original["calculator.py"].replace("left - right", replacement)
    with pytest.raises(ValueError):
        validate_patch(
            PatchProposal(
                explanation="bad", files=[FileChange(path="calculator.py", content=content)]
            ),
            original,
        )


def test_pure_arithmetic_repair_returns_reviewable_diff():
    original = fixture_source("calculator-add")
    content = original["calculator.py"].replace("left - right", "left + right")
    changes, diff = validate_patch(
        PatchProposal(explanation="fix", files=[FileChange(path="calculator.py", content=content)]),
        original,
    )
    assert list(changes) == ["calculator.py"]
    assert "+    return left + right" in diff
