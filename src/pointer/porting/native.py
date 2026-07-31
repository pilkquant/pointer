"""Native build and verification — Cargo commands and artifact handling.

Runs the actual Rust toolchain commands with argv arrays, timeouts,
and structured output capture. No fake checks.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .security import sanitize_env, truncate_output


@dataclass
class CommandResult:
    """Result of a single native command execution."""

    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    success: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": truncate_output(self.stdout, 10000),
            "stderr": truncate_output(self.stderr, 10000),
            "duration_seconds": round(self.duration_seconds, 3),
            "timed_out": self.timed_out,
            "success": self.success,
        }


@dataclass
class NativeBuildResult:
    """Result of the full native build pipeline."""

    fmt_result: CommandResult | None = None
    clippy_result: CommandResult | None = None
    test_result: CommandResult | None = None
    build_result: CommandResult | None = None
    binary_path: Path | None = None
    binary_hash: str | None = None
    all_passed: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fmt": self.fmt_result.to_dict() if self.fmt_result else None,
            "clippy": self.clippy_result.to_dict() if self.clippy_result else None,
            "test": self.test_result.to_dict() if self.test_result else None,
            "build": self.build_result.to_dict() if self.build_result else None,
            "binary_path": str(self.binary_path) if self.binary_path else None,
            "binary_hash": self.binary_hash,
            "all_passed": self.all_passed,
            "errors": self.errors,
        }


def discover_cargo() -> str | None:
    """Discover the cargo binary."""
    return shutil.which("cargo")


def discover_rustc() -> str | None:
    """Discover rustc binary."""
    return shutil.which("rustc")


def _run_command(
    argv: list[str],
    cwd: Path,
    timeout: float = 300.0,
) -> CommandResult:
    """Run a command with timeout and capture output."""
    start = time.monotonic()
    clean_env = sanitize_env(dict(__import__("os").environ))

    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            env=clean_env,
            capture_output=True,
            timeout=timeout,
        )
        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace")
        exit_code = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode("utf-8", errors="replace") if e.stdout else ""
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        exit_code = -1
        timed_out = True
    except FileNotFoundError as e:
        return CommandResult(
            command=argv,
            exit_code=-1,
            stdout="",
            stderr=str(e),
            duration_seconds=time.monotonic() - start,
        )

    duration = time.monotonic() - start
    return CommandResult(
        command=argv,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=duration,
        timed_out=timed_out,
        success=exit_code == 0,
    )


def check_cargo_available() -> bool:
    """Check if cargo is available."""
    return discover_cargo() is not None


def check_rust_available() -> bool:
    """Check if the full Rust toolchain is available."""
    return all(
        [
            discover_cargo() is not None,
            discover_rustc() is not None,
            shutil.which("cargo-clippy") is not None or shutil.which("clippy-driver") is not None,
            shutil.which("cargo-fmt") is not None or shutil.which("rustfmt") is not None,
        ]
    )


def cargo_fmt_check(workspace: Path, timeout: float = 60.0) -> CommandResult:
    """Run cargo fmt --check."""
    cargo = discover_cargo()
    if not cargo:
        return CommandResult(["cargo"], -1, "", "cargo not found", 0.0)
    return _run_command([cargo, "fmt", "--check"], workspace, timeout)


def cargo_clippy(
    workspace: Path,
    timeout: float = 300.0,
) -> CommandResult:
    """Run cargo clippy with -D warnings."""
    cargo = discover_cargo()
    if not cargo:
        return CommandResult(["cargo"], -1, "", "cargo not found", 0.0)

    # Try clippy via rustup proxy first, then direct
    clippy = shutil.which("cargo-clippy") or shutil.which("clippy-driver")
    if clippy and "cargo-clippy" in clippy:
        return _run_command(
            [cargo, "clippy", "--all-targets", "--all-features", "--", "-D", "warnings"],
            workspace,
            timeout,
        )
    # Fallback: cargo clippy via cargo
    return _run_command(
        [cargo, "clippy", "--all-targets", "--all-features", "--", "-D", "warnings"],
        workspace,
        timeout,
    )


def cargo_test(
    workspace: Path,
    timeout: float = 300.0,
) -> CommandResult:
    """Run cargo test."""
    cargo = discover_cargo()
    if not cargo:
        return CommandResult(["cargo"], -1, "", "cargo not found", 0.0)
    return _run_command(
        [cargo, "test", "--all-targets", "--all-features"],
        workspace,
        timeout,
    )


def cargo_build_release(
    workspace: Path,
    timeout: float = 300.0,
) -> tuple[CommandResult, Path | None]:
    """Run cargo build --release and return result + binary path.

    Returns (result, binary_path). binary_path is None if build failed.
    """
    cargo = discover_cargo()
    if not cargo:
        return CommandResult(["cargo"], -1, "", "cargo not found", 0.0), None

    result = _run_command([cargo, "build", "--release"], workspace, timeout)

    if not result.success:
        return result, None

    # Find the built binary
    release_dir = workspace / "target" / "release"
    if not release_dir.exists():
        return result, None

    # Look for the binary based on Cargo.toml package name
    cargo_toml = workspace / "Cargo.toml"
    binary_name = None
    if cargo_toml.exists():
        try:
            content = cargo_toml.read_text(encoding="utf-8")
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("name = "):
                    binary_name = line.split("=", 1)[1].strip().strip('"')
                    break
        except OSError:
            pass

    if binary_name:
        binary_path = release_dir / binary_name
        if binary_path.exists() and binary_path.is_file():
            return result, binary_path

    # Fallback: find any executable in release dir
    for entry in release_dir.iterdir():
        if entry.is_file() and entry.stat().st_mode & 0o111:
            # Skip .d and .o files
            if entry.suffix in (".d", ".o", ".rlib"):
                continue
            return result, entry

    return result, None


def hash_binary(binary_path: Path) -> str:
    """SHA-256 hash of a binary file."""
    h = hashlib.sha256()
    with open(binary_path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def run_full_build_pipeline(workspace: Path, timeout: float = 300.0) -> NativeBuildResult:
    """Run the complete native build pipeline.

    Executes in order:
    1. cargo fmt --check
    2. cargo clippy --all-targets --all-features -- -D warnings
    3. cargo test --all-targets --all-features
    4. cargo build --release

    Returns result with all command outputs.
    """
    result = NativeBuildResult()

    if not check_cargo_available():
        result.errors.append("cargo not found in PATH")
        return result

    # 1. fmt check
    result.fmt_result = cargo_fmt_check(workspace, timeout)
    if not result.fmt_result.success:
        result.errors.append("cargo fmt --check failed")

    # 2. clippy
    result.clippy_result = cargo_clippy(workspace, timeout)
    if not result.clippy_result.success:
        result.errors.append("cargo clippy failed")

    # 3. test
    result.test_result = cargo_test(workspace, timeout)
    if not result.test_result.success:
        result.errors.append("cargo test failed")

    # 4. build release
    result.build_result, result.binary_path = cargo_build_release(workspace, timeout)
    if not result.build_result.success:
        result.errors.append("cargo build --release failed")

    # Hash binary if we have one
    if result.binary_path:
        try:
            result.binary_hash = hash_binary(result.binary_path)
        except OSError:
            pass

    result.all_passed = (
        result.fmt_result is not None
        and result.fmt_result.success
        and result.clippy_result is not None
        and result.clippy_result.success
        and result.test_result is not None
        and result.test_result.success
        and result.build_result is not None
        and result.build_result.success
        and result.binary_path is not None
    )

    return result
