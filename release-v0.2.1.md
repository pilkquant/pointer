## Pointer v0.2.1

This maintenance release hardens the verified Python-to-Rust porting workflow introduced in v0.2.0.

**Maintainer:** Madoka · PilkQuant

### Fixed

- Finds `cargo` and `rustc` in common rustup and platform-specific locations even when they are absent from `PATH`.
- Keeps native-build and verification evidence when a stage fails.
- Prevents repair-loop cycling and advances each bounded repair attempt with fresh diagnostics.
- Repairs the bundled `tinycalc` fixture packaging and imports.
- Keeps generated Pointer run state and reports out of Git.

### Verification

- Full Python suite: 212 passed; 9 Rust-dependent integration tests skipped on the release-preparation Mac because no Rust toolchain is installed.
- Ruff lint and format checks pass.
- Source distribution and universal wheel build successfully.
- The wheel installs in a clean virtual environment.
- Installed CLI reports `pointer 0.2.1`.
- Installed-wheel smoke analysis of `examples/tinycalc` produces Markdown and JSON reports.
- GitHub CI is green on the two fixes included in this release.

### Install after publication

```bash
pip install pointer-cli==0.2.1
```