"""Oracle capture — execute Python source to capture deterministic reference outputs.

The oracle is the Python source itself. We run it with configured commands,
capture stdout/stderr/exit-code, and store these as reference outputs for
differential verification against the generated Rust.

Security:
- Source execution requires explicit consent (--allow-source-execution).
- Commands run with a sanitized environment (no secrets).
- Per-case timeout enforced.
- No network isolation by default (stated in reports).
- No shell=True ever — commands are argv arrays.
"""

from __future__ import annotations

import hashlib
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import NormalizationConfig, OracleCase
from .security import sanitize_env, truncate_output


@dataclass
class CaseResult:
    """Result of running a single oracle case."""

    name: str
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    error: str = ""
    # Normalized versions for comparison
    stdout_normalized: str = ""
    stderr_normalized: str = ""
    # Hash of normalized output
    stdout_hash: str = ""
    stderr_hash: str = ""
    # Raw output truncated for storage
    stdout_raw: str = ""
    stderr_raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for state.json storage."""
        return {
            "name": self.name,
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout_normalized,
            "stderr": self.stderr_normalized,
            "duration_seconds": self.duration_seconds,
            "timed_out": self.timed_out,
            "error": self.error,
            "stdout_hash": self.stdout_hash,
            "stderr_hash": self.stderr_hash,
        }


@dataclass
class OracleCaptureResult:
    """Result of capturing all oracle cases."""

    cases: list[CaseResult] = field(default_factory=list)
    total_cases: int = 0
    successful_captures: int = 0
    failed_captures: int = 0
    network_isolated: bool = False
    consent_given: bool = False
    environment: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "cases": [c.to_dict() for c in self.cases],
            "total_cases": self.total_cases,
            "successful_captures": self.successful_captures,
            "failed_captures": self.failed_captures,
            "network_isolated": self.network_isolated,
            "consent_given": self.consent_given,
            "environment": self.environment,
        }


def _hash_output(text: str) -> str:
    """SHA-256 hash of text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def capture_case(
    case: OracleCase,
    source_root: Path,
    normalization: NormalizationConfig,
    *,
    extra_env: dict[str, str] | None = None,
) -> CaseResult:
    """Run a single oracle case and capture its output.

    Args:
        case: The oracle case definition.
        source_root: Working directory for command execution.
        normalization: Output normalization rules.
        extra_env: Additional env vars (from allowlist) to pass through.
    """
    start = time.monotonic()

    # Build sanitized environment
    clean_env = sanitize_env(dict(__import__("os").environ))
    if extra_env:
        for key, val in extra_env.items():
            clean_env[key] = val

    # Prepare stdin
    stdin_data = case.stdin.encode("utf-8") if case.stdin else None

    try:
        proc = subprocess.run(
            case.command,
            cwd=str(source_root),
            env=clean_env,
            input=stdin_data,
            capture_output=True,
            timeout=case.timeout,
        )
        stdout_raw = proc.stdout.decode("utf-8", errors="replace")
        stderr_raw = proc.stderr.decode("utf-8", errors="replace")
        exit_code = proc.returncode
        timed_out = False
        error = ""
    except subprocess.TimeoutExpired as e:
        stdout_raw = e.stdout.decode("utf-8", errors="replace") if e.stdout else ""
        stderr_raw = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        exit_code = -1
        timed_out = True
        error = f"Timed out after {case.timeout}s"
    except FileNotFoundError as e:
        return CaseResult(
            name=case.name,
            command=case.command,
            exit_code=-1,
            stdout="",
            stderr="",
            duration_seconds=time.monotonic() - start,
            error=f"Command not found: {e}",
        )

    duration = time.monotonic() - start

    # Normalize outputs
    stdout_norm = normalization.normalize(stdout_raw)
    stderr_norm = normalization.normalize(stderr_raw)

    return CaseResult(
        name=case.name,
        command=case.command,
        exit_code=exit_code,
        stdout=stdout_norm,
        stderr=stderr_norm,
        duration_seconds=duration,
        timed_out=timed_out,
        error=error,
        stdout_normalized=stdout_norm,
        stderr_normalized=stderr_norm,
        stdout_hash=_hash_output(stdout_norm),
        stderr_hash=_hash_output(stderr_norm),
        stdout_raw=truncate_output(stdout_raw),
        stderr_raw=truncate_output(stderr_raw),
    )


def capture_oracle(
    cases: list[OracleCase],
    source_root: Path,
    normalization: NormalizationConfig,
    *,
    consent_given: bool,
    extra_env: dict[str, str] | None = None,
    network_isolated: bool = False,
) -> OracleCaptureResult:
    """Capture all oracle cases from the Python source.

    Requires explicit consent. If not given, raises PermissionError.
    """
    if not consent_given:
        raise PermissionError(
            "Source execution requires explicit consent. Use --allow-source-execution or interactive confirmation."
        )

    result = OracleCaptureResult(
        consent_given=True,
        network_isolated=network_isolated,
        environment={
            "cwd": str(source_root),
            "python": __import__("sys").version,
            "network_isolated": network_isolated,
        },
    )

    for case in cases:
        case_result = capture_case(case, source_root, normalization, extra_env=extra_env)
        result.cases.append(case_result)
        if case_result.error or case_result.timed_out:
            result.failed_captures += 1
        else:
            result.successful_captures += 1

    result.total_cases = len(cases)
    return result


# ---------------------------------------------------------------------------
# Differential verification
# ---------------------------------------------------------------------------


