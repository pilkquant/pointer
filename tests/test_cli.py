"""CLI smoke tests — test the actual command-line interface."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from pointer import __version__
from pointer.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


class TestCLIBasic:
    def test_version(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert __version__ in captured.out

    def test_help_no_command(self, capsys):
        result = main([])
        assert result == 0
        captured = capsys.readouterr()
        assert "pointer" in captured.out.lower()

    def test_help_flag(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0


class TestCLIAnalyze:
    def test_analyze_pure_python(self, capsys, tmp_path):
        output_dir = str(tmp_path / "report")
        result = main(
            [
                "analyze",
                str(FIXTURES / "pure_python"),
                "--target",
                "compare",
                "--output",
                output_dir,
            ]
        )
        assert result == 0

        # Check files exist
        assert (tmp_path / "report" / "report.md").exists()
        assert (tmp_path / "report" / "report.json").exists()

    def test_analyze_rust_target(self, capsys, tmp_path):
        output_dir = str(tmp_path / "report")
        result = main(
            [
                "analyze",
                str(FIXTURES / "pure_python"),
                "--target",
                "rust",
                "--output",
                output_dir,
            ]
        )
        assert result == 0

    def test_analyze_cpp_target(self, capsys, tmp_path):
        output_dir = str(tmp_path / "report")
        result = main(
            [
                "analyze",
                str(FIXTURES / "pure_python"),
                "--target",
                "cpp",
                "--output",
                output_dir,
            ]
        )
        assert result == 0

    def test_analyze_nonexistent_path(self, capsys):
        result = main(["analyze", "/nonexistent/path/xyz123"])
        assert result == 2  # invalid path

    def test_analyze_file_not_dir(self, capsys):
        result = main(["analyze", __file__])
        assert result == 2  # not a directory

    def test_analyze_malformed_repo(self, capsys, tmp_path):
        """Malformed repo should still produce a report, not crash."""
        output_dir = str(tmp_path / "report")
        result = main(
            [
                "analyze",
                str(FIXTURES / "malformed"),
                "--output",
                output_dir,
            ]
        )
        assert result == 0
        assert (tmp_path / "report" / "report.md").exists()

    def test_analyze_with_exclude(self, capsys, tmp_path):
        output_dir = str(tmp_path / "report")
        result = main(
            [
                "analyze",
                str(FIXTURES / "pure_python"),
                "--output",
                output_dir,
                "--exclude",
                "*.py",
            ]
        )
        assert result == 0

    def test_default_output_dir(self, capsys, tmp_path, monkeypatch):
        """Default output should be pointer-report/."""
        monkeypatch.chdir(tmp_path)
        result = main(["analyze", str(FIXTURES / "pure_python")])
        assert result == 0
        assert (tmp_path / "pointer-report" / "report.md").exists()


class TestCLIDoctor:
    def test_doctor_exits_zero(self, capsys):
        result = main(["doctor"])
        assert result == 0

    def test_doctor_output(self, capsys):
        main(["doctor"])
        captured = capsys.readouterr()
        assert "Pointer" in captured.out
        assert "Python" in captured.out


class TestCLISubprocess:
    """Test via actual subprocess to catch packaging issues."""

    def test_subprocess_version(self):
        result = subprocess.run(
            [sys.executable, "-m", "pointer", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert __version__ in result.stdout

    def test_subprocess_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "pointer", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "analyze" in result.stdout
        assert "doctor" in result.stdout

    def test_subprocess_analyze(self, tmp_path):
        output = tmp_path / "out"
        result = subprocess.run(
            [sys.executable, "-m", "pointer", "analyze", str(FIXTURES / "pure_python"), "--output", str(output)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert (output / "report.md").exists()
        assert (output / "report.json").exists()
