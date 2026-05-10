from __future__ import annotations

from decimal import Decimal

import pytest

from personal_assistant_bot.hours import format_hours_total, format_subtotals, parse_getmm, parse_hours

# --- parse_hours edge cases ---


def test_parse_hours_pure_decimal() -> None:
    assert parse_hours("3.5") == Decimal("3.5")


def test_parse_hours_negative_decimal() -> None:
    assert parse_hours("-3.5") == Decimal("-3.5")


def test_parse_hours_hours_only() -> None:
    assert parse_hours("1h") == Decimal("1")


def test_parse_hours_with_and_separator() -> None:
    assert parse_hours("1h and 30m") == Decimal("1.5")


def test_parse_hours_negative_minutes_only() -> None:
    assert parse_hours("-30m") == Decimal("-0.5")


def test_parse_hours_invalid_string_raises() -> None:
    with pytest.raises(ValueError, match="Hours must be"):
        parse_hours("abc")


def test_parse_hours_empty_string_raises() -> None:
    with pytest.raises(ValueError, match="Hours must be"):
        parse_hours("")


def test_parse_hours_whitespace_only_raises() -> None:
    with pytest.raises(ValueError, match="Hours must be"):
        parse_hours("   ")


def test_parse_hours_minutes_roll_into_hours() -> None:
    assert parse_hours("1h 90m") == Decimal("2.5")


def test_parse_hours_leading_trailing_whitespace() -> None:
    assert parse_hours("  2h 30m  ") == Decimal("2.5")


# --- parse_getmm edge cases ---


def test_parse_getmm_boundary_low() -> None:
    assert parse_getmm("get01") == 1


def test_parse_getmm_boundary_high() -> None:
    assert parse_getmm("get12") == 12


def test_parse_getmm_zero_raises() -> None:
    with pytest.raises(ValueError, match="getMM"):
        parse_getmm("get00")


def test_parse_getmm_thirteen_raises() -> None:
    with pytest.raises(ValueError, match="getMM"):
        parse_getmm("get13")


def test_parse_getmm_single_digit_raises() -> None:
    with pytest.raises(ValueError, match="getMM"):
        parse_getmm("get1")


def test_parse_getmm_uppercase_raises() -> None:
    with pytest.raises(ValueError, match="getMM"):
        parse_getmm("GET01")


def test_parse_getmm_extra_suffix_raises() -> None:
    with pytest.raises(ValueError, match="getMM"):
        parse_getmm("get01extra")


# --- format_hours_total edge cases ---


def test_format_hours_total_zero() -> None:
    assert format_hours_total(Decimal("0")) == "0h 0m"


def test_format_hours_total_negative() -> None:
    assert format_hours_total(Decimal("-1.5")) == "-1h 30m"


def test_format_hours_total_fractional_minute_rounding() -> None:
    assert format_hours_total(Decimal("0.083333")) == "0h 5m"


def test_format_hours_total_exact_hour() -> None:
    assert format_hours_total(Decimal("1")) == "1h 0m"


# --- format_subtotals edge cases ---


def test_format_subtotals_both_zero() -> None:
    assert format_subtotals(Decimal("0"), Decimal("0")) == "Day subtotal: 0h 0m\nMonth subtotal: 0h 0m"
