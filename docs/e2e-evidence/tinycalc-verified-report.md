# Pointer Port Report — 20260731-045053-71a720

**Generated:** 2026-07-31T04:52:53+00:00
**Pointer version:** 0.2.0
**Target language:** rust
**Agent backend:** codex (codex-cli 0.146.0)

## Verdict: ✅ verified

The Rust port builds in release mode, passes all checks (fmt, clippy, test), and every configured oracle case passes differential verification.

## Source
- Path: `/Users/pilk/.hermes/kanban/boards/madoka-works/workspaces/t_0f01784a/examples/tinycalc`

## Oracle
- Execution consent: yes
- Network isolated: no
- Total cases: 8
- Successful captures: 8
- Failed captures: 0

## Stage Timeline
- ✅ preflight: completed (0.1s)
- ✅ analyze: completed (0.0s)
- ✅ oracle_capture: completed (0.1s)
- ✅ plan: completed (0.0s)
- ✅ generate: completed (119.8s)
- ✅ native_build: completed (0.1s)
- ✅ differential_verify: completed (0.1s)
- ✅ repair: completed (0.0s)

## Native Build
- Binary: `/tmp/pointer-e2e/.pointer/output/20260731-045053-71a720/target/release/port-target`
- SHA-256: `64cab2d59687706076353d6b7579b1ef8a52f905bfc610b5aba1d9463e00c22f`

## Differential Verification
- Total cases: 8
- Passed: 8
- Failed: 0

- ✅ basic_add
- ✅ basic_subtract
- ✅ multiply
- ✅ divide_float
- ✅ precedence
- ✅ stdin
- ✅ error_invalid
- ✅ error_div_zero

## Warnings
- ⚠️ Generation prompt saved to /tmp/pointer-e2e/.pointer/runs/20260731-045053-71a720/prompt-generate.md

## Definition of 'verified'

A run is `verified` only when ALL of:
1. Rust workspace builds in release mode
2. `cargo fmt --check` passes
3. `cargo clippy --all-targets --all-features -- -D warnings` passes
4. `cargo test --all-targets --all-features` passes
5. Every configured oracle case passes differential verification
6. Evidence points to actual commands and artifacts

## Limitations
- Dynamic Python behavior (reflection, monkeypatching) cannot be fully captured
- Nondeterministic outputs cannot be verified
- Network-dependent behavior may differ
- Database, GUI, and distributed system ports are out of scope
- Native C/Fortran dependencies require manual handling
