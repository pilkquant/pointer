"""Tests for prompt construction — bounded context, source limits, repair prompts."""

from __future__ import annotations

from pointer.porting.config import PortConfig
from pointer.porting.oracle import CaseResult, OracleCaptureResult
from pointer.porting.prompts import (
    PROMPT_VERSION,
    build_generation_prompt,
    build_repair_prompt,
    write_prompt_to_file,
)


class TestGenerationPrompt:
    def test_includes_source_code(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')")
        prompt = build_generation_prompt(
            source_root=tmp_path,
            port_config=PortConfig(),
            oracle_result=None,
            analysis_json=None,
            output_dir=tmp_path / "output",
        )
        assert "print('hello')" in prompt
        assert "main.py" in prompt

    def test_includes_version(self, tmp_path):
        prompt = build_generation_prompt(
            source_root=tmp_path,
            port_config=PortConfig(),
            oracle_result=None,
            analysis_json=None,
            output_dir=tmp_path / "output",
        )
        assert f"v{PROMPT_VERSION}" in prompt

    def test_includes_acceptance_criteria(self, tmp_path):
        prompt = build_generation_prompt(
            source_root=tmp_path,
            port_config=PortConfig(),
            oracle_result=None,
            analysis_json=None,
            output_dir=tmp_path / "output",
        )
        assert "cargo fmt" in prompt
        assert "cargo clippy" in prompt
        assert "cargo test" in prompt
        assert "cargo build --release" in prompt

    def test_includes_oracle_transcript(self, tmp_path):
        oracle_result = OracleCaptureResult(
            cases=[
                CaseResult(
                    name="test1",
                    command=["python", "main.py"],
                    exit_code=0,
                    stdout="42\n",
                    stderr="",
                    duration_seconds=0.1,
                    stdout_normalized="42",
                    stderr_normalized="",
                    stdout_hash="abc",
                    stderr_hash="def",
                ),
            ],
            total_cases=1,
            successful_captures=1,
        )
        prompt = build_generation_prompt(
            source_root=tmp_path,
            port_config=PortConfig(),
            oracle_result=oracle_result,
            analysis_json=None,
            output_dir=tmp_path / "output",
        )
        assert "test1" in prompt
        assert "42" in prompt

    def test_includes_analysis(self, tmp_path):
        prompt = build_generation_prompt(
            source_root=tmp_path,
            port_config=PortConfig(),
            oracle_result=None,
            analysis_json={"project_name": "test-project", "summary": "test"},
            output_dir=tmp_path / "output",
        )
        assert "test-project" in prompt or "Static Analysis" in prompt

    def test_source_file_limit(self, tmp_path):
        """Prompt should cap number of source files."""
        for i in range(30):
            (tmp_path / f"file_{i}.py").write_text(f"# file {i}")
        prompt = build_generation_prompt(
            source_root=tmp_path,
            port_config=PortConfig(),
            oracle_result=None,
            analysis_json=None,
            output_dir=tmp_path / "output",
        )
        assert "truncated" in prompt.lower() or prompt.count("FILE:") <= 25

    def test_skips_test_files(self, tmp_path):
        (tmp_path / "main.py").write_text("# main")
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_main.py").write_text("# test")
        prompt = build_generation_prompt(
            source_root=tmp_path,
            port_config=PortConfig(),
            oracle_result=None,
            analysis_json=None,
            output_dir=tmp_path / "output",
        )
        assert "main.py" in prompt
        # Test files should be excluded
        assert "test_main.py" not in prompt


class TestRepairPrompt:
    def test_includes_build_errors(self):
        prompt = build_repair_prompt(
            build_result={"errors": ["cargo test failed"]},
            verification_result=None,
            repair_attempt=1,
            max_repairs=3,
        )
        assert "cargo test failed" in prompt
        assert "attempt 1/3" in prompt

    def test_includes_verification_mismatches(self):
        prompt = build_repair_prompt(
            build_result={"errors": []},
            verification_result={
                "mismatches": [
                    {
                        "case_name": "test1",
                        "field": "stdout",
                        "expected": "42",
                        "actual": "43",
                    }
                ]
            },
            repair_attempt=2,
            max_repairs=3,
        )
        assert "test1" in prompt
        assert "42" in prompt
        assert "43" in prompt

    def test_includes_clippy_output(self):
        prompt = build_repair_prompt(
            build_result={
                "errors": [],
                "clippy": {
                    "success": False,
                    "stdout": "warning: unused variable",
                    "stderr": "",
                },
            },
            verification_result=None,
            repair_attempt=1,
            max_repairs=3,
        )
        assert "unused variable" in prompt


class TestWritePrompt:
    def test_writes_file(self, tmp_path):
        path = write_prompt_to_file("test prompt content", tmp_path, "generate")
        assert path.exists()
        assert path.read_text() == "test prompt content"
        assert "generate" in path.name
