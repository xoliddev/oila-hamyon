from decimal import Decimal

import pytest

from hamyon.core.money import (AmountError, convert_minor, eval_amount, fmt, fmt_decimal, parse_minor,
                               split_proportionally, to_minor)


@pytest.mark.parametrize("expr,expected", [
    ("12000", "12000"),
    ("2*9500", "19000"),
    ("0.5*60000", "30000.0"),
    ("50000-8000", "42000"),
    ("1 500 000", "1500000"),
    ("1,5 mln", "1500000"),
    ("12 ming", "12000"),
    ("12k", "12000"),
    ("2.5mln", "2500000"),
    ("12500.50", "12500.50"),
    ("(3+2)*1000/4", "1250"),
    ("2×4500", "9000"),
])
def test_eval_amount(expr, expected):
    assert eval_amount(expr) == Decimal(expected)


@pytest.mark.parametrize("bad", ["", "abc", "__import__('os')", "1/0", "2**10", None, "x" * 400])
def test_eval_amount_rejects(bad):
    with pytest.raises(AmountError):
        eval_amount(bad)


def test_no_float_error():
    # float bilan 0.1+0.2 != 0.3 bo'lardi
    assert parse_minor("0.1+0.2") == 30
    assert parse_minor("3*33333.33") == 9999999


def test_rounding_half_up():
    assert to_minor(Decimal("1.005")) == 101
    assert to_minor(Decimal("1.004")) == 100
    assert parse_minor("10/3") == 333


def test_fmt():
    assert fmt(125000000) == "1 250 000 so'm"
    assert fmt(1250050) == "12 500,50 so'm"
    assert fmt(1250, "USD") == "12,50 $"
    assert fmt(-500000) == "-5 000 so'm"
    assert fmt(500000, signed=True) == "+5 000 so'm"
    assert fmt(0) == "0 so'm"


def test_fmt_decimal():
    assert fmt_decimal("1.50") == "1,5"
    assert fmt_decimal("2") == "2"
    assert fmt_decimal("12700.00") == "12 700"


def test_split_proportionally_exact_sum():
    parts = split_proportionally(1000, [3333, 3333, 3334])
    assert sum(parts) == 1000
    parts = split_proportionally(1, [1, 1, 1])
    assert sum(parts) == 1
    parts = split_proportionally(250000, [1250000, 890000, 320000, 45000])
    assert sum(parts) == 250000


def test_convert_minor():
    # 100 $ (10000 sent) * 12 700,55 = 1 270 055 so'm
    assert convert_minor(10000, "12700.55") == 127005500
    # so'mdan dollarga
    assert convert_minor(127005500, "1", "12700.55") == 10000