@dataclass
class VerificationMismatch:
    """A single mismatch between Python oracle and Rust output."""

    case_name: str
    field: str  # "stdout", "stderr", "exit_code"
    expected: str
    actual: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_name": self.case_name,
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass
class DifferentialResult:
    """Result of running all oracle cases against the Rust binary."""

    results: list[dict[str, Any]] = field(default_factory=list)
    mismatches: list[VerificationMismatch] = field(default_factory=list)
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    all_passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": self.results,
            "mismatches": [m.to_dict() for m in self.mismatches],
            "total_cases": self.total_cases,
            "passed": self.passed,
            "failed": self.failed,
            "all_passed": self.all_passed,
        }


def _rewrite_command_for_rust(
    command: list[str],
    rust_binary: Path,
    rust_args: list[str] | None = None,
) -> list[str]:
    """Rewrite a Python oracle command to invoke the Rust binary instead.

    Strategy: replace ``python -m <module> [args]`` patterns with the Rust
    binary path. If rust_args is provided, append them.
    """
    # Common pattern: ["python", "-m", "module", ...] or ["python", "script.py", ...]
    if len(command) >= 2 and command[0] in ("python", "python3"):
        # Skip "python -m module" prefix, keep remaining args
        rest = command[2:]  # Skip "python" and either "-m" or script path
        if command[1] == "-m" and len(command) >= 3:
            rest = command[3:]  # Skip "python -m module"
        return [str(rust_binary)] + rest

    # If command starts with a module name, replace with binary
    return [str(rust_binary)] + command[1:]


def verify_against_rust(
    cases: list[OracleCase],
    oracle_results: list[CaseResult],
    rust_binary: Path,
    normalization: NormalizationConfig,
    *,
    extra_env: dict[str, str] | None = None,
) -> DifferentialResult:
    """Run oracle cases against the Rust binary and compare.

    Compares normalized stdout, stderr, and exit codes.
    """
    result = DifferentialResult()
    clean_env = sanitize_env(dict(__import__("os").environ))
    if extra_env:
        clean_env.update(extra_env)

    # Index oracle results by case name
    oracle_by_name = {r.name: r for r in oracle_results}

    for case in cases:
        oracle = oracle_by_name.get(case.name)
        if not oracle:
            result.mismatches.append(
                VerificationMismatch(
                    case_name=case.name,
                    field="oracle",
                    expected="oracle result exists",
                    actual="missing",
                )
            )
            result.failed += 1
            result.total_cases += 1
            continue

        # Rewrite command for Rust binary
        rust_cmd = _rewrite_command_for_rust(case.command, rust_binary)
        stdin_data = case.stdin.encode("utf-8") if case.stdin else None

        start = time.monotonic()
        try:
            proc = subprocess.run(
                rust_cmd,
                env=clean_env,
                input=stdin_data,
                capture_output=True,
                timeout=case.timeout,
            )
            rust_stdout = normalization.normalize(proc.stdout.decode("utf-8", errors="replace"))
            rust_stderr = normalization.normalize(proc.stderr.decode("utf-8", errors="replace"))
            rust_exit = proc.returncode
        except subprocess.TimeoutExpired:
            rust_stdout = ""
            rust_stderr = f"[timeout after {case.timeout}s]"
            rust_exit = -1
        except FileNotFoundError as e:
            result.mismatches.append(
                VerificationMismatch(
                    case_name=case.name,
                    field="binary",
                    expected=str(rust_binary),
                    actual=f"not found: {e}",
                )
            )
            result.failed += 1
            result.total_cases += 1
            continue

        duration = time.monotonic() - start

        # Compare
        case_pass = True
        case_result: dict[str, Any] = {
            "case_name": case.name,
            "rust_command": rust_cmd,
            "duration_seconds": round(duration, 3),
            "passed": True,
            "comparisons": {},
        }

        # Compare exit code
        exit_match = rust_exit == oracle.exit_code
        case_result["comparisons"]["exit_code"] = {
            "expected": oracle.exit_code,
            "actual": rust_exit,
            "match": exit_match,
        }
        if not exit_match:
            case_pass = False
            result.mismatches.append(
                VerificationMismatch(
                    case_name=case.name,
                    field="exit_code",
                    expected=str(oracle.exit_code),
                    actual=str(rust_exit),
                )
            )

        # Compare stdout
        stdout_match = rust_stdout == oracle.stdout_normalized
        case_result["comparisons"]["stdout"] = {
            "expected_hash": oracle.stdout_hash,
            "actual_hash": _hash_output(rust_stdout),
            "match": stdout_match,
        }
        if not stdout_match:
            case_pass = False
            result.mismatches.append(
                VerificationMismatch(
                    case_name=case.name,
                    field="stdout",
                    expected=truncate_output(oracle.stdout_normalized, 500),
                    actual=truncate_output(rust_stdout, 500),
                )
            )

        # Compare stderr (only if oracle had non-empty stderr or we expect it)
        if oracle.stderr_normalized or rust_stderr:
            stderr_match = rust_stderr == oracle.stderr_normalized
            case_result["comparisons"]["stderr"] = {
                "expected_hash": oracle.stderr_hash,
                "actual_hash": _hash_output(rust_stderr),
                "match": stderr_match,
            }
            if not stderr_match and oracle.stderr_normalized:
                # Only flag as mismatch if oracle expected specific stderr
                case_pass = False
                result.mismatches.append(
                    VerificationMismatch(
                        case_name=case.name,
                        field="stderr",
                        expected=truncate_output(oracle.stderr_normalized, 500),
                        actual=truncate_output(rust_stderr, 500),
                    )
                )

        case_result["passed"] = case_pass
        if case_pass:
            result.passed += 1
        else:
            result.failed += 1
        result.total_cases += 1
        result.results.append(case_result)

    result.all_passed = result.total_cases > 0 and result.failed == 0
    return result
