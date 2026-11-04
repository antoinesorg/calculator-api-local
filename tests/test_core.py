"""Tests for core arithmetic functions."""

import math

import pytest

from core import add, divide, multiply, subtract


@pytest.mark.parametrize(
    ("func", "a", "b", "expected"),
    [
        (add, 2, 3, 5),
        (add, -2, 3, 1),
        (add, 0, 0, 0),
        (subtract, 5, 3, 2),
        (subtract, 3, 5, -2),
        (multiply, 4, 3, 12),
        (multiply, -4, 3, -12),
        (multiply, 5, 0, 0),
        (divide, 6, 3, 2),
        (divide, 1, 4, 0.25),
        (divide, -6, 3, -2),
        (divide, 0, 5, 0),
    ],
)
def test_arithmetic(func, a, b, expected):
    assert func(a, b) == expected


def test_float_imprecision_is_preserved():
    assert add(0.1, 0.2) == 0.1 + 0.2
    assert add(0.1, 0.2) != 0.3
    assert add(0.1, 0.2) == pytest.approx(0.3)


def test_large_values():
    assert multiply(1e308, 10) == math.inf
    assert add(1e308, 1e308) == math.inf


def test_nan_and_inf():
    assert math.isnan(add(math.nan, 1))
    assert subtract(math.inf, math.inf) != 0
    assert divide(math.inf, 2) == math.inf


def test_divide_by_zero_raises():
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        divide(1, 0)


def test_divide_by_negative_zero_raises():
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        divide(1, -0.0)
