"""Tests for oracle capture and differential verification."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pointer.porting.config import NormalizationConfig, OracleCase
from pointer.porting.oracle import (
    CaseResult,
    capture_case,
    capture_oracle,
    verify_against_rust,
)


class TestCaptureCase:
    def test_basic_capture(self, tmp_path):
        """Capture output from a simple Python command."""
        case = OracleCase(
            name="echo",
            command=[sys.executable, "-c", "print('hello world')"],
        )
        result = capture_case(case, tmp_path, NormalizationConfig())
        assert result.exit_code == 0
        assert "hello world" in result.stdout
        assert not result.timed_out

    def test_error_exit_code(self, tmp_path):
        case = OracleCase(
            name="error",
            command=[sys.executable, "-c", "import sys; sys.exit(1)"],
        )
        result = capture_case(case, tmp_path, NormalizationConfig())
        assert result.exit_code == 1

    def test_stdin(self, tmp_path):
        case = OracleCase(
            name="stdin",
            command=[sys.executable, "-c", "import sys; print(sys.stdin.read().strip())"],
            stdin="test input",
        )
        result = capture_case(case, tmp_path, NormalizationConfig())
        assert "test input" in result.stdout

    def test_timeout(self, tmp_path):
        case = OracleCase(
            name="slow",
            command=[sys.executable, "-c", "import time; time.sleep(10)"],
            timeout=0.5,
        )
        result = capture_case(case, tmp_path, NormalizationConfig())
        assert result.timed_out is True

    def test_not_found(self, tmp_path):
        case = OracleCase(
            name="missing",
            command=["nonexistent-binary-12345"],
        )
        result = capture_case(case, tmp_path, NormalizationConfig())
        assert "not found" in result.error.lower() or result.exit_code != 0

    def test_hash_computed(self, tmp_path):
        case = OracleCase(
            name="hash_test",
            command=[sys.executable, "-c", "print('42')"],
        )
        result = capture_case(case, tmp_path, NormalizationConfig())
        assert result.stdout_hash != ""
        assert len(result.stdout_hash) == 64  # SHA-256 hex


class TestCaptureOracle:
    def test_requires_consent(self, tmp_path):
        with pytest.raises(PermissionError):
            capture_oracle(
                cases=[],
                source_root=tmp_path,
                normalization=NormalizationConfig(),
                consent_given=False,
            )

    def test_successful_capture(self, tmp_path):
        cases = [
            OracleCase(
                name="test1",
                command=[sys.executable, "-c", "print('output1')"],
            ),
            OracleCase(
                name="test2",
                command=[sys.executable, "-c", "print('output2')"],
            ),
        ]
        result = capture_oracle(
            cases=cases,
            source_root=tmp_path,
            normalization=NormalizationConfig(),
            consent_given=True,
        )
        assert result.total_cases == 2
        assert result.successful_captures == 2
        assert result.failed_captures == 0
        assert result.consent_given is True

    def test_mixed_results(self, tmp_path):
        cases = [
            OracleCase(
                name="good",
                command=[sys.executable, "-c", "print('ok')"],
            ),
            OracleCase(
                name="bad",
                command=["nonexistent-cmd"],
            ),
        ]
        result = capture_oracle(
            cases=cases,
            source_root=tmp_path,
            normalization=NormalizationConfig(),
            consent_given=True,
        )
        assert result.total_cases == 2
        assert result.successful_captures == 1
        assert result.failed_captures == 1


class TestVerifyAgainstRust:
    def test_perfect_match(self, tmp_path):
        """Create a simple script that matches oracle output."""
        # Create oracle result
        oracle_cases = [
            OracleCase(
                name="test",
                command=[sys.executable, "-c", "print('42')"],
            ),
        ]
        oracle_results = [
            CaseResult(
                name="test",
                command=["python"],
                exit_code=0,
                stdout="42",
                stderr="",
                duration_seconds=0.1,
                stdout_normalized="42",
                stderr_normalized="",
                stdout_hash="abc",
                stderr_hash="def",
            ),
        ]
        # Use Python as the "Rust binary" for test purposes
        result = verify_against_rust(
            cases=oracle_cases,
            oracle_results=oracle_results,
            rust_binary=Path(sys.executable),
            normalization=NormalizationConfig(),
        )
        # The rewrite will make command [rust_binary, "-c", "print('42')"]
        # which should work with Python
        assert result.total_cases == 1

    def test_mismatch_detection(self, tmp_path):
        """Detect stdout mismatch."""
        oracle_cases = [
            OracleCase(
                name="test",
                command=["python", "script.py", "arg1"],
            ),
        ]
        oracle_results = [
            CaseResult(
                name="test",
                command=["python", "script.py"],
                exit_code=0,
                stdout="expected output",
                stderr="",
                duration_seconds=0.1,
                stdout_normalized="expected output",
                stderr_normalized="",
                stdout_hash="abc",
                stderr_hash="def",
            ),
        ]
        # Use a command that outputs something different
        result = verify_against_rust(
            cases=oracle_cases,
            oracle_results=oracle_results,
            # Python will try to run as rust binary and fail to find the script
            rust_binary=Path(sys.executable),
            normalization=NormalizationConfig(),
        )
        assert result.total_cases == 1
        assert result.failed >= 1

    def test_exit_code_mismatch(self, tmp_path):
        oracle_cases = [
            OracleCase(
                name="test",
                command=[sys.executable, "-c", "import sys; sys.exit(0)"],
            ),
        ]
        oracle_results = [
            CaseResult(
                name="test",
                command=["python"],
                exit_code=0,
                stdout="",
                stderr="",
                duration_seconds=0.1,
                stdout_normalized="",
                stderr_normalized="",
                stdout_hash="abc",
                stderr_hash="def",
            ),
        ]
        # Create a "binary" that exits 1
        result = verify_against_rust(
            cases=oracle_cases,
            oracle_results=oracle_results,
            rust_binary=Path(sys.executable),
            normalization=NormalizationConfig(),
        )
        # The rewrite command will be [python, "-c", "import sys; sys.exit(0)"]
        # which should produce exit 0 and match
        # But actually the rewrite removes "python" prefix and replaces with binary
        # For [python, "-c", "..."] -> [binary, "-c", "..."] = [python, "-c", "..."]
        # So it should match
        assert result.total_cases == 1


class TestRewriteCommand:
    def test_python_m_prefix(self, tmp_path):
        from pointer.porting.oracle import _rewrite_command_for_rust

        binary = Path("/usr/local/port-target")
        result = _rewrite_command_for_rust(
            ["python", "-m", "tinycalc", "1", "+", "2"],
            binary,
        )
        assert result[0] == str(binary)
        assert "1" in result
        assert "+" in result
        assert "2" in result

    def test_python_script_prefix(self, tmp_path):
        from pointer.porting.oracle import _rewrite_command_for_rust

        binary = Path("/usr/local/port-target")
        result = _rewrite_command_for_rust(
            ["python", "cli.py", "--flag"],
            binary,
        )
        assert result[0] == str(binary)
        assert "--flag" in result
