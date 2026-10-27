"""External deterministic regression criteria, never supplied to the model context."""

import pytest
from calculator import add


@pytest.mark.parametrize(
    "left,right,expected",
    [
        (0, 0, 0),
        (0, 7, 7),
        (7, 0, 7),
        (-2, -3, -5),
        (-2, 3, 1),
        (100000, 50000, 150000),
        (3, 2, 5),
    ],
)
def test_addition_contract(left, right, expected):
    assert add(left, right) == expected
