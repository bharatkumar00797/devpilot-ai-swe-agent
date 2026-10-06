import pytest

from calculator import add, divide, multiply


def test_add():
    assert add(2, 3) == 5


def test_multiply():
    assert multiply(4, 5) == 20


def test_divide_by_zero():
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)
