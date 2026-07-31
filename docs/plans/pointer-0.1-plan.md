# Pointer 0.1 Implementation Plan

**Date**: 2026-07-31
**Author**: Madoka
**Status**: Active

## Goal

Ship Pointer 0.1 as a trustworthy, zero-dependency, static Python portability-analysis
CLI that produces Markdown + JSON reports guiding Rust/C++ porting decisions.

## Key Design Decisions

1. **Zero runtime dependencies.** Pure Python stdlib (ast, tomllib, argparse, json, pathlib).
   This makes installation instant (`pip install pointer` just works, no transitive deps to audit),
   aligns with "keep runtime dependencies minimal," and is the strongest security posture for a
   tool that analyzes untrusted repos.

2. **No execution of target code.** All analysis is static: filesystem discovery + stdlib AST parsing.
   The target repo is never imported, never executed, never added to sys.path.

3. **Symlink-safe traversal.** Files outside the repo root via symlinks are never followed.

4. **Schema-versioned JSON.** `schema_version` field enables future evolution. Deterministic ordering.

5. **Evidence/inference/confidence taxonomy.** Every finding carries a source label:
   `observed` (directly detected), `inferred` (deduced from signals), `unknown` (not enough data).
   Confidence: high/medium/low.

## Module Layout

```
src/pointer/
  __init__.py           # __version__, package metadata
  __main__.py           # python -m pointer
  cli.py                # argparse-based CLI: analyze, doctor
  models.py             # Typed dataclasses for all report structures
  pipeline.py           # Orchestrates analyzers → report
  doctor.py             # Environment/capability check
  analyzer/
    __init__.py
    discovery.py        # Packaging/build/lockfile/entry-point discovery
    ast_scanner.py      # AST import inventory + dynamic blocker detection
    native_ext.py       # Composite native extension detection
    metrics.py          # LOC/file counts, module inventory
    test_layout.py      # Test framework/file detection + oracle readiness
    deps_kb.py          # Curated dependency disposition knowledge base
    scoring.py          # Rust vs C++ recommendation engine
  report/
    __init__.py
    json_out.py         # JSON report writer
    markdown.py         # Markdown report writer
```

## Analysis Pipeline

```
analyze(path, target) →
  1. discovery.discover(root)        → ProjectStructure
  2. ast_scanner.scan_python(root)    → AstAnalysis (imports, blockers)
  3. native_ext.detect(root, structure) → NativeExtAnalysis
  4. metrics.measure(root)            → CodeMetrics
  5. test_layout.detect(root)         → TestAnalysis
  6. deps_kb.disposition(imports)     → DepDisposition[]
  7. scoring.recommend(target, ...)    → Recommendation
  → report.json_out + report.markdown
```

## CLI Interface

```
pointer --help
pointer --version
pointer analyze PATH [--target compare|rust|cpp] [--output DIR] [--exclude GLOB ...]
pointer doctor
```

Exit codes: 0 success, 2 invalid path/args, 1 internal failure.

## Test Strategy

- Unit tests per analyzer module (mock fixtures)
- Integration tests with golden fixtures:
  - `fixtures/pure_python/` — tiny pure-Python package
  - `fixtures/dynamic/` — eval/exec/metaclass/monkeypatch
  - `fixtures/native_ext/` — .so files, maturin/pyo3 source refs
  - `fixtures/malformed/` — syntax errors, missing pyproject
- Golden/snapshot tests for report determinism
- Security tests: no import of target code, no symlink escape
- Clean-venv install + CLI smoke test

## CI

GitHub Actions matrix: Ubuntu/macOS/Windows × Python 3.11/3.12/3.13/3.14.
Jobs: lint (ruff), test (pytest), build (python -m build), smoke (install wheel, run CLI).
