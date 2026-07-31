## The Final Fantasy — one-command verified Python to Rust porting

```bash
pointer port ./python-repo --target rust --agent codex
```

One command: analysis, oracle capture, Codex generation, Rust build/test, differential verification, bounded repair, evidence report.

### Real E2E verification (tinycalc fixture)

Verified with real OpenAI Codex CLI 0.146.0:

- **Verdict:** verified
- **Run ID:** 20260731-045053-71a720
- **Oracle cases:** 8/8 passed (basic_add, basic_subtract, multiply, divide_float, precedence, stdin, error_invalid, error_div_zero)
- **Repair count:** 0
- **Binary SHA-256:** 64cab2d59687706076353d6b7579b1ef8a52f905bfc610b5aba1d9463e00c22f
- **Generation time:** 119.8s
- **Evidence:** docs/e2e-evidence/tinycalc-verified-report.md

### What is new

- **pointer port** — one-command porting workflow with durable state machine
- **Replaceable agent backend** — CodexBackend (real CLI) + FakeBackend (deterministic tests)
- **Executable oracle** — pointer.toml defines deterministic test cases, captured before generation
- **Differential verification** — normalized stdout/stderr/exit-code comparison between Python and Rust
- **Bounded repair** — structured diagnostic feedback to Codex via resume, default 3 attempts
- **Evidence reports** — report.md + evidence.json with full stage timeline and verdict
- **Security** — source-execution consent boundary, secret redaction, path confinement, no dangerous sandbox bypass
- **pointer status**, **pointer continue**, **pointer verify** — run management commands

### Stats

- 221 tests (97 original + 124 new), all passing
- CI green on Linux, macOS, Windows (Python 3.11 to 3.13)
- Zero runtime dependencies
- 3,500 LOC new porting engine across 10 modules

### Acceptance gates

1. Existing v0.1 behavior and tests remain green (97 tests)
2. New CLI workflows install and run from built wheel
3. Deterministic fake-backend E2E passes locally and in CI
4. Real Codex CLI E2E: verdict verified, 8/8 oracle cases
5. Rust workspace passes fmt, Clippy -D warnings, tests, release build
6. Interruption/resume and bounded repair proven by tests
7. Security tests: consent, path confinement, redaction, no dangerous flag, no false verified
8. Lint, format, all tests, package build, clean-wheel install, smoke tests pass
9. GitHub Actions green (commit 73d6856)
10. Repository remains PUBLIC under pilkquant
11. This release published (not on PyPI)

-- Madoka
