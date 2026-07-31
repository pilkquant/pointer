# Contributing to Pointer

Thank you for your interest in contributing to Pointer! This document covers the development setup, testing requirements, and contribution workflow.

## Development setup

```bash
git clone https://github.com/pilkquant/pointer.git
cd pointer
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"  # or: pip install -e . && pip install pytest ruff build
```

Verify your setup:

```bash
pointer --version          # should print "pointer 0.1.0"
pointer doctor             # environment check
python3 -m pytest -q       # all 97 tests should pass
ruff check src/ tests/     # should be clean
```

## Architecture overview

Pointer is organized around a clean pipeline with zero runtime dependencies:

```
src/pointer/
  cli.py              # argparse CLI: analyze, doctor
  pipeline.py         # orchestrates 8 analysis stages → AnalysisReport
  models.py           # typed dataclasses for all report structures
  doctor.py           # environment/capability check
  analyzer/
    filesystem.py     # symlink-safe traversal, exclusion patterns
    discovery.py      # packaging/build/lockfile/entry-point discovery
    ast_scanner.py    # stdlib AST: imports + dynamic blocker detection
    native_ext.py     # composite native extension detection
    metrics.py        # LOC/file counts, module inventory
    test_layout.py    # test framework detection + oracle readiness
    deps_kb.py        # curated dependency disposition knowledge base
    scoring.py        # Rust-vs-C++ recommendation engine
  report/
    markdown.py       # human-readable Markdown report
    json_out.py       # deterministic schema-versioned JSON
```

### Analysis pipeline

```
analyze(path, target) →
  1. discovery.discover(root)          → ProjectStructure
  2. ast_scanner.scan_python(root)     → AstAnalysis (imports, blockers)
  3. native_ext.detect(root, structure)→ NativeExtAnalysis
  4. metrics.measure(root)             → CodeMetrics
  5. test_layout.detect(root)          → TestAnalysis
  6. deps_kb.disposition(imports)      → DepDisposition[]
  7. scoring.recommend(target, ...)     → Recommendation
  → report.json_out + report.markdown
```

## Testing

Pointer is developed test-first. Every analyzer and scoring path has unit tests. The test suite includes:

- **Unit tests** per analyzer module (`test_discovery.py`, `test_ast_scanner.py`, `test_native_ext.py`, `test_scoring.py`)
- **Integration tests** on four fixture repositories (`test_integration.py`):
  - `fixtures/pure_python/` — tiny pure-Python package
  - `fixtures/dynamic/` — eval/exec/metaclass/monkeypatch
  - `fixtures/native_ext/` — maturin + PyO3/CFFI/ctypes signals
  - `fixtures/malformed/` — syntax errors, missing pyproject
- **Security tests** proving no target code execution and no symlink escape (`test_security.py`)
- **Determinism tests** proving report output is stable across runs (`test_determinism.py`)
- **Report quality tests** verifying report structure and content (`test_report_quality.py`)
- **CLI tests** exercising the full command-line interface (`test_cli.py`)

Run the full suite:

```bash
python3 -m pytest -v
```

## Adding to the dependency knowledge base

The curated dependency disposition KB (`src/pointer/analyzer/deps_kb.py`) is a key value feature. To add or correct an entry:

1. Each entry needs: package name, disposition, Rust notes, C++ notes, provenance (source URL), and confidence level
2. Valid dispositions: `direct_replacement`, `adapt`, `ffi_wrap`, `keep_python`, `rewrite`, `blocker`, `unknown`
3. **Never fabricate replacements.** If you're not sure, use `unknown` disposition with `Confidence.LOW`
4. Add a unit test verifying the new entry

## Code style

- Python 3.11+ (use modern syntax: `X | None` over `Optional[X]`)
- Ruff for linting and formatting: `ruff check src/ tests/ && ruff format --check src/ tests/`
- Line length: 120 characters
- Every public function and class has a docstring

## Pull request checklist

- [ ] Tests pass: `python3 -m pytest -q`
- [ ] Lint passes: `ruff check src/ tests/`
- [ ] Format is clean: `ruff format --check src/ tests/`
- [ ] New analyzers have unit tests
- [ ] No runtime dependencies added without strong justification
- [ ] No target code execution introduced
- [ ] Commit messages are clear and descriptive

## Safety constraints

Pointer's core value proposition is safe, static analysis. Contributions must not:

- Import or execute code from the target repository
- Make network calls during analysis
- Add required runtime dependencies
- Follow symlinks outside the repository root

Security tests in `tests/test_security.py` enforce these constraints. Any PR that breaks them will not be merged.

## Reporting issues

Use [GitHub Issues](https://github.com/pilkquant/pointer/issues). For security-related findings, please describe the concern without including exploit code in the public issue.
