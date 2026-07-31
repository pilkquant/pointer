"""Tests for tinycalc."""
import pytest
from tinycalc import evaluate, format_result, tokenize


class TestTokenize:
    def test_simple(self):
        assert tokenize("1 + 2") == ["1", "+", "2"]

    def test_no_spaces(self):
        assert tokenize("3*4") == ["3", "*", "4"]

    def test_floats(self):
        assert tokenize("1.5 + 2.5") == ["1.5", "+", "2.5"]

    def test_empty(self):
        assert tokenize("") == []

    def test_whitespace_only(self):
        assert tokenize("   ") == []

    def test_invalid_char(self):
        with pytest.raises(ValueError):
            tokenize("1 & 2")


class TestEvaluate:
    def test_addition(self):
        assert evaluate("1 + 2") == 3.0

    def test_subtraction(self):
        assert evaluate("10 - 4") == 6.0

    def test_multiplication(self):
        assert evaluate("3 * 4") == 12.0

    def test_division(self):
        assert evaluate("10 / 4") == 2.5

    def test_precedence(self):
        assert evaluate("2 + 3 * 4") == 14.0

    def test_precedence2(self):
        assert evaluate("10 - 2 * 3") == 4.0

    def test_precedence3(self):
        assert evaluate("10 / 2 + 3") == 8.0

    def test_float_result(self):
        assert evaluate("10 / 4") == 2.5

    def test_empty(self):
        with pytest.raises(ValueError):
            evaluate("")

    def test_div_by_zero(self):
        with pytest.raises(ZeroDivisionError):
            evaluate("1 / 0")

    def test_trailing_operator(self):
        with pytest.raises(ValueError):
            evaluate("1 + ")

    def test_invalid_number(self):
        with pytest.raises(ValueError):
            evaluate("abc + 2")


class TestFormatResult:
    def test_integer(self):
        assert format_result(3.0) == "3"

    def test_float(self):
        assert format_result(2.5) == "2.5"

    def test_large_integer(self):
        assert format_result(1000000.0) == "1000000"
