# tinycalc — a tiny arithmetic expression calculator

A minimal Python CLI used as a Pointer porting fixture. It demonstrates:
- A CLI accepting arguments and stdin
- Deterministic stdout and exit behavior
- Multiple operations with precedence
- An error path (invalid input)
- Unit tests

## Usage

```bash
python -m tinycalc 1 + 2        # → 3
python -m tinycalc "10 / 4"     # → 2.5
echo "3 * 4" | python -m tinycalc  # → 12
python -m tinycalc invalid       # exit 1
```
