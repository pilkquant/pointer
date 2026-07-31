"""tinycalc — a tiny arithmetic expression calculator.

Supports +, -, *, / with standard precedence and parentheses-free evaluation.
Reads from command-line arguments or stdin.
"""

from __future__ import annotations

import sys


def tokenize(expr: str) -> list[str]:
    """Tokenize an arithmetic expression into numbers and operators."""
    tokens: list[str] = []
    current = ""
    for ch in expr:
        if ch.isspace():
            if current:
                tokens.append(current)
                current = ""
            continue
        if ch in "+-*/":
            if current:
                tokens.append(current)
                current = ""
            tokens.append(ch)
        elif ch.isdigit() or ch == ".":
            current += ch
        else:
            raise ValueError(f"unexpected character: {ch}")
    if current:
        tokens.append(current)
    return tokens


def evaluate(expr: str) -> float:
    """Evaluate an arithmetic expression.

    Supports +, -, *, / with * and / having higher precedence than + and -.
    Returns the result as a float.
    Raises ValueError on invalid input.
    """
    tokens = tokenize(expr)
    if not tokens:
        raise ValueError("empty expression")

    # Parse into values and operators
    values: list[float] = []
    ops: list[str] = []

    expect_value = True
    for tok in tokens:
        if expect_value:
            try:
                values.append(float(tok))
            except ValueError:
                raise ValueError(f"invalid number: {tok}") from None
            expect_value = False
        else:
            if tok not in ("+", "-", "*", "/"):
                raise ValueError(f"expected operator, got: {tok}")
            ops.append(tok)
            expect_value = True

    if expect_value:
        raise ValueError("expression ends with operator")

    # First pass: * and /
    i = 0
    while i < len(ops):
        if ops[i] in ("*", "/"):
            left = values[i]
            right = values[i + 1]
            if ops[i] == "*":
                values[i] = left * right
            else:
                if right == 0:
                    raise ZeroDivisionError("division by zero")
                values[i] = left / right
            values.pop(i + 1)
            ops.pop(i)
        else:
            i += 1

    # Second pass: + and -
    result = values[0]
    for j, op in enumerate(ops):
        right = values[j + 1]
        if op == "+":
            result += right
        else:
            result -= right

    return result


def format_result(value: float) -> str:
    """Format a result: integers without decimal point."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return str(value)


def main() -> int:
    """CLI entry point."""
    args = sys.argv[1:]

    if not args:
        # Read from stdin
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                result = evaluate(line)
                print(format_result(result))
            except (ValueError, ZeroDivisionError) as e:
                print(f"Error: {e}")
                return 1
        return 0

    # Evaluate the expression from arguments
    expr = " ".join(args)
    try:
        result = evaluate(expr)
        print(format_result(result))
        return 0
    except (ValueError, ZeroDivisionError) as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
