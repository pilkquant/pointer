# Changelog

All notable changes to Pointer will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-31

### Added

- Initial release of Pointer — a static Python portability-analysis CLI.
- `pointer analyze PATH --target {compare,rust,cpp}` command producing Markdown and JSON reports.
- `pointer doctor` command reporting version, platform, and optional tool availability.
- Repository structure discovery: `pyproject.toml`, `setup.cfg`, `setup.py`, requirements files, `uv.lock`, Poetry/PDM/Pipenv lockfiles, source roots, and entry points.
- AST-based import inventory classifying imports into stdlib, external, and local.
- Dynamic language blocker detection: eval, exec, compile, dynamic imports, metaclasses, `__getattr__`, monkeypatching, reflection-heavy calls.
- Composite native extension detection: compiled files (`.so`/`.pyd`/`.dylib`), wheel tags, build backends (maturin, meson-python, scikit-build-core, setuptools-rust), and binding tool references (PyO3, pybind11, nanobind, Cython, CFFI, ctypes).
- Code metrics: physical and logical LOC, file counts, module inventory.
- Test layout detection and oracle-readiness assessment for pytest, unittest, hypothesis, nose, and nox.
- Curated dependency disposition knowledge base with 45+ common Python packages, each with Rust and C++ porting notes and provenance.
- Transparent Rust-vs-C++-vs-hybrid-vs-stay-Python recommendation engine with exposed scoring factors and caveats.
- Migration seam suggestions based on module boundaries and dependency concentration.
- Evidence taxonomy distinguishing observed, inferred, and unknown findings with confidence levels.
- 97 unit, integration, security, and determinism tests.
- Zero runtime dependencies — pure Python stdlib.
- Symlink-safe traversal that never follows links outside the repository root.
- GitHub Actions CI on Linux, macOS, and Windows across Python 3.11–3.14.

[0.1.0]: https://github.com/pilkquant/pointer/releases/tag/v0.1.0
