# Pointer

**Point it at Python. Get an evidence-backed path to native.**

Pointer is a static portability-analysis CLI that examines a Python repository and produces a detailed, evidence-backed report guiding your decision to port to Rust or C++ (or stay in Python). It never imports or executes your code — every finding comes from static filesystem discovery and AST analysis.

## Why Pointer?

Before committing to a native port, you need answers:

- Is this codebase even portable, or is it too dynamic?
- What dependencies will block me, and which have native equivalents?
- Where are the natural module boundaries for incremental porting?
- Rust or C++ — which is the better fit given *this* codebase's signals?
- Do I have enough test coverage to verify a port against Python as the oracle?

Pointer answers all of these with **observed evidence, transparent scoring, and explicit confidence levels**. It never fabricates findings it hasn't detected, and it labels unknowns as unknowns.

## Install

```bash
pip install pointer-cli
```

Pointer has **zero runtime dependencies** — it uses only the Python standard library. No transitive packages to audit, no install conflicts, instant setup.

Requires Python 3.11+.

## 60-second example

```bash
# Analyze any Python repository
pointer analyze ./my-project

# Compare Rust vs C++ suitability (default)
pointer analyze ./my-project --target compare

# Get a Rust-focused assessment
pointer analyze ./my-project --target rust

# Reports land in ./pointer-report/ by default
ls pointer-report/
# report.md   report.json
```

Output:

```
Pointer 0.1.0 — analyzing /home/you/my-project
Target: compare

✓ Analysis complete.
  Markdown: pointer-report/report.md
  JSON:     pointer-report/report.json

**my-project** (42 Python files, 3,200 lines) pure Python . Recommendation: **hybrid** (confidence: medium).
```

## What the report tells you

Every report answers nine questions across both Markdown (for humans) and JSON (for tooling):

1. **Repository profile** — project name, version, Python requirement, file/line counts, build system
2. **Packaging & layout** — build backends (setuptools, hatch, poetry, maturin...), lockfiles (uv, poetry, pip), source roots, entry points, declared dependencies
3. **Native extension status** — is this pure Python or already partly native? Detects `.so`/`.pyd`/`.dylib` files, wheel tags, native build backends, and binding tool references (PyO3, pybind11, Cython, CFFI, ctypes, nanobind)
4. **Imports & dependencies** — full import inventory classified into stdlib, external, and local; plus a curated dependency portability disposition table
5. **Dynamic language blockers** — eval, exec, metaclasses, monkeypatching, dynamic imports, `__getattr__` — the constructs that make static porting hardest
6. **Test & oracle evidence** — test framework detection (pytest, unittest, hypothesis), fixture/conftest presence, and an oracle-readiness assessment for future differential verification
7. **Migration seams & ordering** — recommended module boundaries for incremental porting, prioritized by dependency concentration and blocker presence
8. **Target recommendation** — transparent Rust-vs-C++-vs-hybrid-vs-stay-Python scoring with every factor exposed; allows an inconclusive result
9. **Evidence taxonomy** — every finding labeled as observed, inferred, or unknown with confidence levels

### Sample report excerpt

```markdown
## 8. Target Recommendation

### Recommendation: 🦀 Rust (confidence: 🟢 high)

Rust target assessment:
Favorable: Small codebase (420 Python lines); No significant dynamic language blockers.
Rust offers structural memory safety (borrow checker), unified build system (cargo),
and mature Python bindings (PyO3/maturin).

| Factor | Base | Rust adj. | C++ adj. | Reason |
|--------|------|----------|----------|--------|
| codebase_size | +1 | +1 | +1 | Small codebase (420 Python lines) |
| dynamic_constructs | +1 | +1 | +1 | No significant dynamic blockers detected |
| type_coverage | +1 | +1 | 0 | High type annotation coverage (85%) |
| test_oracle | +1 | +1 | +1 | Strong test suite |
```

## Safety model

Pointer is designed to analyze untrusted repositories safely:

- **No code execution.** Target code is never imported, never executed, never added to `sys.path`. All analysis uses stdlib `ast.parse()` on file contents.
- **No network access.** Zero outbound calls. No telemetry, no update checks, no API keys.
- **Symlink-safe traversal.** Symlinks pointing outside the repository root are never followed. Files are resolved and checked against the root boundary.
- **Size limits.** Oversized files are skipped gracefully.
- **Graceful degradation.** Syntax errors, missing manifests, namespace packages, and partial repositories are handled without crashing.

See the [security tests](tests/test_security.py) for verifiable proof of these guarantees.

## CLI reference

```bash
pointer --help
pointer --version
pointer analyze PATH [options]
pointer doctor
```

### `pointer analyze`

```
pointer analyze ./my-project [options]

Options:
  --target {compare,rust,cpp}  Target language for analysis (default: compare)
  --output, -o DIR             Output directory (default: pointer-report)
  --exclude GLOB               Additional exclude pattern (repeatable)
```

Exit codes: `0` success, `2` invalid path/arguments, `1` internal failure.

### `pointer doctor`

Reports Pointer version, Python version, platform, and the availability of optional external tools (cargo, cmake, etc.). External tools are never required for static analysis.

## Exclusion defaults

Pointer automatically excludes: `.git`, `__pycache__`, `*.egg-info`, `*.dist-info`, `.tox`, `.nox`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `node_modules`, `.venv`, `venv`, `env`, `.env`, `build`, `dist`, `.eggs`, `site-packages`, `.idea`, `.vscode`.

Add custom excludes with `--exclude`.

## Limitations

Pointer 0.1 is a **static** analyzer. It does not:

- Port or translate code
- Execute the target repository or its tests
- Call an LLM or any network service
- Measure runtime performance or coverage
- Generate build files or scaffolding

These are planned for future versions (see [Roadmap](#roadmap)).

Dynamic language constructs (eval, monkeypatching, metaclasses) are detected heuristically. Pointer flags them as **signals** — it cannot fully resolve their runtime behavior without execution, which is out of scope for 0.1.

## Roadmap

- **0.1** (this release): Static portability analysis with Markdown + JSON reports
- **Future**: Incremental porting orchestration, runtime coverage analysis, golden-master oracle capture, differential testing harness, PyO3/nanobind project scaffolding

Pointer 0.1 is the trustworthy foundation. Later versions build on its static analysis to orchestrate actual porting work — always with Python as the executable oracle.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Pointer is developed test-first with 97 unit, integration, security, and determinism tests.

## License

[Apache License 2.0](LICENSE)
