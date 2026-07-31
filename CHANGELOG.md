# Changelog

All notable changes to Pointer will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-07-31

### Added — The Final Fantasy: Codex-backed Python→Rust porting

- `pointer port PATH --target rust --agent codex` — one-command porting workflow.
- `pointer status [RUN_ID]` — list all porting runs or show details.
- `pointer continue RUN_ID` — resume an interrupted porting run.
- `pointer verify RUN_ID` — re-check verification status of a completed run.
- Durable run state machine with 10 typed stages, atomic JSON persistence, and crash-safe resume.
- Replaceable `AgentBackend` protocol with `CodexBackend` (real CLI) and `FakeBackend` (deterministic test double).
- Codex CLI discovery via `POINTER_CODEX_BIN`, `~/.local/bin/codex`, and PATH.
- JSONL event parsing with defensive handling of malformed lines.
- Process group management with clean termination and configurable timeouts.
- `pointer.toml` oracle specification: versioned config for executable test cases with declarative normalizers.
- Python oracle capture with sanitized subprocess environment, per-case timeouts, and SHA-256 output hashing.
- Differential verification comparing normalized stdout/stderr/exit-codes between Python and Rust.
- Native build pipeline: `cargo fmt --check`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`, `cargo build --release`.
- Bounded repair loop with configurable budget, structured diagnostic prompts, and session resume.
- Staged prompt construction with source tree limits, analysis context, oracle transcripts, and acceptance criteria.
- Evidence reports: `report.md` (human-readable) and `evidence.json` (machine-readable) with full stage timeline.
- Verdict vocabulary: `verified`, `generated_unverified`, `blocked`, `failed`, `cancelled`.
- Secret redaction (API keys, tokens, JWTs, passwords) from all logs and reports.
- Path confinement and symlink-escape prevention for the porting workspace.
- Source-execution consent enforcement (`--allow-source-execution` as a separate security boundary).
- Dangerous flag assertion (never uses `--dangerously-bypass-approvals-and-sandbox`).
- Example fixture repository: `examples/tinycalc/` — arithmetic calculator with CLI, stdin, tests, and 8 oracle cases.
- 124 new tests for porting (221 total): state machine, config, security, backend, oracle, prompts, integration.
- CI job for porting tests with Rust toolchain on Linux and macOS.
- Updated `pointer doctor` to report porting tool availability.

### Changed

- Version bumped to 0.2.0.
- README updated with porting documentation, security model, and architecture overview.
- CI matrix narrowed to Python 3.11–3.13 (3.14 pending ecosystem support).

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

[0.2.0]: https://github.com/pilkquant/pointer/releases/tag/v0.2.0
[0.1.0]: https://github.com/pilkquant/pointer/releases/tag/v0.1.0
